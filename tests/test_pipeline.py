import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from run import Pipeline, select_diverse_top
from models import RawItem, ScoredItem


def test_pipeline_creates_data_dir(tmp_path):
    config = {
        "scoring": {"digest_size": 5, "deep_dive_count": 2, "min_momentum_score": 0.1,
                     "freshness_half_life_hours": 48, "cross_platform_boost": {2: 1.5, 3: 2.5, 4: 4.0}},
        "sources": {"hackernews": {"enabled": True}},
        "delivery": {"telegram": {"enabled": False}, "dashboard": {"enabled": False}},
    }
    pipeline = Pipeline(config=config, data_root=tmp_path / "data")
    assert pipeline.data_dir.parent == tmp_path / "data"


def test_pipeline_collect_stage(tmp_path):
    config = {
        "scoring": {"digest_size": 5, "deep_dive_count": 2, "min_momentum_score": 0.1,
                     "freshness_half_life_hours": 48, "cross_platform_boost": {2: 1.5, 3: 2.5, 4: 4.0}},
        "sources": {"hackernews": {"enabled": True}, "github": {"enabled": False},
                     "reddit": {"enabled": False}, "arxiv": {"enabled": False},
                     "huggingface": {"enabled": False}, "twitter": {"enabled": False}},
        "delivery": {"telegram": {"enabled": False}, "dashboard": {"enabled": False}},
    }
    pipeline = Pipeline(config=config, data_root=tmp_path / "data")

    mock_items = [RawItem(title="Test", url="http://test.com", source="hackernews",
                          description="", metrics={"points": 100}, timestamp="2026-04-08T00:00:00Z")]
    with patch("run.HackerNewsCollector") as mock_cls:
        mock_collector = MagicMock()
        mock_collector.run.return_value = mock_items
        mock_collector.source_name = "hackernews"
        mock_cls.return_value = mock_collector

        result = pipeline.stage_collect()
        assert len(result) >= 1


def test_pipeline_full_run_with_mocks(tmp_path):
    config = {
        "scoring": {"digest_size": 5, "deep_dive_count": 1, "min_momentum_score": 0.0,
                     "freshness_half_life_hours": 48, "cross_platform_boost": {2: 1.5, 3: 2.5, 4: 4.0}},
        "sources": {"hackernews": {"enabled": True}, "github": {"enabled": False},
                     "reddit": {"enabled": False}, "arxiv": {"enabled": False},
                     "huggingface": {"enabled": False}, "twitter": {"enabled": False}},
        "delivery": {"telegram": {"enabled": False}, "dashboard": {"enabled": True, "port": 8080}},
    }

    mock_items = [
        RawItem(title=f"AI Project {i}", url=f"http://example.com/{i}", source="hackernews",
                description=f"Description {i}", metrics={"points": 100 * (5 - i)},
                timestamp="2026-04-08T00:00:00Z")
        for i in range(5)
    ]

    llm_filter_response = {
        "items": [
            {"index": 0, "category": "tool", "interest_score": 9,
             "summary": "Top project", "novel": True, "ai_relevant": True, "deep_dive": True},
            {"index": 1, "category": "paper", "interest_score": 7,
             "summary": "Good paper", "novel": True, "ai_relevant": True, "deep_dive": False},
        ]
    }

    deep_dive_response = {
        "what_it_is": "A test project",
        "why_trending": "Very popular",
        "pain_point": "Hard problem",
        "gap_analysis": "Missing features",
        "competitors": ["Alt1"],
        "app_idea": "Build something better",
        "feasibility": {"effort": "2 weeks", "market": "growing", "competition": "low"},
    }

    with patch("run.HackerNewsCollector") as mock_hn, \
         patch("scoring.llm_filter.call_claude_json", return_value=llm_filter_response), \
         patch("analysis.deep_dive.call_claude_json", return_value=deep_dive_response), \
         patch("analysis.gatherer.requests.get") as mock_get, \
         patch("reporting.summary.call_claude", return_value="Summary text"):

        def fake_run(data_dir):
            import json
            raw_dir = data_dir / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            with open(raw_dir / "hackernews.json", "w") as f:
                json.dump([item.to_dict() for item in mock_items], f)
            return mock_items

        mock_collector = MagicMock()
        mock_collector.run.side_effect = fake_run
        mock_collector.source_name = "hackernews"
        mock_hn.return_value = mock_collector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "# README"
        mock_resp.json.return_value = {"items": []}
        mock_get.return_value = mock_resp

        pipeline = Pipeline(config=config, data_root=tmp_path / "data", date_str="2026-04-08")
        pipeline.run()

        data_dir = tmp_path / "data" / "2026-04-08"
        assert (data_dir / "raw" / "hackernews.json").exists()
        assert (data_dir / "scored" / "ranked.json").exists()
        assert (data_dir / "reports" / "digest.md").exists()
        assert (data_dir / "reports" / "summary.md").exists()
        assert (data_dir / "reports" / "dashboard" / "index.html").exists()


def _make_scored(title, source, final_score):
    raw = RawItem(title=title, url=f"http://{source}/{title}", source=source,
                  description="", metrics={}, timestamp="")
    return ScoredItem(
        raw_items=[raw], momentum_score=final_score, final_score=final_score,
        sources=[source], category="", llm_summary="", interest_score=0,
    )


def test_select_diverse_top_interleaves_sources():
    items = [
        _make_scored("r1", "reddit", 100),
        _make_scored("r2", "reddit", 90),
        _make_scored("r3", "reddit", 80),
        _make_scored("g1", "github", 70),
        _make_scored("g2", "github", 60),
        _make_scored("h1", "hackernews", 50),
    ]
    result = select_diverse_top(items, count=6)
    first_three_sources = {r.sources[0] for r in result[:3]}
    assert first_three_sources == {"reddit", "github", "hackernews"}


def test_select_diverse_top_respects_count():
    items = [
        _make_scored("r1", "reddit", 100),
        _make_scored("r2", "reddit", 90),
        _make_scored("g1", "github", 80),
        _make_scored("g2", "github", 70),
    ]
    result = select_diverse_top(items, count=3)
    assert len(result) == 3


def test_select_diverse_top_handles_uneven_sources():
    items = [
        _make_scored("r1", "reddit", 100),
        _make_scored("g1", "github", 50),
        _make_scored("g2", "github", 40),
        _make_scored("g3", "github", 30),
    ]
    result = select_diverse_top(items, count=4)
    assert len(result) == 4


def test_pipeline_score_includes_github_items(tmp_path):
    """GitHub items should appear in the ranked output after normalization + diversity."""
    config = {
        "scoring": {"digest_size": 5, "deep_dive_count": 2, "min_momentum_score": 0.0,
                     "freshness_half_life_hours": 48, "cross_platform_boost": {2: 1.5, 3: 2.5, 4: 4.0}},
        "sources": {},
        "delivery": {"telegram": {"enabled": False}, "dashboard": {"enabled": False}},
    }
    pipeline = Pipeline(config=config, data_root=tmp_path / "data")

    raw_items = [
        RawItem(title="Big AI News", url="http://reddit.com/1", source="reddit",
                description="Important", metrics={"score": 5000},
                timestamp="2026-04-09T01:00:00Z"),
        RawItem(title="Another AI Post", url="http://reddit.com/2", source="reddit",
                description="Also important", metrics={"score": 3000},
                timestamp="2026-04-09T01:00:00Z"),
        RawItem(title="New agent framework", url="http://github.com/1", source="github",
                description="Cool new tool", metrics={"stargazers_count": 500, "age_days": 3},
                timestamp="2026-04-09T00:00:00Z"),
        RawItem(title="ML compiler", url="http://github.com/2", source="github",
                description="Fast ML compiler", metrics={"stargazers_count": 200, "age_days": 5},
                timestamp="2026-04-09T00:00:00Z"),
    ]

    llm_filter_response = {
        "items": [
            {"index": i, "category": "tool", "interest_score": 8,
             "summary": f"Item {i}", "novel": True, "ai_relevant": True, "deep_dive": False}
            for i in range(4)
        ]
    }

    with patch("scoring.llm_filter.call_claude_json", return_value=llm_filter_response):
        digest, _ = pipeline.stage_score(raw_items)

    sources_in_digest = set()
    for item in digest:
        sources_in_digest.update(item.sources)
    assert "github" in sources_in_digest, "GitHub items should appear in digest after normalization"
    assert "reddit" in sources_in_digest
