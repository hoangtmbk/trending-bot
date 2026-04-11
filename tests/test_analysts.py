import json
import pytest
from unittest.mock import patch, MagicMock
from db.database import Database
from db.queries import upsert_item, get_items, get_item_by_url
from orchestrator.events import EventBus
from agents.base import AgentContext


# ---------- fixtures ----------

@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def event_bus():
    return EventBus()


def _seed_items(db, count=5, source="github"):
    """Insert test items into the DB and return their IDs."""
    ids = []
    for i in range(count):
        metrics = {"stargazers_count": (i + 1) * 100, "forks_count": (i + 1) * 10, "age_days": i + 1}
        item_id = upsert_item(
            db,
            url=f"https://github.com/test/repo-{i}",
            title=f"Test Repo {i}",
            source=source,
            description=f"Description for repo {i}",
            raw_metrics=metrics,
            momentum_score=float(i * 10),
            normalized_score=float(i * 20),
        )
        ids.append(item_id)
    return ids


def _seed_mixed_source_items(db):
    """Insert items from multiple sources for cross-source testing."""
    items = [
        ("https://github.com/test/alpha", "Alpha Framework", "github",
         {"stargazers_count": 500, "forks_count": 50, "age_days": 5}),
        ("https://reddit.com/r/ml/post1", "Alpha Framework Discussion", "reddit",
         {"score": 200, "upvote_ratio": 0.95, "num_comments": 30,
          "total_awards": 0, "num_crossposts": 0, "subreddit": "MachineLearning"}),
        ("https://github.com/test/beta", "Beta Tool", "github",
         {"stargazers_count": 300, "forks_count": 30, "age_days": 2}),
        ("https://arxiv.org/abs/2026.1234", "Novel Attention Mechanism", "arxiv",
         {"citation_count": 10, "influential_citations": 3, "categories": ["cs.AI"]}),
        ("https://huggingface.co/test/model", "Test LLM v2", "huggingface",
         {"downloads": 5000, "likes": 100, "tags": ["text-generation"],
          "pipeline_tag": "text-generation"}),
    ]
    ids = []
    for url, title, source, metrics in items:
        item_id = upsert_item(
            db, url=url, title=title, source=source,
            description=f"Desc of {title}",
            raw_metrics=metrics,
            momentum_score=10.0,
            normalized_score=50.0,
        )
        ids.append(item_id)
    return ids


# ========== TrendScorer ==========

class TestTrendScorer:

    def test_scores_recent_items(self, db, event_bus):
        from agents.analysts.scorer import TrendScorer

        _seed_items(db, count=3, source="github")
        ctx = AgentContext(
            db=db, event_bus=event_bus,
            config={"scoring": {"freshness_half_life_hours": 48}},
        )

        scorer = TrendScorer()
        result = scorer.execute(ctx)

        assert result.success is True
        assert result.data["scored_count"] == 3

        # Verify scores were updated in DB
        items = get_items(db, source="github", order_by="normalized_score DESC")
        assert len(items) == 3
        # The item with highest stargazers_count/age_days should have highest normalized score
        # repo-2: 300/3=100, repo-1: 200/2=100, repo-0: 100/1=100
        # They all have the same momentum, but normalized will rank them
        for item in items:
            assert item["momentum_score"] >= 0.0

    def test_no_items_returns_early(self, db, event_bus):
        from agents.analysts.scorer import TrendScorer

        ctx = AgentContext(
            db=db, event_bus=event_bus,
            config={"scoring": {}},
        )

        scorer = TrendScorer()
        result = scorer.execute(ctx)

        assert result.success is True
        assert "No recent items" in result.message

    def test_emits_scores_updated_event(self, db, event_bus):
        from agents.analysts.scorer import TrendScorer

        _seed_items(db, count=2)
        received = []
        event_bus.subscribe("scores_updated", lambda d: received.append(d))

        ctx = AgentContext(
            db=db, event_bus=event_bus,
            config={"scoring": {}},
        )

        scorer = TrendScorer()
        scorer.execute(ctx)

        assert len(received) == 1
        assert received[0]["count"] == 2

    def test_scores_multiple_sources(self, db, event_bus):
        from agents.analysts.scorer import TrendScorer

        _seed_mixed_source_items(db)

        ctx = AgentContext(
            db=db, event_bus=event_bus,
            config={"scoring": {"freshness_half_life_hours": 48}},
        )

        scorer = TrendScorer()
        result = scorer.execute(ctx)

        assert result.success is True
        assert result.data["scored_count"] == 5

        # Check that items from each source were scored
        github_items = get_items(db, source="github")
        reddit_items = get_items(db, source="reddit")
        arxiv_items = get_items(db, source="arxiv")
        assert len(github_items) == 2
        assert len(reddit_items) == 1
        assert len(arxiv_items) == 1


# ========== RelevanceFilter ==========

class TestRelevanceFilter:

    @patch("agents.analysts.filter.RelevanceFilter._run_llm_filter")
    def test_filter_stores_analysis(self, mock_llm, db, event_bus):
        from agents.analysts.filter import RelevanceFilter

        ids = _seed_items(db, count=3)
        mock_llm.return_value = [
            {"index": 0, "novel": True, "ai_relevant": True,
             "category": "framework", "interest_score": 8,
             "summary": "Great new framework", "deep_dive": True},
            {"index": 1, "novel": True, "ai_relevant": True,
             "category": "tool", "interest_score": 6,
             "summary": "Useful dev tool", "deep_dive": False},
            {"index": 2, "novel": False, "ai_relevant": True,
             "category": "tool", "interest_score": 3,
             "summary": "Not novel", "deep_dive": False},
        ]

        ctx = AgentContext(
            db=db, event_bus=event_bus,
            config={"scoring": {"digest_size": 15, "filter_pool_size": 30}},
        )

        filt = RelevanceFilter()
        result = filt.execute(ctx)

        assert result.success is True
        # Only 2 items pass (index 2 is not novel)
        assert result.data["analyzed_count"] == 2

        # Verify item_analysis was written
        with db.connect() as conn:
            analyses = conn.execute("SELECT * FROM item_analysis").fetchall()
        assert len(analyses) == 2
        assert all(a["analysis_type"] == "filter" for a in analyses)

    @patch("agents.analysts.filter.RelevanceFilter._run_llm_filter")
    def test_filter_creates_topics(self, mock_llm, db, event_bus):
        from agents.analysts.filter import RelevanceFilter

        _seed_items(db, count=2)
        mock_llm.return_value = [
            {"index": 0, "novel": True, "ai_relevant": True,
             "category": "framework", "interest_score": 9,
             "summary": "A framework", "deep_dive": True},
            {"index": 1, "novel": True, "ai_relevant": True,
             "category": "dataset", "interest_score": 7,
             "summary": "A dataset", "deep_dive": False},
        ]

        ctx = AgentContext(
            db=db, event_bus=event_bus,
            config={"scoring": {}},
        )

        filt = RelevanceFilter()
        filt.execute(ctx)

        # Verify topics were created
        with db.connect() as conn:
            topics = conn.execute("SELECT * FROM topics").fetchall()
        topic_names = {t["name"] for t in topics}
        assert "framework" in topic_names
        assert "dataset" in topic_names

        # Verify item_topics linkage
        with db.connect() as conn:
            item_topics = conn.execute("SELECT * FROM item_topics").fetchall()
        assert len(item_topics) == 2
        # confidence should be interest_score / 10
        confidences = sorted([it["confidence"] for it in item_topics])
        assert confidences == [0.7, 0.9]

    @patch("agents.analysts.filter.RelevanceFilter._run_llm_filter")
    def test_filter_emits_event(self, mock_llm, db, event_bus):
        from agents.analysts.filter import RelevanceFilter

        _seed_items(db, count=1)
        mock_llm.return_value = [
            {"index": 0, "novel": True, "ai_relevant": True,
             "category": "tool", "interest_score": 5,
             "summary": "A tool", "deep_dive": False},
        ]

        received = []
        event_bus.subscribe("analysis_complete", lambda d: received.append(d))

        ctx = AgentContext(
            db=db, event_bus=event_bus,
            config={"scoring": {}},
        )

        filt = RelevanceFilter()
        filt.execute(ctx)

        assert len(received) == 1
        assert received[0]["analyzed_count"] == 1

    def test_filter_fallback_on_llm_failure(self, db, event_bus):
        from agents.analysts.filter import RelevanceFilter

        _seed_items(db, count=3)

        ctx = AgentContext(
            db=db, event_bus=event_bus,
            config={"scoring": {"digest_size": 15}},
        )

        filt = RelevanceFilter()
        # Patch _run_llm_filter to raise an exception
        with patch.object(filt, "_run_llm_filter", side_effect=RuntimeError("LLM down")):
            result = filt.execute(ctx)

        assert result.success is True
        # Fallback should still analyze items
        assert result.data["analyzed_count"] > 0

        # Verify fallback items stored in DB
        with db.connect() as conn:
            analyses = conn.execute("SELECT * FROM item_analysis").fetchall()
        assert len(analyses) > 0

    @patch("agents.analysts.filter.RelevanceFilter._run_llm_filter")
    def test_filter_no_items(self, mock_llm, db, event_bus):
        from agents.analysts.filter import RelevanceFilter

        # No items in DB
        ctx = AgentContext(
            db=db, event_bus=event_bus,
            config={"scoring": {}},
        )

        filt = RelevanceFilter()
        result = filt.execute(ctx)

        assert result.success is True
        assert "No items to filter" in result.message
        mock_llm.assert_not_called()


# ========== DotConnector ==========

class TestDotConnector:

    @patch("claude_cli.call_claude_json")
    def test_connector_stores_connections(self, mock_claude, db, event_bus):
        from agents.analysts.connector import DotConnector

        ids = _seed_mixed_source_items(db)

        mock_claude.return_value = {
            "connections": [
                {"item_a_index": 0, "item_b_index": 1,
                 "relationship": "same_topic",
                 "description": "Both discuss Alpha Framework"},
                {"item_a_index": 2, "item_b_index": 3,
                 "relationship": "builds_on",
                 "description": "Beta Tool uses the novel attention mechanism"},
            ]
        }

        ctx = AgentContext(
            db=db, event_bus=event_bus,
            config={},
        )

        connector = DotConnector()
        result = connector.execute(ctx)

        assert result.success is True
        assert result.data["connections_count"] == 2

        # Verify connections in DB
        with db.connect() as conn:
            connections = conn.execute("SELECT * FROM item_connections").fetchall()
        assert len(connections) == 2
        rels = {c["relationship"] for c in connections}
        assert "same_topic" in rels
        assert "builds_on" in rels

    @patch("claude_cli.call_claude_json")
    def test_connector_filters_invalid_indices(self, mock_claude, db, event_bus):
        from agents.analysts.connector import DotConnector

        _seed_items(db, count=3)

        mock_claude.return_value = {
            "connections": [
                {"item_a_index": 0, "item_b_index": 1,
                 "relationship": "competes_with",
                 "description": "Valid connection"},
                {"item_a_index": 99, "item_b_index": 0,
                 "relationship": "same_topic",
                 "description": "Invalid index should be skipped"},
                {"item_a_index": -1, "item_b_index": 2,
                 "relationship": "same_topic",
                 "description": "Negative index should be skipped"},
            ]
        }

        ctx = AgentContext(db=db, event_bus=event_bus, config={})

        connector = DotConnector()
        result = connector.execute(ctx)

        assert result.success is True
        # Only 1 valid connection
        assert result.data["connections_count"] == 1

        with db.connect() as conn:
            connections = conn.execute("SELECT * FROM item_connections").fetchall()
        assert len(connections) == 1
        assert connections[0]["relationship"] == "competes_with"

    @patch("claude_cli.call_claude_json")
    def test_connector_normalizes_invalid_relationship(self, mock_claude, db, event_bus):
        from agents.analysts.connector import DotConnector

        _seed_items(db, count=2)

        mock_claude.return_value = {
            "connections": [
                {"item_a_index": 0, "item_b_index": 1,
                 "relationship": "invented_relationship_type",
                 "description": "Should fall back to same_topic"},
            ]
        }

        ctx = AgentContext(db=db, event_bus=event_bus, config={})

        connector = DotConnector()
        result = connector.execute(ctx)

        assert result.success is True
        assert result.data["connections_count"] == 1

        with db.connect() as conn:
            connections = conn.execute("SELECT * FROM item_connections").fetchall()
        assert connections[0]["relationship"] == "same_topic"

    def test_connector_not_enough_items(self, db, event_bus):
        from agents.analysts.connector import DotConnector

        # Only 1 item - need at least 2
        _seed_items(db, count=1)

        ctx = AgentContext(db=db, event_bus=event_bus, config={})

        connector = DotConnector()
        result = connector.execute(ctx)

        assert result.success is True
        assert "Not enough items" in result.message

    @patch("claude_cli.call_claude_json")
    def test_connector_handles_llm_failure(self, mock_claude, db, event_bus):
        from agents.analysts.connector import DotConnector

        _seed_items(db, count=3)
        mock_claude.side_effect = RuntimeError("LLM unreachable")

        ctx = AgentContext(db=db, event_bus=event_bus, config={})

        connector = DotConnector()
        result = connector.execute(ctx)

        assert result.success is False
        assert "LLM unreachable" in result.message

        # No connections should be stored
        with db.connect() as conn:
            connections = conn.execute("SELECT * FROM item_connections").fetchall()
        assert len(connections) == 0
