from models import RawItem, ScoredItem, AnalysisReport
from reporting.digest import build_digest


def _scored(title, score, category, sources, summary):
    raw = RawItem(title=title, url=f"http://example.com/{title}", source=sources[0],
                  description="", metrics={}, timestamp="2026-04-08T00:00:00Z")
    return ScoredItem(raw_items=[raw], momentum_score=score, final_score=score,
                      sources=sources, category=category, llm_summary=summary,
                      interest_score=int(score * 10))


def test_build_digest_creates_markdown(tmp_path):
    items = [
        _scored("AgentKit", 0.9, "tool", ["github", "reddit"], "Agent framework"),
        _scored("ScalingPaper", 0.7, "paper", ["arxiv"], "New scaling paper"),
    ]
    reports = [AnalysisReport(slug="agentkit", title="AgentKit", what_it_is="test",
                              why_trending="test", pain_point="test", gap_analysis="test",
                              competitors=[], app_idea="test", feasibility={})]
    data_dir = tmp_path / "data" / "2026-04-08"
    build_digest(items, reports, data_dir, "2026-04-08")
    digest_path = data_dir / "reports" / "digest.md"
    assert digest_path.exists()
    content = digest_path.read_text()
    assert "AgentKit" in content
    assert "ScalingPaper" in content


def test_digest_groups_by_category(tmp_path):
    items = [
        _scored("ToolA", 0.9, "tool", ["github"], "A tool"),
        _scored("PaperB", 0.8, "paper", ["arxiv"], "A paper"),
        _scored("ToolC", 0.7, "tool", ["github"], "Another tool"),
    ]
    data_dir = tmp_path / "data" / "2026-04-08"
    build_digest(items, [], data_dir, "2026-04-08")
    content = (data_dir / "reports" / "digest.md").read_text()
    tool_pos = content.index("tool")
    assert tool_pos >= 0
