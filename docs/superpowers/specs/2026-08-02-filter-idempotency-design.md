# Filter agent idempotency — design

**Date:** 2026-08-02
**Component:** `agents/analysts/filter.py`, `db/queries.py`

## Problem

The relevance filter re-sends the same items to the Claude CLI indefinitely. In
production on 2026-08-02:

| Measure | Value |
| --- | --- |
| Filter analysis rows | 29,983 |
| Distinct items covered | 3,187 |
| Redundancy | ~9.4x |
| Most re-analyzed item (id 9483, last seen 2026-05-14) | 1,191 analyses |
| Of today's 173 rows | 44 fresh / 129 stale |

Two independent defects compound:

**No recency bound on selection.** `filter.py:21` selects the global top 30 by
`normalized_score` with no time bound. The scorer only rescores items seen in the
last 48h (`agents/analysts/scorer.py:28`), so an older item's `normalized_score`
is *frozen*, not decayed — it can never fall out of the top 30 on its own.

**No idempotency on write.** `filter.py:50` unconditionally INSERTs a new
`item_analysis` row. There is no "already filtered" check, unlike
`_enqueue_deep_dives` (`filter.py:103`) which does guard against re-work.

The agent is `on_demand`, re-enqueued after every scout via `scores_updated`
(`main.py:138-145`), so it fires many times a day. Each call takes ~100s, which
is why the filter agent is almost always busy.

### Secondary symptom: digest spam

`digest_pusher._select_items` admits items whose filter row is newer than the last
digest (`agents/notifiers/digest_pusher.py:140`). Every re-filter mints a fresh
`created_at`, so item 9483 has been eligible for the Telegram digest ~1,191 times.
Fixing the write path fixes this as a side effect.

### Capacity is mis-targeted, not exhausted

464 items seen in the last 48h have no filter verdict at all. The filter is not
over capacity — roughly 75% of its calls go to months-old content. Reclaiming that
should let it cover the fresh inflow.

## Decisions

**Each item is filtered exactly once, ever.** The filter's output (`novel`,
`ai_relevant`, `category`, `interest_score`, `summary`) is a judgment about
content, and content does not change. Only momentum changes, and that is the
scorer's job.

**Candidate selection is bounded to 48h on `last_seen`,** matching the scorer's
window. The two agents then operate on an identical working set, so anything the
filter sees has a live `normalized_score`. This costs almost nothing: 3,175 of
3,187 items ever filtered (99.6%) were first filtered within 48h of `last_seen`.

It also avoids a pointless backlog drain. 19,636 items have never been filtered,
16,039 of them older than 30 days. Without the gate, "filter once ever" would
queue ~650 LLM batches (~18h of continuous calls) on content nobody will read.
The pre-48h backlog stays permanently unfiltered by design.

**On LLM failure, write nothing.** The current fallback (`filter.py:31-34`)
fabricates a verdict — `novel=True, ai_relevant=True, interest_score=5,
summary=title`. That is harmless today only because the next run overwrites it.
Under filter-once it becomes permanent: one transient Claude CLI failure would
burn 30 items with junk. Since the agent is re-enqueued after every scout, a
transient failure self-heals within minutes if we simply do nothing.

**Exclusion happens at selection time, not before the INSERT.** This is what
avoids the ~100s LLM call rather than just the write.

## Design

### 1. `db/queries.py` — new `get_unfiltered_items()`

`get_items()` cannot express "has no filter analysis", and adding a flag would
muddy a general-purpose helper. A purpose-built query follows the precedent set
by `get_items_with_filter()`.

```sql
SELECT i.* FROM items i
WHERE i.last_seen >= ?
  AND NOT EXISTS (SELECT 1 FROM item_analysis ia
                  WHERE ia.item_id = i.id AND ia.analysis_type = 'filter')
ORDER BY i.normalized_score DESC
LIMIT ?
```

Signature: `get_unfiltered_items(db, since: str, limit: int) -> list[dict]`.

The docstring must record why both bounds exist, since neither is obvious and
removing either silently restores the bug.

The existing `idx_item_analysis_item_id` covers the correlated subquery. No new
index.

### 2. `agents/analysts/filter.py`

- Line 21 calls `get_unfiltered_items()` with `since = now - 48h`, reusing
  `scoring.freshness_half_life_hours`' sibling constant pattern — the window is a
  module-level constant, not config, until there is a reason to tune it.
- An empty result returns early in the same shape as the existing
  `"No items to filter"` path. This becomes the common case once the backlog
  drains, so it must be cheap and must not log at warning level.
- Lines 28–34: remove the fabricated-verdict fallback. On exception, log the
  error and return `AgentResult(success=False, message=...)`.
- Everything downstream of the INSERT (topic assignment, status promotion,
  `_enqueue_deep_dives`) is unchanged.

### 3. `scripts/dedupe_filter_analyses.py`

One-off cleanup keeping only the newest filter row per item (~26,796 deletions),
then `VACUUM`.

Safe for every reader: `get_items_with_filter` and `digest_pusher._select_items`
both resolve `MAX(created_at)` per item, and keeping the newest row preserves that
value exactly.

Dry-run by default; `--apply` to commit. Run by hand on prod after deploy — not
wired into startup, so a bulk destructive delete never happens implicitly.

### 4. Downstream readers — verified, no changes

- `get_items_with_filter` (`db/queries.py`) — one row per item makes the
  `MAX(created_at)` self-join degenerate but still correct.
- `digest_pusher._select_items` — each item now qualifies for a digest exactly
  once instead of once per re-filter. A visible behavior change to Telegram, and
  the intended one. Its `interest_score DESC` ordering is deliberately left alone.
- `deep_diver.py:51` — reads one filter row by item id; unaffected.

## Testing

Test-first, using the existing `TestRelevanceFilter` fixtures in
`tests/test_analysts.py`.

**`tests/test_queries.py`** — `get_unfiltered_items()`:
- excludes items older than `since`
- excludes items that already have a `filter` analysis
- includes items with a non-`filter` analysis (e.g. `deep_dive` only)
- orders by `normalized_score DESC` and respects `limit`

**`tests/test_analysts.py`** — the agent:
- a stale item with a high frozen `normalized_score` is not selected
- an already-filtered item is not selected, and the LLM is not called
- a fresh unfiltered item is still selected and stored
- nothing to filter → early return, LLM not called, zero rows written
- LLM failure → zero rows written, `success=False`

`test_filter_fallback_on_llm_failure` (`tests/test_analysts.py:364`) currently
asserts the fallback *writes* rows; it inverts.

## Out of scope

- The 206 existing rows where `summary == title` (the LLM-fallback fingerprint).
  The heuristic is inexact — a genuine summary could equal the title.
- `digest_pusher`'s `interest_score DESC, normalized_score DESC` ordering.
- The 19.2k pre-48h unfiltered backlog.
