from unittest.mock import patch
from models import RawItem, ScoredItem
from reporting.summary import build_summary


def _scored(title, score, category, sources, summary):
    raw = RawItem(title=title, url=f"http://example.com/{title}", source=sources[0],
                  description="", metrics={}, timestamp="2026-04-08T00:00:00Z")
    return ScoredItem(raw_items=[raw], momentum_score=score, final_score=score,
                      sources=sources, category=category, llm_summary=summary,
                      interest_score=int(score * 10))


def test_build_summary_creates_file(tmp_path):
    items = [_scored("AgentKit", 0.9, "tool", ["github"], "Agent framework")]
    mock_response = "Today's top trend is AgentKit, a multi-agent framework gaining rapid traction."
    with patch("reporting.summary.call_claude", return_value=mock_response):
        data_dir = tmp_path / "data" / "2026-04-08"
        path = build_summary(items, [], data_dir, "2026-04-08")
        assert path.exists()
        content = path.read_text()
        assert "AgentKit" in content


def test_build_summary_fallback_on_error(tmp_path):
    items = [_scored("AgentKit", 0.9, "tool", ["github"], "Agent framework")]
    with patch("reporting.summary.call_claude", side_effect=RuntimeError("fail")):
        data_dir = tmp_path / "data" / "2026-04-08"
        path = build_summary(items, [], data_dir, "2026-04-08")
        assert path.exists()
        content = path.read_text()
        assert "AgentKit" in content
