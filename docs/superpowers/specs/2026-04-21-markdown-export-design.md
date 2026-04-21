# Markdown Export — Design

**Date:** 2026-04-21
**Status:** Approved

## Purpose

Let the user export trending items from the dashboard as Markdown — either a single item or all items currently visible on the dashboard. Output is saved to disk via a normal browser download so the user can paste it into Obsidian, a doc, or anywhere else.

## Scope

- Per-item export, available from each dashboard card and the item detail page.
- Bulk export of items currently visible on the dashboard (respects the client-side search filter).
- Full content per item: title, source/score/rank metadata, summary, description, every analysis row, score history.
- Single combined `.md` file for bulk (no zip).

## Out of scope

- Date-range or category-filter UI for bulk export — uses the visible set only.
- Other export formats (HTML, PDF, JSON).
- Persistent export history or sharing.
- Server-side file storage.

## Architecture

A new module `interfaces/web/export.py` exposes two pure functions:

- `render_item_markdown(item: dict, analyses: list[dict], scores: list[dict]) -> str`
- `render_bulk_markdown(items_with_data: list[tuple[dict, list[dict], list[dict]]]) -> str`

Two new routes in `interfaces/web/app.py` call those functions. Routes pull data using the same `get_item_by_id` and `get_score_history` queries the existing item-detail page already uses, plus the existing inline `item_analysis` query — no new DB code.

Why this split: the formatter is pure and easy to unit-test; the routes only handle HTTP concerns (status codes, headers, ID validation).

## API

### GET /api/items/{item_id}/export.md

Returns one item as Markdown.

- `200 text/markdown; charset=utf-8`
  - Header: `Content-Disposition: attachment; filename="item-{id}-{slug}.md"`
- `404` if the item does not exist.

Filename slug rules:
- Lowercase the title, replace any run of non-alphanumeric chars with `-`, strip leading/trailing `-`, truncate to 50 chars.
- If the slug is empty after slugifying, the filename is `item-{id}.md`.

### POST /api/items/export.md

Returns a combined Markdown document for the requested items.

- Request body: `{"ids": [1, 17, 42, ...]}`
- `200 text/markdown; charset=utf-8`
  - Header: `Content-Disposition: attachment; filename="trendbot-export-{YYYY-MM-DD}.md"`
- `400` if `ids` is missing, empty, not a list of integers, or contains more than 100 ids.
- Items not found in the DB are silently skipped (don't fail the whole export because one row was deleted between page load and click). If every id is missing, still return `200` with just the header section and a "(no items)" note — the request itself was valid.

## Markdown format

### Per-item template

```markdown
# {title}

**Source:** {source} · **Score:** {interest_score}/10 · **Rank:** {normalized_score}
**First seen:** {first_seen} · **Times seen:** {times_seen}
**URL:** {url}

{category badge if set}

## Summary
{llm_summary}

## Description
{description}

## Analysis — {analysis_type}
{key}: {value}
...
(repeated per analysis row, newest first; lists joined with ", ";
nested dicts pretty-printed as sub-bullets)

## Score history
- {recorded_at} — momentum {x.xx} · normalized {x}
...

---
*Exported from TrendBot on {YYYY-MM-DD HH:MM UTC}*
```

Empty or missing fields are skipped, not rendered as `None`. If there are no analyses, the `## Analysis` section is omitted entirely. Same for `## Score history`.

### Bulk template

A header block:

```markdown
# TrendBot export — {YYYY-MM-DD}

**{N} items** across {M} sources, exported on {YYYY-MM-DD HH:MM UTC}

---
```

Then items grouped by `category` (sorted by max `interest_score` per category, items sorted by `interest_score` desc within each group). Each item is rendered with the per-item template, **demoted one heading level** (`#` → `##`, `##` → `###`) so the document has a single H1.

## UI changes

### Dashboard cards (`interfaces/web/templates/index.html`)

- Add `data-item-id="{{ item.id }}"` to each `.card` div so the bulk-export JS can collect IDs from currently-visible cards.
- Add a small ⬇ icon-button to each card's right-hand column (next to the score). Plain anchor styled as a button: `<a href="/api/items/{{ item.id }}/export.md" class="btn btn-secondary" title="Export to Markdown">⬇</a>`. No JS — the browser handles the download from the `Content-Disposition` header.

### Dashboard top bar

- Above the existing search box, add an **"Export visible (N)"** button.
- JS:
  - On page load and on every search-input event: count the currently-visible `.card` elements (the existing search toggles `card.style.display`, so `card.style.display !== 'none'` is the visibility check) and update the button label.
  - On click: collect `data-item-id` values from visible cards, `POST` to `/api/items/export.md` with `{"ids": [...]}`, then trigger a download by reading the response as a `Blob`, creating a temporary `<a download="trendbot-export-YYYY-MM-DD.md">`, clicking it, and revoking the URL.
  - Disabled when 0 items are visible.

### Item detail page (`interfaces/web/templates/item.html`)

- Add an "Export to Markdown ⬇" button next to the existing "← Back" button. Same plain anchor to the GET endpoint.

### Styling

Reuse the existing `.btn` / `.btn-secondary` classes already in `base.html`. No new CSS.

## Data flow

```
Per-item:
  Browser → GET /api/items/{id}/export.md
            → app.py: get_item_by_id + analyses query + get_score_history
            → export.py: render_item_markdown
            → text/markdown response with Content-Disposition

Bulk:
  Browser collects visible IDs → POST /api/items/export.md {ids: [...]}
            → app.py: validate ids, fetch each item + analyses + scores
            → export.py: render_bulk_markdown
            → text/markdown response with Content-Disposition
            → JS Blob download
```

## Error handling

- Missing item on `GET`: `404` with FastAPI's standard `HTTPException` (matches the existing `/api/items/{id}` pattern).
- Invalid `POST` body: `400` with a clear message — `"ids must be a non-empty list of integers (max 100)"`.
- Missing items inside a bulk request: silently skipped, never `404`. The user clicked one button; one missing row should not fail the whole export.
- Errors in the markdown formatter itself (e.g., malformed JSON in `analysis.content`) bubble up as `500` — these would represent a corrupted DB row and warrant investigation, not a silent skip.

## Testing

Add `tests/test_export.py`:

**Formatter unit tests:**
- `render_item_markdown` with full data (analyses + scores) → asserts H1, summary, analysis section, score history all present.
- `render_item_markdown` with minimal data (no analyses, no scores, no summary) → no empty headings, no literal `None`, no broken sections.
- `render_bulk_markdown` with mixed-category items → asserts single H1, group headings, items sorted by score desc within each group, heading demotion is correct (per-item `#` becomes `##`).
- `render_bulk_markdown` with empty input → still produces a valid header section with `(no items)` note.

**Endpoint tests via `fastapi.testclient.TestClient`:**
- `GET /api/items/{id}/export.md` → `200`, `Content-Type: text/markdown; charset=utf-8`, `Content-Disposition: attachment` with expected filename, body starts with `# `.
- `GET` on a missing id → `404`.
- `POST /api/items/export.md` with valid ids → `200`, combined body contains all items.
- `POST` with empty / missing / non-integer / >100 ids → `400`.
- `POST` with a mix of valid and missing ids → `200`, missing ones silently skipped.

No JS tests — the existing dashboard JS isn't tested either, and that's out of scope.

## Files touched

**New:**
- `interfaces/web/export.py` — markdown formatter
- `tests/test_export.py` — unit + endpoint tests

**Modified:**
- `interfaces/web/app.py` — two new routes
- `interfaces/web/templates/index.html` — per-card export icon, top-bar export-visible button, JS for bulk download
- `interfaces/web/templates/item.html` — export button beside "Back"
