import json as _json
import pytest
from fastapi.testclient import TestClient

from db.database import Database
from db.queries import upsert_item, snapshot_score
from interfaces.web.app import create_app
from interfaces.web.export import slugify, render_item_markdown, render_bulk_markdown


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
        assert len(result) == 50

    def test_truncate_does_not_leave_trailing_dash(self):
        # 49 a's + space + bbbbb → naive slice gives 'a'*49 + '-' (trailing dash)
        result = slugify(("a" * 49) + " bbbbb")
        assert result == "a" * 49

    def test_empty_input_returns_empty(self):
        assert slugify("") == ""

    def test_only_punctuation_returns_empty(self):
        assert slugify("!!!---???") == ""

    def test_unicode_treated_as_non_alphanumeric(self):
        # Keep it ASCII-only — unicode chars become dashes.
        assert slugify("café résumé") == "caf-r-sum"


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

    def test_analysis_with_only_empty_values_skipped(self):
        # An analysis whose content values all stringify to "" should not
        # leave an orphan "## Analysis — {type}" heading in the output.
        empty_analysis = {
            "id": 99, "item_id": 42, "analysis_type": "deep_dive",
            "created_at": "2026-04-22T09:00:00+00:00",
            "content": {"thesis": None, "key_findings": None},
        }
        md = render_item_markdown(make_item(), [empty_analysis], [])
        assert "## Analysis — deep_dive" not in md

    def test_heading_offset_demotes_all_headings(self):
        # heading_offset=2 → per-item H1 becomes H3, H2 becomes H4.
        # Used by render_bulk_markdown so the document has a single H1.
        md = render_item_markdown(
            make_item(),
            [make_filter_analysis(), make_deep_dive_analysis()],
            [make_score("2026-04-21T10:00:00+00:00", 0.5, 40.0)],
            heading_offset=2,
        )
        assert "### Gemini 3 launch announcement" in md
        # No bare H1 anywhere
        assert "\n# " not in md
        assert not md.startswith("# ")
        # Per-item H2 sections become H4
        assert "#### Summary" in md
        assert "#### Description" in md
        assert "#### Analysis — deep_dive" in md
        assert "#### Score history" in md


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
        # heading_offset=2: per-item H1 (item title) is demoted to H3
        # under the document H1 and category H2.
        assert "\n### Gemini 3 launch announcement\n" in md
        # Per-item H2 sections (Summary, Description, …) become H4.
        assert "\n#### Summary\n" in md

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
        # heading_offset=2: per-item H1 (item title) becomes H3.
        assert "\n### Model A\n" in md
        assert "\n### Tool B\n" in md

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
