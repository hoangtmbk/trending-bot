# Telegram Digest: Inline Summaries + Deep-Dive Follow-up

Date: 2026-04-18
Status: Approved

## Problem

The scheduled Telegram digest (`agents/notifiers/digest_pusher.py`) lists 15
trending items as clickable titles with source, score, and URL. The title
alone is often too thin to decide whether to click — the user asked to see
"summary or deep dive analysis if there is."

Both data points already exist in the database:

- **Filter summary** — every tracked item has a `filter` row in
  `item_analysis` whose JSON payload contains a one-line `summary` field
  (from `prompts/filter.md`).
- **Deep-dive analysis** — items the filter flags get processed by the
  `deep_diver` agent and written as a `deep_dive` row in `item_analysis`
  with fields `what_it_is`, `why_trending`, `pain_point`, `gap_analysis`,
  `competitors`, `app_idea`, `feasibility`.

Deep-dive coverage is partial: on any given cron fire, a subset of the 15
digest items (typically 3–8) will have a deep-dive ready.

## Goal

Surface both signals in the existing 08:00 / 20:00 UTC Telegram digest
without flooding the chat.

## Non-goals

- No new agent, cron schedule, or DB tables.
- No per-user preferences or config flags — enhancements are strictly
  additive defaults.
- No on-demand triggering of deep-dives from the digest (that's already
  available via `/deepdive` and inline buttons on single-item messages).
- No changes to the dashboard or `run.py` legacy pipeline.

## Design

### Two messages per cron fire

`DigestPusher.execute()` sends up to two Telegram messages per fire:

1. **Digest message** (extended) — the existing 15-item list, with a new
   italic summary line per item that has a filter summary.
2. **Deep-dives follow-up** (new, conditional) — one HTML message with
   compact deep-dive blocks for the subset of the 15 digest items that
   have a `deep_dive` row. Skipped entirely when that subset is empty.

Both messages go through the existing `_chunk()` helper (3900-char cap,
newline-boundary splits) so HTML tags never straddle chunks.

### Data fetch

`DigestPusher._select_items()` continues to return the 15 items. After it
returns, fetch analyses for those item IDs in two queries:

```sql
SELECT item_id, content FROM item_analysis
  WHERE analysis_type='filter' AND item_id IN (…);

SELECT item_id, content FROM item_analysis
  WHERE analysis_type='deep_dive' AND item_id IN (…);
```

Both are keyed into `dict[int, dict]` (item_id → parsed JSON payload).
Items are looked up by ID at render time; missing keys mean "no analysis
yet" and the relevant UI is suppressed.

If the same `item_id` has multiple rows of a given `analysis_type` (e.g.
a re-run), prefer the most recent — the query uses
`ORDER BY created_at DESC` and each `dict[item_id] = payload` is only
written once (first wins).

### Digest message format

Existing rendering (2 lines per item) becomes 3 lines when a filter
summary is available:

```
1. ⭐ <a href="https://github.com/MemPalace/mempalace">The best-benchmarked open-source AI memory system…</a>
   github · score 100 · https://github.com/MemPalace/mempalace
   💡 <i>Drop-in Python memory layer for LLMs that beats MemGPT on LoCoMo.</i>
```

Rules:

- Summary text is pulled from `json.loads(filter_row["content"])["summary"]`.
- Truncate summaries to 140 characters; append `…` if truncated.
- HTML-escape the summary with the existing `_escape_html` helper.
- If no filter row exists or `summary` is missing / malformed JSON, skip
  the summary line entirely. Log at DEBUG only.
- The rest of the rendering (title link, source/score/URL line) is
  unchanged.

Capacity check: 15 items × 3 lines averaging ~160 chars per line
≈ 2.4 KB → fits a single Telegram message; `_chunk()` remains a safety
net.

### Deep-dives follow-up format

Sent only when at least one digest item has a deep-dive. Header, then one
block per item, ordered by the same rank as the digest:

```
🔬 <b>Deep Dives</b>
<i>N of 15 items have detailed analysis.</i>

🔬 <b>#3 · Qwen3.6-35B-A3B</b> <i>(hackernews · score 100)</i>
<b>What:</b> Alibaba's new open-weights Qwen3 variant tuned for agentic coding…
<b>Why trending:</b> Beats DeepSeek-Coder on SWE-bench at 35B params.
<b>Pain:</b> Open-weight coding models lag GPT-4 class on multi-file agents.
<b>Idea:</b> Self-hosted coding agent for teams that can't send code to OpenAI.
<b>Competitors:</b> DeepSeek-Coder, CodeLlama, StarCoder2

🔬 <b>#5 · caveman</b> <i>(github · score 100)</i>
…
```

Rules:

- `#N` matches the digest-message index (1-based position in the 15-item
  list), so users can visually cross-reference.
- Per-field character caps:
  - `what_it_is`, `why_trending`, `pain_point`, `app_idea`: 200 chars,
    truncate with `…`.
  - `competitors`: first 5 entries, comma-joined.
- If a field is missing, empty, or literally `"N/A"` / `"n/a"`, skip that
  line — do not render "N/A".
- `gap_analysis` and `feasibility` are intentionally omitted from the
  follow-up to keep blocks scannable on mobile.
- No inline keyboard. Telegram attaches reply markup to the whole
  message, not per block, so it wouldn't be per-item meaningful.
- Order blocks by each item's position in the digest (already sorted by
  `normalized_score DESC`), not by deep-dive recency.
- URL is not repeated in the follow-up — the digest message carries it.

The existing `format_deep_dive()` formatter stays in place (it's still
used by the `/deepdive` single-item command). The new
`format_deep_dives_followup(items, deep_dives)` is a separate function.

### Sending

`DigestPusher._send(bot_token, chat_id, text)` currently sends one text.
Replace with a variant that accepts a list of texts and sends them
sequentially in one event loop:

```python
async def _do_send():
    bot = Bot(token=bot_token)
    for text in texts:
        for chunk in _chunk(text, limit=3900):
            await bot.send_message(
                chat_id=chat_id, text=chunk,
                parse_mode="HTML", disable_web_page_preview=True,
            )
```

`execute()` builds `[digest_text, followup_text]` and omits the second
entry if the follow-up is empty.

### Digest-record bookkeeping

`_record_digest()` continues to insert one row per fire keyed on the
digest items (not the follow-up). The follow-up is a derived view of the
same 15 items; no separate tracking needed.

## Edge cases

- **Empty `item_analysis` table**: digest renders unchanged from today;
  follow-up suppressed. Zero regression.
- **Item has a filter row but the JSON lacks `summary`**: summary line
  suppressed; other lines render normally.
- **Deep-dive JSON has partial fields**: render whichever of `what_it_is`,
  `why_trending`, `pain_point`, `app_idea`, `competitors` exist; skip
  missing ones. Do not render the block if *all* rendered fields are
  empty.
- **Combined follow-up exceeds 3900 chars**: `_chunk()` splits on newline
  boundaries. Since every HTML tag in the formatted blocks opens and
  closes on the same line, tag integrity is preserved.
- **Same item appears twice across digests**: existing cutoff logic in
  `_select_items` gates on `digests.created_at`; not affected.

## Files touched

- `interfaces/telegram/formatters.py` — extend `format_digest` to accept
  and render optional `filter_summaries: dict[int, dict]`. Add
  `format_deep_dives_followup(items, deep_dives: dict[int, dict]) -> str | None`.
- `agents/notifiers/digest_pusher.py` — fetch both analysis maps after
  item selection; adapt `_send` to accept a list of texts; conditionally
  append the follow-up.
- `tests/test_digest_pusher.py` — extend existing integration tests.
- `tests/test_formatters.py` — new unit tests for the formatters (or
  co-located in an existing test file if one emerges during
  implementation).

## Testing

**Unit tests** for formatters:

- `format_digest`
  - renders without summaries when the dict is empty / missing keys
  - renders the italic `💡` line when a summary is present
  - truncates at 140 chars with trailing `…`
  - HTML-escapes angle brackets and ampersands in the summary
- `format_deep_dives_followup`
  - returns `None` when the deep-dive dict is empty
  - renders N blocks in digest order, using the matching `#N` label
  - applies the 200-char per-field cap
  - skips fields that are missing / empty / `"N/A"`
  - joins up to 5 competitors

**Integration test** added to the existing `tests/test_digest_pusher.py`
using the module's `db` fixture (seed items + `item_analysis` rows):

- Mock `telegram.Bot`; assert `send_message` is called once when no
  deep-dives exist, twice when at least one does.
- Assert the digest text contains a summary line for items with filter
  rows.
- Assert the follow-up text contains blocks only for items with
  deep-dive rows.

## Rollout

Ship as a single change. The digest schedule (`0 8,20 * * *`) and user-
visible behaviour are strictly additive:

- New summary lines appear under items that already have filter rows.
- New follow-up message appears only when ≥1 digest item has a deep-dive.

No migration, no feature flag, no rollback dance.
