from models import RawItem, ScoredItem, AnalysisReport
from datetime import datetime, timezone


def test_raw_item_from_dict(sample_raw_item):
    item = RawItem.from_dict(sample_raw_item)
    assert item.title == "AgentKit v2"
    assert item.source == "github"
    assert item.metrics["stars_24h"] == 1200


def test_raw_item_to_dict(sample_raw_item):
    item = RawItem.from_dict(sample_raw_item)
    d = item.to_dict()
    assert d["title"] == "AgentKit v2"
    assert d["url"] == "https://github.com/example/agentkit"


def test_scored_item_from_raw(sample_raw_item):
    raw = RawItem.from_dict(sample_raw_item)
    scored = ScoredItem(
        raw_items=[raw],
        momentum_score=0.85,
        final_score=1.7,
        sources=["github"],
        category="tool",
        llm_summary="Multi-agent framework with visual builder",
        interest_score=9,
    )
    assert scored.final_score == 1.7
    assert scored.title == "AgentKit v2"
    assert len(scored.sources) == 1


def test_scored_item_title_uses_first_raw():
    item1 = RawItem.from_dict({
        "title": "First Title", "url": "http://a.com", "source": "github",
        "description": "", "metrics": {}, "timestamp": "2026-04-08T00:00:00Z",
    })
    item2 = RawItem.from_dict({
        "title": "Second Title", "url": "http://a.com", "source": "reddit",
        "description": "", "metrics": {}, "timestamp": "2026-04-08T00:00:00Z",
    })
    scored = ScoredItem(
        raw_items=[item1, item2], momentum_score=0.5, final_score=1.0,
        sources=["github", "reddit"], category="tool", llm_summary="", interest_score=5,
    )
    assert scored.title == "First Title"


def test_scored_item_normalized_score_defaults():
    raw = RawItem.from_dict({
        "title": "Test", "url": "http://a.com", "source": "github",
        "description": "", "metrics": {}, "timestamp": "2026-04-08T00:00:00Z",
    })
    scored = ScoredItem(
        raw_items=[raw], momentum_score=1.0, final_score=0.6,
        sources=["github"], category="tool", llm_summary="", interest_score=5,
    )
    assert scored.normalized_score == 0.0


def test_scored_item_normalized_score_in_to_dict():
    raw = RawItem.from_dict({
        "title": "Test", "url": "http://a.com", "source": "github",
        "description": "", "metrics": {}, "timestamp": "2026-04-08T00:00:00Z",
    })
    scored = ScoredItem(
        raw_items=[raw], momentum_score=1.0, final_score=0.6,
        sources=["github"], category="tool", llm_summary="", interest_score=5,
        normalized_score=75.0,
    )
    d = scored.to_dict()
    assert d["normalized_score"] == 75.0


def test_analysis_report_to_dict():
    report = AnalysisReport(
        slug="agentkit-v2",
        title="AgentKit v2",
        what_it_is="A multi-agent framework",
        why_trending="1.2k stars in 24h",
        pain_point="Building multi-agent systems is hard",
        gap_analysis="No visual builder exists",
        competitors=["CrewAI", "AutoGen"],
        app_idea="Visual drag-and-drop agent builder",
        feasibility={"effort": "3 weeks", "market": "growing", "competition": "low"},
    )
    d = report.to_dict()
    assert d["slug"] == "agentkit-v2"
    assert "CrewAI" in d["competitors"]
