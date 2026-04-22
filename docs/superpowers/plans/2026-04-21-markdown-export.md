# Markdown Export — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user export trending items from the dashboard as Markdown — single item or bulk — via browser download.

**Architecture:** Pure formatter module (`interfaces/web/export.py`) used by two new FastAPI routes (`GET /api/items/{id}/export.md`, `POST /api/items/export.md`). Dashboard JS scrapes visible card IDs for bulk export and triggers a `Blob` download. Per-item exports are plain `<a>` tags pointing at the GET endpoint.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, SQLite, vanilla JS, pytest + `fastapi.testclient.TestClient`.

**Spec:** `docs/superpowers/specs/2026-04-21-markdown-export-design.md`

---

## File Structure

**New files:**
- `interfaces/web/export.py` — markdown formatter (`render_item_markdown`, `render_bulk_markdown`, `slugify`)
- `tests/test_export.py` — unit tests for the formatter, endpoint tests via TestClient

**Modified files:**
- `interfaces/web/app.py` — two new routes calling into `export.py`
- `interfaces/web/templates/index.html` — `data-item-id` attr on cards, ⬇ icon on each card, "Export visible (N)" button + JS at the top
- `interfaces/web/templates/item.html` — "Export to Markdown ⬇" button next to "← Back"

The formatter and routes are split deliberately: the formatter is pure (`dict → str`) and trivially unit-testable; the routes own HTTP concerns (status codes, headers, ID validation) and DB access.

---

## Task 1: Slugify helper + module scaffolding

**Files:**
- Create: `interfaces/web/export.py`
- Create: `tests/test_export.py`

- [ ] **Step 1: Write failing tests for slugify**

Create `tests/test_export.py`:

```python
import pytest

from interfaces.web.export import slugify


class TestSlugify:
    def test_basic_lowercase(self):
        assert slugify("Hello World") == "hello-world"

    def test_collapses_non_alphanumeric_runs(self):
        assert slugify("Foo!!! Bar??? Baz") == "foo-bar-baz"

    def test_strips_leading_trailing_dashes(self):
        assert slugify("---weird---title---") == "weird-title"

    def test_truncates_to_50_chars(self):
        long = "a" * 80
        result = slugify(long)
        assert len(result) <= 50

    def test_truncate_does_not_leave_trailing_dash(self):
        # 49 a's + space + bbbbb → naive slice gives 'a'*49 + '-' (trailing dash)
        result = slugify(("a" * 49) + " bbbbb")
        assert not result.endswith("-")

    def test_empty_input_returns_empty(self):
        assert slugify("") == ""

    def test_only_punctuation_returns_empty(self):
        assert slugify("!!!---???") == ""

    def test_unicode_treated_as_non_alphanumeric(self):
        # Keep it ASCII-only — unicode chars become dashes.
        assert slugify("café résumé") == "caf-r-sum"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_export.py -v`
Expected: ImportError / ModuleNotFoundError on `interfaces.web.export`.

- [ ] **Step 3: Implement `slugify` and module skeleton**

Create `interfaces/web/export.py`:

```python
"""Markdown export for dashboard items.

Pure formatter — no DB access, no HTTP. The web routes pass in dicts
already loaded from the DB and we return strings.
"""
from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 50) -> str:
    """Lowercase, collapse non-alphanumerics into single dashes, trim, truncate.

    Used for export filenames. Non-ASCII chars are treated as non-alphanumeric
    (no transliteration). Empty input returns empty string — callers should
    fall back to an id-based filename.
    """
    s = _NON_ALNUM.sub("-", text.lower()).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_export.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add interfaces/web/export.py tests/test_export.py
git commit -m "feat(export): slugify helper for export filenames"
```

---

## Task 2: Per-item markdown formatter

**Files:**
- Modify: `interfaces/web/export.py`
- Modify: `tests/test_export.py`

- [ ] **Step 1: Write failing tests for `render_item_markdown`**

Append to `tests/test_export.py`:

```python
from interfaces.web.export import render_item_markdown


def make_item(**overrides):
    """Default item dict matching the `items` table shape."""
    base = {
        "id": 42,
        "title": "Gemini 3 launch announcement",
        "url": "https://blog.google/technology/google-deepmind/gemini-3/",
        "source": "blog",
        "description": "A major next-generation frontier model release.",
        "first_seen": "2026-04-15T10:30:00+00:00",
        "last_seen":  "2026-04-21T14:00:00+00:00",
        "times_seen": 9,
        "momentum_score": 0.0,
        "normalized_score": 48.0,
    }
    base.update(overrides)
    return base


def make_filter_analysis(**content_overrides):
    content = {
        "novel": True, "ai_relevant": True,
        "interest_score": 9, "category": "model",
        "summary": "Gemini 3 launch — major frontier model release.",
    }
    content.update(content_overrides)
    return {
        "id": 1, "item_id": 42, "analysis_type": "filter",
        "created_at": "2026-04-21T14:01:00+00:00",
        "content": content,
    }


def make_deep_dive_analysis(**content_overrides):
    content = {
        "thesis": "Gemini 3 represents a step change in reasoning quality.",
        "key_findings": ["10x compute scaling", "Native multimodal training"],
        "competitors": ["GPT-5", "Claude Opus 4.7"],
    }
    content.update(content_overrides)
    return {
        "id": 2, "item_id": 42, "analysis_type": "deep_dive",
        "created_at": "2026-04-22T09:00:00+00:00",
        "content": content,
    }


def make_score(recorded_at, momentum, normalized):
    return {
        "id": 1, "item_id": 42,
        "recorded_at": recorded_at,
        "momentum_score": momentum,
        "normalized_score": normalized,
        "raw_metrics": {},
    }


class TestRenderItemMarkdown:
    def test_h1_is_title(self):
        md = render_item_markdown(make_item(), [], [])
        assert md.startswith("# Gemini 3 launch announcement\n")

    def test_includes_metadata(self):
        md = render_item_markdown(make_item(), [make_filter_analysis()], [])
        assert "**Source:** blog" in md
        assert "**Score:** 9/10" in md
        assert "**Rank:** 48" in md
        assert "**Times seen:** 9" in md
        assert "**First seen:** 2026-04-15" in md
        assert "**URL:** https://blog.google" in md

    def test_score_omitted_when_no_filter_analysis(self):
        md = render_item_markdown(make_item(), [], [])
        # No filter analysis means no interest_score — line should still render
        # source/rank/seen but skip the score field gracefully.
        assert "**Score:**" not in md
        assert "**Source:** blog" in md

    def test_includes_summary_section_from_filter(self):
        md = render_item_markdown(make_item(), [make_filter_analysis()], [])
        assert "## Summary" in md
        assert "Gemini 3 launch — major frontier model release." in md

    def test_summary_section_omitted_when_no_filter(self):
        md = render_item_markdown(make_item(), [], [])
        assert "## Summary" not in md

    def test_includes_description(self):
        md = render_item_markdown(make_item(), [], [])
        assert "## Description" in md
        assert "A major next-generation frontier model release." in md

    def test_description_section_omitted_when_blank(self):
        md = render_item_markdown(make_item(description=""), [], [])
        assert "## Description" not in md

    def test_includes_category_when_present(self):
        md = render_item_markdown(make_item(), [make_filter_analysis()], [])
        assert "**Category:** model" in md

    def test_renders_each_analysis(self):
        md = render_item_markdown(
            make_item(),
            [make_filter_analysis(), make_deep_dive_analysis()],
            [],
        )
        assert "## Analysis — deep_dive" in md
        assert "Thesis: Gemini 3 represents" in md
        # Lists rendered comma-joined
        assert "Key Findings: 10x compute scaling, Native multimodal training" in md
        assert "Competitors: GPT-5, Claude Opus 4.7" in md

    def test_filter_analysis_not_rendered_as_separate_section(self):
        # The filter analysis is consumed for summary/score/category — don't also
        # render it as a generic "## Analysis — filter" section.
        md = render_item_markdown(make_item(), [make_filter_analysis()], [])
        assert "## Analysis — filter" not in md

    def test_includes_score_history(self):
        scores = [
            make_score("2026-04-20T10:00:00+00:00", 0.5, 40.0),
            make_score("2026-04-21T10:00:00+00:00", 0.8, 48.0),
        ]
        md = render_item_markdown(make_item(), [], scores)
        assert "## Score history" in md
        assert "2026-04-20T10:00 — momentum 0.50 · normalized 40" in md
        assert "2026-04-21T10:00 — momentum 0.80 · normalized 48" in md

    def test_score_history_section_omitted_when_empty(self):
        md = render_item_markdown(make_item(), [], [])
        assert "## Score history" not in md

    def test_no_literal_none_in_output(self):
        item = make_item(description=None, last_seen=None)
        md = render_item_markdown(item, [], [])
        assert "None" not in md

    def test_minimal_item_renders_without_errors(self):
        item = {
            "id": 1, "title": "Minimal", "url": "https://x.example",
            "source": "blog", "description": "",
            "first_seen": "2026-04-21T10:00:00+00:00",
            "last_seen": "2026-04-21T10:00:00+00:00",
            "times_seen": 1,
            "momentum_score": 0.0, "normalized_score": 0.0,
        }
        md = render_item_markdown(item, [], [])
        assert md.startswith("# Minimal\n")
        assert "*Exported from TrendBot on" in md

    def test_footer_present(self):
        md = render_item_markdown(make_item(), [], [])
        assert "*Exported from TrendBot on" in md
        # Footer comes after a separator
        assert "\n---\n" in md

    def test_returns_string_with_trailing_newline(self):
        md = render_item_markdown(make_item(), [], [])
        assert isinstance(md, str)
        assert md.endswith("\n")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_export.py -v`
Expected: ImportError on `render_item_markdown`.

- [ ] **Step 3: Implement `render_item_markdown`**

Append to `interfaces/web/export.py`:

```python
from datetime import datetime, timezone
from typing import Any


def _stringify_value(value: Any) -> str:
    """Render an analysis-content value for inline display."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        # Pretty-print as inline sub-bullets so nested dicts stay readable.
        parts = [f"{k}: {_stringify_value(v)}" for k, v in value.items()]
        return "; ".join(parts)
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _format_field_label(key: str) -> str:
    """snake_case → Title Case for analysis content keys."""
    return key.replace("_", " ").title()


def _extract_filter_content(analyses: list[dict]) -> dict | None:
    """Return the most recent filter analysis content dict (already JSON-parsed)."""
    for a in analyses:
        if a.get("analysis_type") == "filter":
            return a.get("content") or {}
    return None


def _format_iso_date(iso: str | None, length: int = 10) -> str:
    """Trim an ISO timestamp to YYYY-MM-DD (length=10) or YYYY-MM-DDTHH:MM (length=16)."""
    if not iso:
        return ""
    return iso[:length]


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def render_item_markdown(
    item: dict,
    analyses: list[dict],
    scores: list[dict],
    heading_offset: int = 0,
) -> str:
    """Render one item as markdown.

    `heading_offset` shifts every heading down by N levels (used by bulk export
    so the per-item H1 becomes H2 under the document's top-level H1).
    """
    h1 = "#" * (1 + heading_offset)
    h2 = "#" * (2 + heading_offset)

    filter_content = _extract_filter_content(analyses) or {}
    interest_score = filter_content.get("interest_score")
    summary = filter_content.get("summary")
    category = filter_content.get("category")

    lines: list[str] = []

    # Heading
    lines.append(f"{h1} {item['title']}")
    lines.append("")

    # Metadata block
    meta_parts = [f"**Source:** {item['source']}"]
    if interest_score is not None:
        meta_parts.append(f"**Score:** {interest_score}/10")
    if item.get("normalized_score") is not None:
        meta_parts.append(f"**Rank:** {int(item['normalized_score'])}")
    lines.append(" · ".join(meta_parts))

    seen_parts = []
    if item.get("first_seen"):
        seen_parts.append(f"**First seen:** {_format_iso_date(item['first_seen'])}")
    if item.get("times_seen") is not None:
        seen_parts.append(f"**Times seen:** {item['times_seen']}")
    if seen_parts:
        lines.append(" · ".join(seen_parts))

    if item.get("url"):
        lines.append(f"**URL:** {item['url']}")
    if category:
        lines.append(f"**Category:** {category}")
    lines.append("")

    # Summary (from filter analysis)
    if summary:
        lines.append(f"{h2} Summary")
        lines.append(summary)
        lines.append("")

    # Description (raw item field)
    if item.get("description"):
        lines.append(f"{h2} Description")
        lines.append(item["description"])
        lines.append("")

    # Other analyses (skip filter — already consumed above)
    for a in analyses:
        if a.get("analysis_type") == "filter":
            continue
        atype = a.get("analysis_type", "analysis")
        content = a.get("content") or {}
        lines.append(f"{h2} Analysis — {atype}")
        for key, value in content.items():
            rendered = _stringify_value(value)
            if rendered == "":
                continue
            lines.append(f"{_format_field_label(key)}: {rendered}")
        lines.append("")

    # Score history
    if scores:
        lines.append(f"{h2} Score history")
        for s in scores:
            ts = _format_iso_date(s.get("recorded_at"), length=16)
            mom = s.get("momentum_score") or 0.0
            norm = s.get("normalized_score") or 0.0
            lines.append(f"- {ts} — momentum {mom:.2f} · normalized {int(norm)}")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Exported from TrendBot on {_now_utc_str()}*")
    lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_export.py -v`
Expected: all tests pass (slugify + new render tests).

- [ ] **Step 5: Commit**

```bash
git add interfaces/web/export.py tests/test_export.py
git commit -m "feat(export): per-item markdown formatter"
```

---

## Task 3: Bulk markdown formatter

**Files:**
- Modify: `interfaces/web/export.py`
- Modify: `tests/test_export.py`

- [ ] **Step 1: Write failing tests for `render_bulk_markdown`**

Append to `tests/test_export.py`:

```python
from interfaces.web.export import render_bulk_markdown


class TestRenderBulkMarkdown:
    def test_empty_input_still_valid(self):
        md = render_bulk_markdown([])
        assert md.startswith("# TrendBot export — ")
        assert "(no items)" in md

    def test_single_item(self):
        triple = (make_item(), [make_filter_analysis()], [])
        md = render_bulk_markdown([triple])
        assert md.startswith("# TrendBot export — ")
        assert "**1 items**" in md
        # Per-item H1 is demoted to H2
        assert "## Gemini 3 launch announcement" in md
        # Per-item H2 is demoted to H3
        assert "### Summary" in md

    def test_groups_by_category_sorted_by_max_score(self):
        # Two categories: "model" (max score 9), "tool" (max score 7).
        # Expected order: model section first, then tool.
        item_a = make_item(id=1, title="Model A")
        item_b = make_item(id=2, title="Tool B", url="https://x.example/b")
        triples = [
            (item_b, [make_filter_analysis(category="tool", interest_score=7)], []),
            (item_a, [make_filter_analysis(category="model", interest_score=9)], []),
        ]
        md = render_bulk_markdown(triples)
        model_idx = md.index("## model")
        tool_idx = md.index("## tool")
        assert model_idx < tool_idx
        # Items demoted further inside categories — H2 became H3 (offset=2)
        assert "### Model A" in md
        assert "### Tool B" in md

    def test_items_sorted_by_score_desc_within_category(self):
        item_hi = make_item(id=1, title="High Scorer")
        item_lo = make_item(id=2, title="Low Scorer", url="https://x.example/lo")
        triples = [
            (item_lo, [make_filter_analysis(interest_score=6)], []),
            (item_hi, [make_filter_analysis(interest_score=10)], []),
        ]
        md = render_bulk_markdown(triples)
        assert md.index("High Scorer") < md.index("Low Scorer")

    def test_uncategorized_items_grouped_under_other(self):
        item = make_item()
        # No filter analysis → no category
        triples = [(item, [], [])]
        md = render_bulk_markdown(triples)
        assert "## other" in md

    def test_header_counts(self):
        triples = [
            (make_item(id=1, source="blog"), [make_filter_analysis()], []),
            (make_item(id=2, source="reddit", url="https://r.example"),
             [make_filter_analysis(category="paper")], []),
            (make_item(id=3, source="blog", url="https://b.example"),
             [make_filter_analysis()], []),
        ]
        md = render_bulk_markdown(triples)
        assert "**3 items**" in md
        assert "2 sources" in md  # blog + reddit
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_export.py::TestRenderBulkMarkdown -v`
Expected: ImportError on `render_bulk_markdown`.

- [ ] **Step 3: Implement `render_bulk_markdown`**

Append to `interfaces/web/export.py`:

```python
from collections import defaultdict


def render_bulk_markdown(
    items_with_data: list[tuple[dict, list[dict], list[dict]]],
) -> str:
    """Render multiple items as one combined markdown document.

    Items are grouped by category (from each item's filter analysis, falling
    back to "other"). Categories are sorted by max interest_score in the group;
    items within a category are sorted by interest_score desc.

    Per-item rendering uses heading_offset=2 so the document has a single H1
    (the export header), categories are H2, and per-item titles are H3.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not items_with_data:
        return (
            f"# TrendBot export — {today}\n"
            f"\n"
            f"**0 items**, exported on {_now_utc_str()}\n"
            f"\n"
            f"(no items)\n"
        )

    # Bucket items by category, tracking each item's interest_score for sorting.
    Bucket = list[tuple[int, tuple[dict, list[dict], list[dict]]]]
    by_category: dict[str, Bucket] = defaultdict(list)
    sources: set[str] = set()

    for triple in items_with_data:
        item, analyses, _ = triple
        filter_content = _extract_filter_content(analyses) or {}
        category = filter_content.get("category") or "other"
        score = filter_content.get("interest_score") or 0
        by_category[category].append((score, triple))
        if item.get("source"):
            sources.add(item["source"])

    # Sort categories by max score within group (desc).
    cat_max = {cat: max(s for s, _ in items) for cat, items in by_category.items()}
    sorted_categories = sorted(by_category.keys(), key=lambda c: -cat_max[c])

    lines: list[str] = []
    lines.append(f"# TrendBot export — {today}")
    lines.append("")
    lines.append(
        f"**{len(items_with_data)} items** across {len(sources)} sources, "
        f"exported on {_now_utc_str()}"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    for category in sorted_categories:
        lines.append(f"## {category}")
        lines.append("")
        # Items sorted by score desc within the bucket.
        for _, (item, analyses, scores) in sorted(
            by_category[category], key=lambda pair: -pair[0]
        ):
            # heading_offset=2 → per-item H1 becomes H3, H2 becomes H4.
            lines.append(render_item_markdown(item, analyses, scores, heading_offset=2))

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_export.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add interfaces/web/export.py tests/test_export.py
git commit -m "feat(export): bulk markdown formatter with category grouping"
```

---

## Task 4: GET /api/items/{id}/export.md endpoint

**Files:**
- Modify: `interfaces/web/app.py`
- Modify: `tests/test_export.py`

- [ ] **Step 1: Write failing endpoint tests**

Append to `tests/test_export.py`:

```python
import json as _json
import pytest
from fastapi.testclient import TestClient

from db.database import Database
from db.queries import upsert_item, snapshot_score
from interfaces.web.app import create_app


@pytest.fixture
def db(tmp_path):
    database = Database(db_path=tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def seeded_export_db(db):
    """One item with a filter analysis, a deep-dive analysis, and a score row."""
    item_id = upsert_item(
        db,
        url="https://blog.google/gemini-3/",
        title="Gemini 3 Launch",
        source="blog",
        description="Major frontier model release.",
        raw_metrics={},
        momentum_score=0.0,
        normalized_score=48.0,
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO item_analysis (item_id, analysis_type, created_at, content) "
            "VALUES (?, 'filter', datetime('now'), ?)",
            (item_id, _json.dumps({
                "novel": True, "ai_relevant": True,
                "interest_score": 9, "category": "model",
                "summary": "Gemini 3 launch — major model release.",
            })),
        )
        conn.execute(
            "INSERT INTO item_analysis (item_id, analysis_type, created_at, content) "
            "VALUES (?, 'deep_dive', datetime('now'), ?)",
            (item_id, _json.dumps({
                "thesis": "Step change in reasoning quality.",
                "key_findings": ["10x scaling", "Multimodal native"],
            })),
        )
        conn.commit()
    snapshot_score(db, item_id, momentum_score=0.5, normalized_score=40.0)
    snapshot_score(db, item_id, momentum_score=0.8, normalized_score=48.0)
    return db, item_id


@pytest.fixture
def export_client(seeded_export_db):
    db, _ = seeded_export_db
    return TestClient(create_app(db, config={}))


class TestGetItemExport:
    def test_returns_markdown(self, export_client, seeded_export_db):
        _, item_id = seeded_export_db
        resp = export_client.get(f"/api/items/{item_id}/export.md")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")

    def test_content_disposition_attachment(self, export_client, seeded_export_db):
        _, item_id = seeded_export_db
        resp = export_client.get(f"/api/items/{item_id}/export.md")
        cd = resp.headers["content-disposition"]
        assert "attachment" in cd
        assert f"item-{item_id}-gemini-3-launch.md" in cd

    def test_filename_falls_back_when_slug_empty(self, db):
        item_id = upsert_item(
            db, url="https://x.example/weird", title="!!!---???",
            source="blog", description="", raw_metrics={},
            momentum_score=0.0, normalized_score=0.0,
        )
        client = TestClient(create_app(db, config={}))
        resp = client.get(f"/api/items/{item_id}/export.md")
        cd = resp.headers["content-disposition"]
        assert f'filename="item-{item_id}.md"' in cd

    def test_body_starts_with_h1(self, export_client, seeded_export_db):
        _, item_id = seeded_export_db
        resp = export_client.get(f"/api/items/{item_id}/export.md")
        assert resp.text.startswith("# Gemini 3 Launch")

    def test_body_includes_analysis_and_scores(self, export_client, seeded_export_db):
        _, item_id = seeded_export_db
        resp = export_client.get(f"/api/items/{item_id}/export.md")
        body = resp.text
        assert "## Summary" in body
        assert "## Analysis — deep_dive" in body
        assert "## Score history" in body

    def test_404_on_missing_item(self, export_client):
        resp = export_client.get("/api/items/99999/export.md")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_export.py::TestGetItemExport -v`
Expected: 404 on every test (route not registered yet).

- [ ] **Step 3: Add the route**

In `interfaces/web/app.py`, add an import near the top with the other interface imports:

```python
from interfaces.web.export import render_item_markdown, render_bulk_markdown, slugify
```

Also add to the existing imports:

```python
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
```

(`Response` is the new one — it lets us set `text/markdown` content-type directly.)

Inside `create_app`, add a helper to load the per-item export bundle and the new route. Put it after the `api_item_scores` route (around line 120):

```python
    def _load_item_export_bundle(item_id: int) -> tuple[dict, list[dict], list[dict]] | None:
        """Fetch item + analyses + score history. Returns None if item missing."""
        item = get_item_by_id(db, item_id)
        if not item:
            return None
        if item.get("raw_metrics"):
            item["raw_metrics"] = json.loads(item["raw_metrics"])
        with db.connect() as conn:
            analysis_rows = conn.execute(
                "SELECT * FROM item_analysis WHERE item_id=? ORDER BY created_at DESC",
                (item_id,),
            ).fetchall()
        analyses = []
        for row in analysis_rows:
            a = dict(row)
            if a.get("content"):
                a["content"] = json.loads(a["content"])
            analyses.append(a)
        scores = get_score_history(db, item_id)
        return item, analyses, scores

    @app.get("/api/items/{item_id}/export.md")
    async def api_item_export(item_id: int):
        bundle = _load_item_export_bundle(item_id)
        if bundle is None:
            raise HTTPException(status_code=404, detail="Item not found")
        item, analyses, scores = bundle

        slug = slugify(item.get("title") or "")
        filename = f"item-{item_id}-{slug}.md" if slug else f"item-{item_id}.md"
        body = render_item_markdown(item, analyses, scores)
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_export.py::TestGetItemExport -v`
Expected: 6 passed.

Also run the full export test file to confirm no regressions:

Run: `pytest tests/test_export.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add interfaces/web/app.py tests/test_export.py
git commit -m "feat(export): GET /api/items/{id}/export.md endpoint"
```

---

## Task 5: POST /api/items/export.md endpoint

**Files:**
- Modify: `interfaces/web/app.py`
- Modify: `tests/test_export.py`

- [ ] **Step 1: Write failing endpoint tests**

Append to `tests/test_export.py`:

```python
class TestPostBulkExport:
    def test_returns_markdown(self, export_client, seeded_export_db):
        _, item_id = seeded_export_db
        resp = export_client.post("/api/items/export.md", json={"ids": [item_id]})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")

    def test_content_disposition_filename(self, export_client, seeded_export_db):
        _, item_id = seeded_export_db
        resp = export_client.post("/api/items/export.md", json={"ids": [item_id]})
        cd = resp.headers["content-disposition"]
        assert "attachment" in cd
        assert "trendbot-export-" in cd
        assert ".md" in cd

    def test_includes_all_requested_items(self, db):
        ids = []
        for i, title in enumerate(["First", "Second", "Third"]):
            ids.append(upsert_item(
                db, url=f"https://x.example/{i}", title=title,
                source="blog", description="", raw_metrics={},
                momentum_score=0.0, normalized_score=0.0,
            ))
        client = TestClient(create_app(db, config={}))
        resp = client.post("/api/items/export.md", json={"ids": ids})
        assert resp.status_code == 200
        body = resp.text
        for title in ["First", "Second", "Third"]:
            assert title in body

    def test_missing_ids_silently_skipped(self, export_client, seeded_export_db):
        _, item_id = seeded_export_db
        resp = export_client.post(
            "/api/items/export.md",
            json={"ids": [item_id, 99998, 99999]},
        )
        assert resp.status_code == 200
        # Real item present, missing ones don't break the export
        assert "Gemini 3 Launch" in resp.text

    def test_all_missing_returns_empty_export(self, export_client):
        resp = export_client.post(
            "/api/items/export.md",
            json={"ids": [99998, 99999]},
        )
        assert resp.status_code == 200
        assert "(no items)" in resp.text

    def test_400_when_ids_missing(self, export_client):
        resp = export_client.post("/api/items/export.md", json={})
        assert resp.status_code == 400

    def test_400_when_ids_empty(self, export_client):
        resp = export_client.post("/api/items/export.md", json={"ids": []})
        assert resp.status_code == 400

    def test_400_when_ids_not_a_list(self, export_client):
        resp = export_client.post("/api/items/export.md", json={"ids": "not-a-list"})
        assert resp.status_code == 400

    def test_400_when_ids_contain_non_integer(self, export_client):
        resp = export_client.post("/api/items/export.md", json={"ids": [1, "two", 3]})
        assert resp.status_code == 400

    def test_400_when_too_many_ids(self, export_client):
        resp = export_client.post(
            "/api/items/export.md",
            json={"ids": list(range(1, 102))},
        )
        assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_export.py::TestPostBulkExport -v`
Expected: 405 Method Not Allowed or 404 on every test.

- [ ] **Step 3: Add the bulk route**

In `interfaces/web/app.py`, add right below `api_item_export`:

```python
    @app.post("/api/items/export.md")
    async def api_bulk_export(request: Request):
        body = await request.json()
        ids = body.get("ids")
        if not isinstance(ids, list) or not ids:
            raise HTTPException(
                status_code=400,
                detail="ids must be a non-empty list of integers (max 100)",
            )
        if len(ids) > 100:
            raise HTTPException(
                status_code=400,
                detail="ids must be a non-empty list of integers (max 100)",
            )
        if not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            raise HTTPException(
                status_code=400,
                detail="ids must be a non-empty list of integers (max 100)",
            )

        bundles = []
        for item_id in ids:
            bundle = _load_item_export_bundle(item_id)
            if bundle is not None:
                bundles.append(bundle)

        body_md = render_bulk_markdown(bundles)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = f"trendbot-export-{today}.md"
        return Response(
            content=body_md,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
```

Add the `datetime`/`timezone` import at the top of `interfaces/web/app.py`:

```python
from datetime import datetime, timezone
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_export.py::TestPostBulkExport -v`
Expected: 10 passed.

Run the full export file:

Run: `pytest tests/test_export.py -v`
Expected: all pass.

Run the full suite to confirm no regressions:

Run: `pytest tests/ -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add interfaces/web/app.py tests/test_export.py
git commit -m "feat(export): POST /api/items/export.md bulk endpoint"
```

---

## Task 6: Per-card export icon + data-item-id

**Files:**
- Modify: `interfaces/web/templates/index.html`

UI change — no automated test (existing dashboard JS isn't tested either). Verify by visual inspection.

- [ ] **Step 1: Update the card markup**

Open `interfaces/web/templates/index.html`. Replace the entire card block (currently the `<div class="card">...</div>` inside the `{% for item in items %}` loop) with:

```html
<div class="card" data-item-id="{{ item.id }}">
    <div style="display: flex; justify-content: space-between; align-items: start; gap: 16px;">
        <div style="flex: 1; min-width: 0;">
            <a href="/item/{{ item.id }}" style="font-size: 16px; font-weight: 600;">{{ item.title[:120] }}</a>
            {% if item.llm_summary %}
            <p style="margin: 6px 0; color: #cbd5e1; font-size: 14px;">{{ item.llm_summary }}</p>
            {% endif %}
            <div class="meta" style="margin-top: 4px;">
                <span class="badge badge-{{ item.source }}">{{ item.source }}</span>
                {% if item.category %}<span class="badge" style="background:#334155;color:#e2e8f0;">{{ item.category }}</span>{% endif %}
                <span style="margin-left: 6px;">Seen {{ item.times_seen }}x</span>
                {% if item.url %} · <a href="{{ item.url }}" target="_blank">↗ source</a>{% endif %}
            </div>
        </div>
        <div style="text-align: right; flex-shrink: 0;">
            <div class="score">{{ item.interest_score }}<span style="color:#64748b;font-size:14px;">/10</span></div>
            <div class="meta" style="font-size: 11px;">rank {{ "%.0f"|format(item.normalized_score) }}</div>
            <a href="/api/items/{{ item.id }}/export.md"
               class="btn btn-secondary"
               style="margin-top: 8px; font-size: 12px; padding: 4px 10px;"
               title="Export to Markdown">⬇ md</a>
        </div>
    </div>
</div>
```

Two changes:
- `data-item-id="{{ item.id }}"` on the outer `.card` div.
- New ⬇ md anchor in the right-hand column under the score/rank.

- [ ] **Step 2: Manual verification**

Start the dashboard:

```bash
python main.py --no-telegram
```

Open http://localhost:8090. Confirm:
- Each card shows a ⬇ md button under the score
- Clicking the button downloads `item-{id}-{slug}.md`
- Opening the file shows a markdown document starting with `# {title}`

- [ ] **Step 3: Commit**

```bash
git add interfaces/web/templates/index.html
git commit -m "feat(export): per-card markdown export button"
```

---

## Task 7: Item detail page export button

**Files:**
- Modify: `interfaces/web/templates/item.html`

- [ ] **Step 1: Update the back-button row**

Open `interfaces/web/templates/item.html`. Replace the `<div style="margin: 20px 0;">` block (currently containing only the Back link) with:

```html
<div style="margin: 20px 0; display: flex; gap: 8px; align-items: center;">
    <a href="/" class="btn btn-secondary">← Back</a>
    <a href="/api/items/{{ item.id }}/export.md" class="btn btn-secondary">⬇ Export to Markdown</a>
</div>
```

- [ ] **Step 2: Manual verification**

With `python main.py --no-telegram` running, open http://localhost:8090/item/<some-id>. Confirm:
- The export button appears next to "← Back"
- Clicking it downloads the same `.md` file as the dashboard card button

- [ ] **Step 3: Commit**

```bash
git add interfaces/web/templates/item.html
git commit -m "feat(export): markdown export button on item detail page"
```

---

## Task 8: "Export visible (N)" button + bulk download JS

**Files:**
- Modify: `interfaces/web/templates/index.html`

- [ ] **Step 1: Add the button and JS**

Open `interfaces/web/templates/index.html`. The current file is:

```html
{% extends "base.html" %}
{% block title %}TrendBot — Dashboard{% endblock %}
{% block content %}
<h1 style="margin: 20px 0;">Trending Items</h1>
<div id="items">
{% for item in items %}
... (cards) ...
{% endfor %}
{% if not items %}
<p class="meta">No filter-approved items yet. The filter agent runs after each scoring pass — check back in a few cycles.</p>
{% endif %}
</div>
{% endblock %}
```

Replace the entire `{% block content %}` body with:

```html
<div style="margin: 20px 0; display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
    <h1 style="margin: 0;">Trending Items</h1>
    <input type="text" id="search" placeholder="Search…"
           style="flex: 1; min-width: 200px; padding: 6px 10px; background:#1e293b; border:1px solid #334155; border-radius:6px; color:#e2e8f0;">
    <button id="export-visible" class="btn btn-secondary" disabled>⬇ Export visible (0)</button>
</div>
<div id="items">
{% for item in items %}
<div class="card" data-item-id="{{ item.id }}">
    <div style="display: flex; justify-content: space-between; align-items: start; gap: 16px;">
        <div style="flex: 1; min-width: 0;">
            <a href="/item/{{ item.id }}" style="font-size: 16px; font-weight: 600;">{{ item.title[:120] }}</a>
            {% if item.llm_summary %}
            <p style="margin: 6px 0; color: #cbd5e1; font-size: 14px;">{{ item.llm_summary }}</p>
            {% endif %}
            <div class="meta" style="margin-top: 4px;">
                <span class="badge badge-{{ item.source }}">{{ item.source }}</span>
                {% if item.category %}<span class="badge" style="background:#334155;color:#e2e8f0;">{{ item.category }}</span>{% endif %}
                <span style="margin-left: 6px;">Seen {{ item.times_seen }}x</span>
                {% if item.url %} · <a href="{{ item.url }}" target="_blank">↗ source</a>{% endif %}
            </div>
        </div>
        <div style="text-align: right; flex-shrink: 0;">
            <div class="score">{{ item.interest_score }}<span style="color:#64748b;font-size:14px;">/10</span></div>
            <div class="meta" style="font-size: 11px;">rank {{ "%.0f"|format(item.normalized_score) }}</div>
            <a href="/api/items/{{ item.id }}/export.md"
               class="btn btn-secondary"
               style="margin-top: 8px; font-size: 12px; padding: 4px 10px;"
               title="Export to Markdown">⬇ md</a>
        </div>
    </div>
</div>
{% endfor %}
{% if not items %}
<p class="meta">No filter-approved items yet. The filter agent runs after each scoring pass — check back in a few cycles.</p>
{% endif %}
</div>

<script>
(function () {
    const search = document.getElementById('search');
    const button = document.getElementById('export-visible');
    const cards = Array.from(document.querySelectorAll('.card[data-item-id]'));

    function visibleCards() {
        return cards.filter(c => c.style.display !== 'none');
    }

    function refreshButton() {
        const n = visibleCards().length;
        button.textContent = `⬇ Export visible (${n})`;
        button.disabled = n === 0;
    }

    if (search) {
        search.addEventListener('input', function (e) {
            const q = e.target.value.toLowerCase();
            cards.forEach(card => {
                const text = (card.textContent || '').toLowerCase();
                card.style.display = text.includes(q) ? '' : 'none';
            });
            refreshButton();
        });
    }

    button.addEventListener('click', async function () {
        const ids = visibleCards().map(c => parseInt(c.dataset.itemId, 10));
        if (ids.length === 0) return;
        button.disabled = true;
        try {
            const resp = await fetch('/api/items/export.md', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: ids }),
            });
            if (!resp.ok) throw new Error(`Export failed: ${resp.status}`);
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            const today = new Date().toISOString().slice(0, 10);
            a.download = `trendbot-export-${today}.md`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (err) {
            alert('Export failed: ' + err.message);
        } finally {
            refreshButton();
        }
    });

    refreshButton();
})();
</script>
```

Note: this consolidates the new top bar (search + export button) and the cards into one block. The `<script>` at the bottom owns both the search filtering and the export click. The previous `index.html` did not have its own search box (the legacy template did) — adding one here keeps the export-visible feature meaningful.

- [ ] **Step 2: Manual verification**

With `python main.py --no-telegram` running, open http://localhost:8090. Confirm:
- The "⬇ Export visible (N)" button appears next to the search box, where N matches the number of cards on the page.
- Typing in the search box filters cards and updates N in the button label.
- Clicking the button downloads `trendbot-export-YYYY-MM-DD.md`.
- The downloaded file has a top-level `# TrendBot export — YYYY-MM-DD` header, a count line, then category sections containing each visible item.
- Typing a search term that matches only some items, then clicking export, produces a file with only the matching items.

- [ ] **Step 3: Commit**

```bash
git add interfaces/web/templates/index.html
git commit -m "feat(export): bulk export-visible button on dashboard"
```

---

## Final verification

- [ ] Run the full test suite one last time:

Run: `pytest tests/ -v`
Expected: all pass.

- [ ] Manually walk through:
  - Per-card download from dashboard → `.md` file with full content
  - Export button on item detail page → same `.md` file
  - Search box filters cards; "Export visible (N)" updates label and exports only filtered cards in one combined file
  - Combined file has correct grouping by category, items sorted by score within each group, and a single H1
