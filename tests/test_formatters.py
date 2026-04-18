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
        assert "\U0001F4A1" not in text

    def test_renders_without_summaries_when_empty_dict(self):
        text = format_digest([_item(1)], summaries={})
        assert "\U0001F4A1" not in text

    def test_renders_summary_line_when_present(self):
        text = format_digest(
            [_item(1)],
            summaries={1: "A crisp one-line summary of Item 1."},
        )
        assert "\U0001F4A1" in text
        assert "A crisp one-line summary of Item 1." in text
        assert "<i>A crisp one-line summary of Item 1.</i>" in text

    def test_truncates_summary_at_140_chars(self):
        long = "x" * 500
        text = format_digest([_item(1)], summaries={1: long})
        assert "x" * 140 + "\u2026" in text
        assert "x" * 141 not in text

    def test_html_escapes_summary(self):
        text = format_digest(
            [_item(1)],
            summaries={1: "<script>alert(1)</script> & co"},
        )
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
        assert "&amp; co" in text
        assert "<script>" not in text

    def test_skips_summary_for_items_without_entry(self):
        text = format_digest(
            [_item(1), _item(2)],
            summaries={1: "Only item 1 has a summary."},
        )
        assert "Only item 1 has a summary." in text
        item2_section = text.split("2. ")[1]
        assert "\U0001F4A1" not in item2_section


class TestFormatDeepDivesFollowup:
    def _dd(self, **overrides) -> dict:
        base = {
            "what_it_is": "A new AI memory system.",
            "why_trending": "Beats MemGPT on LoCoMo.",
            "pain_point": "LLMs forget context across sessions.",
            "app_idea": "Drop-in Python SDK for memory layers.",
            "competitors": ["MemGPT", "Letta", "Zep"],
            "gap_analysis": "should be omitted",
            "feasibility": {"effort": "2 weeks"},
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
        assert text.index("#1") < text.index("#3")
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
        tail = text.split("<b>Competitors:</b>")[1]
        assert "F" not in tail

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
