from models import RawItem, ScoredItem, AnalysisReport
from reporting.dashboard import build_dashboard


def _scored(title, score, category, sources, summary):
    raw = RawItem(title=title, url=f"http://example.com/{title}", source=sources[0],
                  description="desc", metrics={}, timestamp="2026-04-08T00:00:00Z")
    return ScoredItem(raw_items=[raw], momentum_score=score, final_score=score,
                      sources=sources, category=category, llm_summary=summary,
                      interest_score=int(score * 10))


def _report(slug, title):
    return AnalysisReport(slug=slug, title=title, what_it_is="A tool",
                          why_trending="Viral", pain_point="Hard problem",
                          gap_analysis="Missing features", competitors=["Alt1"],
                          app_idea="Build X", feasibility={"effort": "2 weeks"})


def test_build_dashboard_creates_index(tmp_path):
    items = [_scored("AgentKit", 0.9, "tool", ["github"], "Agent framework")]
    reports = [_report("agentkit", "AgentKit")]
    data_dir = tmp_path / "data" / "2026-04-08"
    build_dashboard(items, reports, data_dir, "2026-04-08")
    index = data_dir / "reports" / "dashboard" / "index.html"
    assert index.exists()
    content = index.read_text()
    assert "AgentKit" in content


def test_build_dashboard_creates_item_pages(tmp_path):
    items = [_scored("AgentKit", 0.9, "tool", ["github"], "Agent framework")]
    reports = [_report("agentkit", "AgentKit")]
    data_dir = tmp_path / "data" / "2026-04-08"
    build_dashboard(items, reports, data_dir, "2026-04-08")
    item_page = data_dir / "reports" / "dashboard" / "agentkit.html"
    assert item_page.exists()
    content = item_page.read_text()
    assert "Build X" in content
