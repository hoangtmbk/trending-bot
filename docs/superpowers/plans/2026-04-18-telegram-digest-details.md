# Telegram Digest Details Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the scheduled Telegram digest to show a one-line filter summary per item and, when ≥1 of the 15 items has a `deep_dive` analysis row, send a compact combined follow-up message with deep-dive blocks.

**Architecture:** Two formatters in `interfaces/telegram/formatters.py` (extended `format_digest`, new `format_deep_dives_followup`). `DigestPusher` fetches both analysis maps after selecting items and calls its existing `_send` once for the digest, optionally again for the follow-up. No schema, config, or scheduling changes.

**Tech Stack:** Python 3.11+, `python-telegram-bot`, sqlite3 (via `db/database.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-04-18-telegram-digest-details-design.md`

---

## File Structure

**Modified:**
- `interfaces/telegram/formatters.py` — extend `format_digest(items, title=..., summaries: dict[int, str] | None = None)`; add `format_deep_dives_followup(items, deep_dives: dict[int, dict]) -> str | None`; export both. The existing `format_deep_dive(analysis)` single-item formatter stays (still used by `/deepdive`).
- `agents/notifiers/digest_pusher.py` — extend `_select_items` (or add a sibling method) to also return `filter_summaries: dict[int, str]` and `deep_dives: dict[int, dict]`; `execute()` builds both texts and calls `self._send` once or twice.

**Test files:**
- `tests/test_formatters.py` — new. Unit tests for both formatters.
- `tests/test_digest_pusher.py` — extend. Add integration tests for the new send-twice behaviour.

---

## Task 1: Formatter — digest with inline summaries

**Files:**
- Modify: `interfaces/telegram/formatters.py:28-52` (extend `format_digest`)
- Create: `tests/test_formatters.py`

The filter agent stores the whole LLM eval payload per row (see `agents/analysts/filter.py:50-54`): `json.dumps(eval_item)`. Each payload is a dict with a `summary` key — confirmed by `prompts/filter.md` and `tests/test_researchers.py:184`.

The formatter takes a pre-extracted `summaries: dict[int, str]` so JSON parsing stays out of the display layer.

- [ ] **Step 1: Write failing tests for `format_digest` with summaries**

Create `tests/test_formatters.py`:

```python
from __future__ import annotations

from interfaces.telegram.formatters import (
    format_digest,
    format_deep_dives_followup,
)


def _item(item_id: int, **kwargs) -> dict:
    base = {
        "id": item_id,
        "title": f"Item {item_id}",
        "url": f"https://example.com/{item_id}",
        "source": "github",
        "normalized_score": 90.0,
    }
    base.update(kwargs)
    return base


class TestFormatDigest:
    def test_renders_without_summaries_when_none(self):
        text = format_digest([_item(1)])
        assert "Item 1" in text
        assert "example.com/1" in text
        # No summary line
        assert "\U0001F4A1" not in text  # 💡

    def test_renders_without_summaries_when_empty_dict(self):
        text = format_digest([_item(1)], summaries={})
        assert "\U0001F4A1" not in text

    def test_renders_summary_line_when_present(self):
        text = format_digest(
            [_item(1)],
            summaries={1: "A crisp one-line summary of Item 1."},
        )
        assert "\U0001F4A1" in text  # 💡
        assert "A crisp one-line summary of Item 1." in text
        assert "<i>A crisp one-line summary of Item 1.</i>" in text

    def test_truncates_summary_at_140_chars(self):
        long = "x" * 500
        text = format_digest([_item(1)], summaries={1: long})
        # 140 chars of x plus an ellipsis
        assert "x" * 140 + "\u2026" in text
        assert "x" * 141 not in text

    def test_html_escapes_summary(self):
        text = format_digest(
            [_item(1)],
            summaries={1: "<script>alert(1)</script> & co"},
        )
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
        assert "&amp; co" in text
        # Raw angle brackets must not appear inside the italic body
        assert "<script>" not in text

    def test_skips_summary_for_items_without_entry(self):
        text = format_digest(
            [_item(1), _item(2)],
            summaries={1: "Only item 1 has a summary."},
        )
        assert "Only item 1 has a summary." in text
        # Item 2 renders normally with no summary line
        item2_section = text.split("2. ")[1]
        assert "\U0001F4A1" not in item2_section
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatters.py::TestFormatDigest -v`
Expected: FAIL — `format_digest` does not accept `summaries=` kwarg.

- [ ] **Step 3: Extend `format_digest` in `interfaces/telegram/formatters.py`**

Replace the current `format_digest` (lines 28–52) with:

```python
def format_digest(
    items: list[dict],
    title: str = "Trending",
    summaries: dict[int, str] | None = None,
) -> str:
    """Format a list of items as a digest message.

    Each item renders as a clickable title on line 1 and a source/score footer
    on line 2; the raw URL is also exposed so it can be copied for verification.
    If a summary is available for an item (via the filter analysis), it is
    appended on a third italic line.
    """
    if not items:
        return "No trending items found."

    summaries = summaries or {}

    lines = [f"\U0001F525 <b>{_escape_html(title)}</b>", f"{len(items)} items", ""]
    for i, item in enumerate(items[:15], 1):
        source = item.get("source", "unknown")
        icon = SOURCE_ICONS.get(source, "\u2022")
        item_title = item.get("title", "Untitled")[:80]
        url = item.get("url", "")
        score = item.get("normalized_score", 0)
        if url:
            safe_url = _escape_html(url)
            lines.append(f"{i}. {icon} <a href=\"{safe_url}\">{_escape_html(item_title)}</a>")
            lines.append(f"   <i>{source}</i> \u00b7 score {score:.0f} \u00b7 {safe_url}")
        else:
            lines.append(f"{i}. {icon} {_escape_html(item_title)}")
            lines.append(f"   <i>{source}</i> \u00b7 score {score:.0f}")

        summary = summaries.get(item.get("id"))
        if summary:
            truncated = _truncate(summary, 140)
            lines.append(f"   \U0001F4A1 <i>{_escape_html(truncated)}</i>")

    return "\n".join(lines)


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\u2026"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_formatters.py::TestFormatDigest -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run existing test suite for regressions**

Run: `pytest tests/test_digest_pusher.py tests/test_telegram_bot.py -v`
Expected: PASS. The new `summaries` kwarg is optional and defaults to `None`; existing callers that pass only `(items, title=…)` are unaffected.

- [ ] **Step 6: Commit**

```bash
git add interfaces/telegram/formatters.py tests/test_formatters.py
git commit -m "feat(telegram): inline filter summaries in digest"
```

---

## Task 2: Formatter — deep-dives follow-up

**Files:**
- Modify: `interfaces/telegram/formatters.py` (add `format_deep_dives_followup`)
- Modify: `tests/test_formatters.py` (add `TestFormatDeepDivesFollowup`)

The follow-up takes `items` (same list passed to `format_digest` so digest indexes match `#N`) and a map `deep_dives: dict[int, dict]` of already-parsed analysis content.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_formatters.py`:

```python
class TestFormatDeepDivesFollowup:
    def _dd(self, **overrides) -> dict:
        base = {
            "what_it_is": "A new AI memory system.",
            "why_trending": "Beats MemGPT on LoCoMo.",
            "pain_point": "LLMs forget context across sessions.",
            "app_idea": "Drop-in Python SDK for memory layers.",
            "competitors": ["MemGPT", "Letta", "Zep"],
            "gap_analysis": "should be omitted",
            "feasibility": {"effort": "2 weeks"},  # should be omitted
        }
        base.update(overrides)
        return base

    def test_returns_none_when_empty(self):
        assert format_deep_dives_followup([_item(1)], {}) is None

    def test_returns_none_when_no_items_have_deep_dive(self):
        assert format_deep_dives_followup([_item(1), _item(2)], {}) is None

    def test_renders_block_with_digest_index(self):
        text = format_deep_dives_followup(
            [_item(1), _item(2, title="Qwen")],
            {2: self._dd()},
        )
        assert text is not None
        assert "Deep Dives" in text
        assert "1 of 2" in text
        assert "#2" in text
        assert "Qwen" in text
        assert "<b>What:</b>" in text
        assert "A new AI memory system." in text
        assert "<b>Why trending:</b>" in text
        assert "<b>Pain:</b>" in text
        assert "<b>Idea:</b>" in text
        assert "<b>Competitors:</b> MemGPT, Letta, Zep" in text

    def test_orders_by_digest_position(self):
        text = format_deep_dives_followup(
            [_item(1, title="First"), _item(2, title="Second"), _item(3, title="Third")],
            {3: self._dd(what_it_is="C"), 1: self._dd(what_it_is="A")},
        )
        # Item 1 block appears before Item 3 block
        assert text.index("#1") < text.index("#3")
        # Item 2 is not rendered
        assert "#2" not in text

    def test_truncates_fields_at_200_chars(self):
        long = "y" * 500
        text = format_deep_dives_followup(
            [_item(1)], {1: self._dd(what_it_is=long)},
        )
        assert "y" * 200 + "\u2026" in text
        assert "y" * 201 not in text

    def test_skips_missing_or_na_fields(self):
        text = format_deep_dives_followup(
            [_item(1)],
            {1: {
                "what_it_is": "Present.",
                "why_trending": "",
                "pain_point": "N/A",
                "app_idea": "n/a",
                "competitors": [],
            }},
        )
        assert "<b>What:</b> Present." in text
        assert "<b>Why trending:</b>" not in text
        assert "<b>Pain:</b>" not in text
        assert "<b>Idea:</b>" not in text
        assert "<b>Competitors:</b>" not in text

    def test_limits_to_five_competitors(self):
        text = format_deep_dives_followup(
            [_item(1)],
            {1: self._dd(competitors=["A", "B", "C", "D", "E", "F", "G"])},
        )
        assert "<b>Competitors:</b> A, B, C, D, E" in text
        assert "F" not in text.split("<b>Competitors:</b>")[1]

    def test_omits_gap_analysis_and_feasibility(self):
        text = format_deep_dives_followup([_item(1)], {1: self._dd()})
        assert "should be omitted" not in text
        assert "feasibility" not in text.lower()
        assert "2 weeks" not in text

    def test_skips_block_when_all_renderable_fields_empty(self):
        text = format_deep_dives_followup(
            [_item(1)],
            {1: {"what_it_is": "", "why_trending": "", "pain_point": "",
                 "app_idea": "", "competitors": []}},
        )
        assert text is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatters.py::TestFormatDeepDivesFollowup -v`
Expected: FAIL — `format_deep_dives_followup` is not defined.

- [ ] **Step 3: Implement `format_deep_dives_followup`**

Append to `interfaces/telegram/formatters.py`:

```python
def format_deep_dives_followup(
    items: list[dict],
    deep_dives: dict[int, dict],
) -> str | None:
    """Compact combined message for items that have a deep_dive analysis.

    `items` is the enumerated digest list (same order). `#N` in each block
    matches the 1-based position in the digest so the user can cross-reference.
    Returns None when no item in the digest has a deep-dive (so the caller can
    skip the follow-up send entirely).
    """
    blocks: list[str] = []
    for i, item in enumerate(items[:15], 1):
        dd = deep_dives.get(item.get("id"))
        if not dd:
            continue
        block = _format_deep_dive_block(i, item, dd)
        if block:
            blocks.append(block)

    if not blocks:
        return None

    header = [
        "\U0001F52C <b>Deep Dives</b>",
        f"<i>{len(blocks)} of {len(items)} items have detailed analysis.</i>",
        "",
    ]
    return "\n".join(header + blocks)


def _format_deep_dive_block(index: int, item: dict, dd: dict) -> str | None:
    title = _escape_html(str(item.get("title", "Untitled"))[:80])
    source = item.get("source", "unknown")
    score = item.get("normalized_score", 0)

    field_lines: list[tuple[str, str]] = []
    for label, key in (
        ("What", "what_it_is"),
        ("Why trending", "why_trending"),
        ("Pain", "pain_point"),
        ("Idea", "app_idea"),
    ):
        value = _clean_field(dd.get(key))
        if value:
            field_lines.append((label, _truncate(value, 200)))

    competitors = [str(c).strip() for c in (dd.get("competitors") or []) if str(c).strip()]
    competitors = competitors[:5]

    if not field_lines and not competitors:
        return None

    lines = [f"\U0001F52C <b>#{index} \u00b7 {title}</b> <i>({source} \u00b7 score {score:.0f})</i>"]
    for label, value in field_lines:
        lines.append(f"<b>{label}:</b> {_escape_html(value)}")
    if competitors:
        lines.append(
            f"<b>Competitors:</b> {_escape_html(', '.join(competitors))}"
        )
    lines.append("")  # trailing blank line between blocks
    return "\n".join(lines)


def _clean_field(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "n/a", "none", "null"}:
        return ""
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_formatters.py -v`
Expected: PASS (all tests from Task 1 and Task 2).

- [ ] **Step 5: Commit**

```bash
git add interfaces/telegram/formatters.py tests/test_formatters.py
git commit -m "feat(telegram): add combined deep-dives follow-up formatter"
```

---

## Task 3: `DigestPusher` — fetch analyses and send follow-up

**Files:**
- Modify: `agents/notifiers/digest_pusher.py`
- Modify: `tests/test_digest_pusher.py`

`_select_items` stays as the single source of truth for which 15 items are in the digest. After it returns, `execute()` fetches two analysis maps keyed by `item_id`.

Key invariant for tests: the existing tests call `send.call_args[0][2]` (third positional arg of `_send`), i.e. `_send(bot_token, chat_id, text)`. Keep that signature. `execute()` just calls it twice when there's a follow-up.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_digest_pusher.py`:

```python
def _deep_dive_analysis(db: Database, item_id: int, content: dict) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO item_analysis (item_id, analysis_type, created_at, content, prompt_version) "
            "VALUES (?, 'deep_dive', datetime('now'), ?, 'v1')",
            (item_id, json.dumps(content)),
        )
        conn.commit()


def _set_filter_content(db: Database, item_id: int, content: dict) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE item_analysis SET content=? "
            "WHERE item_id=? AND analysis_type='filter'",
            (json.dumps(content), item_id),
        )
        conn.commit()


class TestDigestDetails:
    def test_digest_includes_filter_summary(self, ctx, db, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
        item_id = upsert_item(db, url="https://example.com/s", title="S",
                              source="github", normalized_score=90.0)
        _filter_analysis(db, item_id)
        _set_filter_content(db, item_id, {"summary": "A memorable one-liner."})

        with patch.object(DigestPusher, "_send") as send:
            DigestPusher().execute(ctx)

        # Only the digest is sent (no deep-dive yet)
        assert send.call_count == 1
        digest_text = send.call_args_list[0][0][2]
        assert "A memorable one-liner." in digest_text

    def test_no_followup_when_no_deep_dive(self, ctx, db, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
        item_id = upsert_item(db, url="https://example.com/n", title="N",
                              source="github", normalized_score=90.0)
        _filter_analysis(db, item_id)

        with patch.object(DigestPusher, "_send") as send:
            DigestPusher().execute(ctx)

        assert send.call_count == 1

    def test_sends_followup_when_deep_dive_present(self, ctx, db, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
        item_id = upsert_item(db, url="https://example.com/d", title="DeepItem",
                              source="github", normalized_score=95.0)
        _filter_analysis(db, item_id)
        _set_filter_content(db, item_id, {"summary": "Short summary"})
        _deep_dive_analysis(db, item_id, {
            "what_it_is": "A novel thing.",
            "why_trending": "People love it.",
            "pain_point": "Real pain.",
            "app_idea": "Build this.",
            "competitors": ["A", "B"],
        })

        with patch.object(DigestPusher, "_send") as send:
            DigestPusher().execute(ctx)

        assert send.call_count == 2
        digest_text = send.call_args_list[0][0][2]
        followup_text = send.call_args_list[1][0][2]
        assert "Short summary" in digest_text
        assert "Deep Dives" in followup_text
        assert "#1" in followup_text
        assert "DeepItem" in followup_text
        assert "A novel thing." in followup_text

    def test_followup_handles_duplicate_analysis_rows(self, ctx, db, monkeypatch):
        """If two deep_dive rows exist for the same item, use the newer one."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
        item_id = upsert_item(db, url="https://example.com/dup", title="Dup",
                              source="github", normalized_score=95.0)
        _filter_analysis(db, item_id)
        # Older row
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO item_analysis (item_id, analysis_type, created_at, content, prompt_version) "
                "VALUES (?, 'deep_dive', datetime('now', '-1 hour'), ?, 'v1')",
                (item_id, json.dumps({"what_it_is": "OLD VERSION"})),
            )
            conn.commit()
        # Newer row
        _deep_dive_analysis(db, item_id, {"what_it_is": "NEW VERSION"})

        with patch.object(DigestPusher, "_send") as send:
            DigestPusher().execute(ctx)

        followup_text = send.call_args_list[1][0][2]
        assert "NEW VERSION" in followup_text
        assert "OLD VERSION" not in followup_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_digest_pusher.py::TestDigestDetails -v`
Expected: FAIL — digest text does not yet include summaries; no follow-up is sent.

- [ ] **Step 3: Add analysis fetch + dual send in `execute()`**

Replace `agents/notifiers/digest_pusher.py` `execute()` (lines 24–50) and add a helper `_load_analyses`:

```python
def execute(self, ctx: AgentContext) -> AgentResult:
    delivery_cfg = ctx.config.get("delivery", {}).get("telegram", {})
    if not delivery_cfg.get("enabled", False):
        return AgentResult(success=True, message="Telegram delivery disabled")

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return AgentResult(
            success=False,
            message="TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set",
        )

    limit = ctx.config.get("scoring", {}).get("digest_size", 15)
    items = self._select_items(ctx, limit=limit)
    if not items:
        return AgentResult(success=True, message="No new tracked items to send")

    summaries, deep_dives = self._load_analyses(ctx, [item["id"] for item in items])

    digest_text = format_digest(items, title="Trending", summaries=summaries)
    self._send(bot_token, chat_id, digest_text)

    followup = format_deep_dives_followup(items, deep_dives)
    if followup:
        self._send(bot_token, chat_id, followup)

    self._record_digest(ctx, items)

    return AgentResult(
        success=True,
        message=(
            f"Sent digest with {len(items)} items"
            + (f" + deep-dive follow-up ({sum(1 for i in items if i['id'] in deep_dives)} items)"
               if followup else "")
        ),
        data={"count": len(items), "deep_dives": bool(followup)},
    )


def _load_analyses(
    self, ctx: AgentContext, item_ids: list[int],
) -> tuple[dict[int, str], dict[int, dict]]:
    """Return (summaries, deep_dives) keyed by item_id.

    summaries[item_id] -> the filter row's `summary` field (str).
    deep_dives[item_id] -> the parsed deep_dive content (dict).
    For duplicate rows of the same (item_id, type) the most recent wins.
    """
    if not item_ids:
        return {}, {}

    placeholders = ",".join("?" * len(item_ids))
    summaries: dict[int, str] = {}
    deep_dives: dict[int, dict] = {}
    with ctx.db.connect() as conn:
        rows = conn.execute(
            f"SELECT item_id, analysis_type, content FROM item_analysis "
            f"WHERE analysis_type IN ('filter', 'deep_dive') "
            f"  AND item_id IN ({placeholders}) "
            f"ORDER BY created_at DESC",
            item_ids,
        ).fetchall()

    for row in rows:
        item_id = row["item_id"]
        try:
            payload = json.loads(row["content"]) if row["content"] else {}
        except (ValueError, TypeError):
            logger.debug("Malformed %s analysis for item %s", row["analysis_type"], item_id)
            continue
        if row["analysis_type"] == "filter":
            if item_id in summaries:
                continue  # already took the newer one
            summary = payload.get("summary") if isinstance(payload, dict) else None
            if isinstance(summary, str) and summary.strip():
                summaries[item_id] = summary.strip()
        elif row["analysis_type"] == "deep_dive":
            if item_id in deep_dives:
                continue
            if isinstance(payload, dict):
                deep_dives[item_id] = payload

    return summaries, deep_dives
```

Update the imports at the top of the file:

```python
from interfaces.telegram.formatters import format_digest, format_deep_dives_followup
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `pytest tests/test_digest_pusher.py::TestDigestDetails -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the rest of the digest_pusher tests for regressions**

Run: `pytest tests/test_digest_pusher.py -v`
Expected: PASS. The existing tests call `_send` with positional args `(bot_token, chat_id, text)` which remains the signature.

- [ ] **Step 6: Run full test suite**

Run: `pytest -q`
Expected: PASS. (Nothing else imports `format_digest` with a `summaries` kwarg, and the formatter stays backward-compatible.)

- [ ] **Step 7: Commit**

```bash
git add agents/notifiers/digest_pusher.py tests/test_digest_pusher.py
git commit -m "feat(notifiers): digest pushes filter summaries + deep-dive follow-up"
```

---

## Self-Review

**1. Spec coverage**

| Spec section                            | Task |
|-----------------------------------------|------|
| Two-message architecture                | T3   |
| Data fetch (dual `item_analysis` query) | T3   |
| Digest inline summary line              | T1   |
| 140-char summary truncation + escape    | T1   |
| Deep-dive follow-up header + blocks     | T2   |
| `#N` matches digest index               | T2   |
| 200-char field caps                     | T2   |
| Skip missing / `N/A` fields             | T2   |
| 5-competitor cap                        | T2   |
| Omit `gap_analysis` / `feasibility`     | T2   |
| Skip follow-up when N=0                 | T2 (returns `None`) + T3 (conditional send) |
| Duplicate-row handling (newest wins)    | T3   |
| No schema / config / schedule changes   | — (by omission) |
| Tests: unit formatter + integration     | T1, T2, T3 |

All spec bullets map to a task. No gaps.

**2. Placeholder scan**

No TBDs, TODOs, or "implement later" phrasing. Each step has the full code it expects to land.

**3. Type consistency**

- `format_digest(items, title=..., summaries: dict[int, str] | None = None)` — used in T1 tests, T3 execute(). Consistent.
- `format_deep_dives_followup(items, deep_dives: dict[int, dict]) -> str | None` — used in T2 tests, T3 execute(). Consistent.
- `_load_analyses` returns `tuple[dict[int, str], dict[int, dict]]`. Consumed as `summaries, deep_dives = ...`. Consistent.
- `_truncate` / `_clean_field` are internal helpers declared in T1 and T2 respectively; no cross-task rename risk.
- `send.call_args[0][2]` access pattern in existing tests matches the preserved `_send(bot_token, chat_id, text)` signature.
