import json
from unittest.mock import patch
from models import RawItem, ScoredItem
from scoring.llm_filter import run_llm_filter


def _scored_items():
    items = []
    for i in range(5):
        raw = RawItem(title=f"Project {i}", url=f"http://example.com/{i}", source="github",
                      description=f"Description {i}", metrics={"stargazers_count": 1000 * (5 - i)},
                      timestamp="2026-04-08T00:00:00Z")
        items.append(ScoredItem(
            raw_items=[raw], momentum_score=1.0 - i * 0.1, final_score=1.0 - i * 0.1,
            sources=["github"], category="", llm_summary="", interest_score=0,
        ))
    return items


def test_llm_filter_enriches_items():
    llm_response = {
        "items": [
            {"index": 0, "category": "tool", "interest_score": 9,
             "summary": "Great tool", "novel": True, "ai_relevant": True, "deep_dive": True},
            {"index": 1, "category": "paper", "interest_score": 7,
             "summary": "Good paper", "novel": True, "ai_relevant": True, "deep_dive": False},
            {"index": 2, "category": "tool", "interest_score": 3,
             "summary": "Minor fork", "novel": False, "ai_relevant": True, "deep_dive": False},
        ]
    }
    with patch("scoring.llm_filter.call_claude_json", return_value=llm_response):
        digest, deep_dives = run_llm_filter(_scored_items(), digest_size=10, deep_dive_count=5)
        assert len(digest) == 2
        assert digest[0].category == "tool"
        assert digest[0].interest_score == 9
        assert len(deep_dives) == 1


def test_llm_filter_falls_back_on_error():
    with patch("scoring.llm_filter.call_claude_json", side_effect=RuntimeError("Claude down")):
        items = _scored_items()
        digest, deep_dives = run_llm_filter(items, digest_size=3, deep_dive_count=2)
        assert len(digest) == 3
        assert len(deep_dives) == 2
