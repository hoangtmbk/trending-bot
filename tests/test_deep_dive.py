from unittest.mock import patch
from pathlib import Path
from models import RawItem, ScoredItem, AnalysisReport
from analysis.deep_dive import run_deep_dive, run_deep_dives


def _scored_item():
    raw = RawItem(title="example/agentkit", url="https://github.com/example/agentkit",
                  source="github", description="Multi-agent framework",
                  metrics={}, timestamp="2026-04-08T00:00:00Z")
    return ScoredItem(raw_items=[raw], momentum_score=0.85, final_score=1.7,
                      sources=["github"], category="tool", llm_summary="Agent framework",
                      interest_score=9)


def _mock_claude_response():
    return {
        "what_it_is": "A multi-agent orchestration framework",
        "why_trending": "1.2k stars in 24h, launched yesterday",
        "pain_point": "Building multi-agent systems requires gluing together disparate frameworks",
        "gap_analysis": "No visual builder exists. Config is YAML-heavy.",
        "competitors": ["CrewAI", "AutoGen", "LangGraph"],
        "app_idea": "Visual drag-and-drop agent builder for non-dev AI teams",
        "feasibility": {"effort": "3 weeks MVP", "market": "growing", "competition": "low"},
    }


def test_run_deep_dive_returns_report():
    material = {"readme": "# AgentKit\nBuild agents easily", "competitors": ""}
    with patch("analysis.deep_dive.gather_source_material", return_value=material), \
         patch("analysis.deep_dive.call_claude_json", return_value=_mock_claude_response()):
        report = run_deep_dive(_scored_item())
        assert isinstance(report, AnalysisReport)
        assert report.slug == "example-agentkit"
        assert "multi-agent" in report.what_it_is.lower()


def test_run_deep_dives_saves_to_disk(tmp_path):
    material = {"readme": "# AgentKit\nBuild agents easily", "competitors": ""}
    with patch("analysis.deep_dive.gather_source_material", return_value=material), \
         patch("analysis.deep_dive.call_claude_json", return_value=_mock_claude_response()):
        data_dir = tmp_path / "data" / "2026-04-08"
        reports = run_deep_dives([_scored_item()], data_dir)
        assert len(reports) == 1
        analysis_dir = data_dir / "analysis"
        assert analysis_dir.exists()
        md_files = list(analysis_dir.glob("*.md"))
        assert len(md_files) == 1
