from unittest.mock import patch, MagicMock
from models import RawItem, ScoredItem
from analysis.gatherer import gather_source_material


def _github_scored_item():
    raw = RawItem(title="example/agentkit", url="https://github.com/example/agentkit",
                  source="github", description="Multi-agent framework",
                  metrics={"stargazers_count": 3000}, timestamp="2026-04-08T00:00:00Z")
    return ScoredItem(raw_items=[raw], momentum_score=0.85, final_score=1.7,
                      sources=["github"], category="tool", llm_summary="Agent framework",
                      interest_score=9)


def test_gather_github_fetches_readme():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "# AgentKit\nA multi-agent framework for building AI agents."

    with patch("analysis.gatherer.requests.get", return_value=mock_resp):
        material = gather_source_material(_github_scored_item())
        assert "readme" in material
        assert "AgentKit" in material["readme"]


def test_gather_returns_empty_on_failure():
    with patch("analysis.gatherer.requests.get", side_effect=Exception("Network error")):
        material = gather_source_material(_github_scored_item())
        assert isinstance(material, dict)
        assert material.get("readme", "") == ""
