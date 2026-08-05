import json
import pytest
from unittest.mock import patch, MagicMock
from db.database import Database
from db.queries import upsert_item, get_item_by_id
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


def _seed_item(db, url="https://github.com/test/agentkit", title="AgentKit v2",
               source="github", description="Multi-agent framework"):
    """Insert a single test item and return its ID."""
    return upsert_item(
        db, url=url, title=title, source=source, description=description,
        raw_metrics={"stargazers_count": 500}, momentum_score=80.0, normalized_score=90.0,
    )


def _seed_topic_with_interest(db, topic_name="framework"):
    """Create a topic with a user interest and return the topic ID."""
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT INTO topics (name, description, source, created_at, is_active) "
            "VALUES (?, '', 'system', datetime('now'), 1)",
            (topic_name,),
        )
        topic_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO user_interests (topic_id, weight, source, updated_at) "
            "VALUES (?, 1.0, 'explicit', datetime('now'))",
            (topic_id,),
        )
        conn.commit()
    return topic_id


def _link_item_to_topic(db, item_id, topic_id):
    """Link an item to a topic via item_topics."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO item_topics (item_id, topic_id, confidence) VALUES (?, ?, 1.0)",
            (item_id, topic_id),
        )
        conn.commit()


def _add_deep_dive_analysis(db, item_id, competitors=None):
    """Insert a deep dive analysis for an item."""
    content = {
        "what_it_is": "A framework",
        "why_trending": "Growing fast",
        "competitors": competitors or [],
    }
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO item_analysis (item_id, analysis_type, created_at, content, prompt_version) "
            "VALUES (?, 'deep_dive', datetime('now'), ?, 'v1')",
            (item_id, json.dumps(content)),
        )
        conn.commit()


def _bookmark_item(db, item_id):
    """Create a bookmark user action."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO user_actions (item_id, action, created_at) VALUES (?, 'bookmarked', datetime('now'))",
            (item_id,),
        )
        conn.commit()


# ========== DeepDiver ==========

class TestDeepDiver:

    @patch("claude_cli.call_claude_json")
    @patch("agents.researchers.deep_diver.DeepDiver._gather_material")
    def test_deep_dive_success(self, mock_gather, mock_claude, db, event_bus):
        from agents.researchers.deep_diver import DeepDiver

        item_id = _seed_item(db)
        mock_gather.return_value = "### README\nSome readme content"
        mock_claude.return_value = {
            "what_it_is": "An agent framework",
            "why_trending": "Community excitement",
            "pain_point": "Lack of orchestration",
            "gap_analysis": "Missing monitoring",
            "competitors": ["LangChain", "CrewAI"],
            "app_idea": "Build a visual agent builder",
            "feasibility": {"effort": "2 weeks", "market": "growing", "competition": "moderate"},
        }

        received = []
        event_bus.subscribe("research_complete", lambda d: received.append(d))

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={"item_id": item_id})
        diver = DeepDiver()
        result = diver.execute(ctx)

        assert result.success is True
        assert "Deep dive completed" in result.message
        assert result.data["item_id"] == item_id
        assert result.data["slug"] == "agentkit-v2"

        # Verify stored in DB
        with db.connect() as conn:
            analyses = conn.execute(
                "SELECT * FROM item_analysis WHERE item_id=? AND analysis_type='deep_dive'",
                (item_id,),
            ).fetchall()
        assert len(analyses) == 1
        stored = json.loads(analyses[0]["content"])
        assert stored["what_it_is"] == "An agent framework"

        # Verify event emitted
        assert len(received) == 1
        assert received[0]["item_id"] == item_id
        assert received[0]["type"] == "deep_dive"

    @patch("claude_cli.call_claude_json")
    @patch("agents.researchers.deep_diver.DeepDiver._gather_material")
    def test_deep_dive_allows_more_than_the_default_300s(self, mock_gather, mock_claude,
                                                         db, event_bus):
        """Deep dives run 162s at p50 and their tail ran past the old 300s cap,
        which killed ~13% of them at exactly 300s and discarded the work."""
        from agents.researchers.deep_diver import DeepDiver

        item_id = _seed_item(db)
        mock_gather.return_value = "### README\nSome readme content"
        mock_claude.return_value = {"what_it_is": "A framework", "why_trending": "Buzz"}

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={"item_id": item_id})
        DeepDiver().execute(ctx)

        assert mock_claude.call_args.kwargs["timeout"] == 600

    def test_deep_dive_no_item_id(self, db, event_bus):
        from agents.researchers.deep_diver import DeepDiver

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={})
        diver = DeepDiver()
        result = diver.execute(ctx)

        assert result.success is False
        assert "No item_id" in result.message

    def test_deep_dive_item_not_found(self, db, event_bus):
        from agents.researchers.deep_diver import DeepDiver

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={"item_id": 9999})
        diver = DeepDiver()
        result = diver.execute(ctx)

        assert result.success is False
        assert "not found" in result.message

    @patch("claude_cli.call_claude_json")
    @patch("agents.researchers.deep_diver.DeepDiver._gather_material")
    def test_deep_dive_skips_existing(self, mock_gather, mock_claude, db, event_bus):
        from agents.researchers.deep_diver import DeepDiver

        item_id = _seed_item(db)
        _add_deep_dive_analysis(db, item_id)

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={"item_id": item_id})
        diver = DeepDiver()
        result = diver.execute(ctx)

        assert result.success is True
        assert "already exists" in result.message
        mock_claude.assert_not_called()
        mock_gather.assert_not_called()

    @patch("claude_cli.call_claude_json")
    @patch("agents.researchers.deep_diver.DeepDiver._gather_material")
    def test_deep_dive_uses_filter_summary(self, mock_gather, mock_claude, db, event_bus):
        from agents.researchers.deep_diver import DeepDiver

        item_id = _seed_item(db)

        # Add a filter analysis with a summary
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO item_analysis (item_id, analysis_type, created_at, content, prompt_version) "
                "VALUES (?, 'filter', datetime('now'), ?, 'v1')",
                (item_id, json.dumps({"summary": "Impressive new agent framework"})),
            )
            conn.commit()

        mock_gather.return_value = "No additional material available."
        mock_claude.return_value = {"what_it_is": "Framework", "why_trending": "Buzz"}

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={"item_id": item_id})
        diver = DeepDiver()
        diver.execute(ctx)

        # Verify the prompt included the filter summary
        call_args = mock_claude.call_args[0][0]
        assert "Impressive new agent framework" in call_args

    @patch("agents.researchers.deep_diver.DeepDiver._gather_material")
    def test_deep_dive_claude_failure(self, mock_gather, db, event_bus):
        from agents.researchers.deep_diver import DeepDiver

        item_id = _seed_item(db)
        mock_gather.return_value = "Some material"

        with patch("claude_cli.call_claude_json", side_effect=RuntimeError("API timeout")):
            ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={"item_id": item_id})
            diver = DeepDiver()
            result = diver.execute(ctx)

        assert result.success is False
        assert "Claude CLI failed" in result.message

        # No analysis should be stored
        with db.connect() as conn:
            analyses = conn.execute(
                "SELECT * FROM item_analysis WHERE item_id=?", (item_id,)
            ).fetchall()
        assert len(analyses) == 0


class TestDeepDiverSlugify:

    def test_slugify(self):
        from agents.researchers.deep_diver import _slugify

        assert _slugify("AgentKit v2") == "agentkit-v2"
        assert _slugify("Hello World!!! @#$") == "hello-world"
        assert _slugify("a" * 100) == "a" * 60


# ========== TopicTracker ==========

class TestTopicTracker:

    @patch("claude_cli.call_claude_json")
    def test_topic_report_created(self, mock_claude, db, event_bus):
        from agents.researchers.topic_tracker import TopicTracker

        topic_id = _seed_topic_with_interest(db, "framework")
        item_id = _seed_item(db)
        _link_item_to_topic(db, item_id, topic_id)

        mock_claude.return_value = {
            "trajectory": "accelerating",
            "summary": "Framework space is heating up",
            "key_developments": ["New entrant AgentKit"],
            "watch_for": "Enterprise adoption signals",
        }

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={"days": 30})
        tracker = TopicTracker()
        result = tracker.execute(ctx)

        assert result.success is True
        assert result.data["reports_count"] == 1

        # Verify stored in DB
        with db.connect() as conn:
            analyses = conn.execute(
                "SELECT * FROM item_analysis WHERE analysis_type='topic_report'"
            ).fetchall()
        assert len(analyses) == 1
        stored = json.loads(analyses[0]["content"])
        assert stored["topic"] == "framework"
        assert stored["trajectory"] == "accelerating"

    def test_topic_tracker_no_tracked_topics(self, db, event_bus):
        from agents.researchers.topic_tracker import TopicTracker

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={})
        tracker = TopicTracker()
        result = tracker.execute(ctx)

        assert result.success is True
        assert "No tracked topics" in result.message

    @patch("claude_cli.call_claude_json")
    def test_topic_tracker_skips_empty_topics(self, mock_claude, db, event_bus):
        from agents.researchers.topic_tracker import TopicTracker

        # Create a topic with interest but no linked items
        _seed_topic_with_interest(db, "empty_topic")

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={"days": 7})
        tracker = TopicTracker()
        result = tracker.execute(ctx)

        assert result.success is True
        assert result.data["reports_count"] == 0
        mock_claude.assert_not_called()

    @patch("claude_cli.call_claude_json")
    def test_topic_tracker_handles_llm_failure(self, mock_claude, db, event_bus):
        from agents.researchers.topic_tracker import TopicTracker

        topic_id = _seed_topic_with_interest(db, "framework")
        item_id = _seed_item(db)
        _link_item_to_topic(db, item_id, topic_id)

        mock_claude.side_effect = RuntimeError("LLM down")

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={"days": 30})
        tracker = TopicTracker()
        result = tracker.execute(ctx)

        # Should succeed overall but create 0 reports
        assert result.success is True
        assert result.data["reports_count"] == 0


# ========== CompetitorWatcher ==========

class TestCompetitorWatcher:

    def test_competitor_connections_created(self, db, event_bus):
        from agents.researchers.competitor_watch import CompetitorWatcher

        # Item A is bookmarked and has a deep dive listing "Beta Tool" as a competitor
        item_a = _seed_item(db, url="https://github.com/test/alpha", title="Alpha Framework")
        item_b = _seed_item(db, url="https://github.com/test/beta", title="Beta Tool")
        _bookmark_item(db, item_a)
        _add_deep_dive_analysis(db, item_a, competitors=["Beta Tool"])

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={})
        watcher = CompetitorWatcher()
        result = watcher.execute(ctx)

        assert result.success is True
        assert result.data["watched_count"] == 1

        # Verify connection stored
        with db.connect() as conn:
            connections = conn.execute("SELECT * FROM item_connections").fetchall()
        assert len(connections) == 1
        assert connections[0]["item_a_id"] == item_a
        assert connections[0]["item_b_id"] == item_b
        assert connections[0]["relationship"] == "competes_with"

    def test_competitor_no_bookmarks(self, db, event_bus):
        from agents.researchers.competitor_watch import CompetitorWatcher

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={})
        watcher = CompetitorWatcher()
        result = watcher.execute(ctx)

        assert result.success is True
        assert "No bookmarked items" in result.message

    def test_competitor_no_deep_dive(self, db, event_bus):
        from agents.researchers.competitor_watch import CompetitorWatcher

        item_id = _seed_item(db)
        _bookmark_item(db, item_id)
        # No deep dive analysis added

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={})
        watcher = CompetitorWatcher()
        result = watcher.execute(ctx)

        assert result.success is True
        assert result.data["watched_count"] == 0

    def test_competitor_skips_self_match(self, db, event_bus):
        from agents.researchers.competitor_watch import CompetitorWatcher

        # Item lists itself as a competitor (edge case)
        item_id = _seed_item(db, url="https://github.com/test/alpha", title="Alpha Framework")
        _bookmark_item(db, item_id)
        _add_deep_dive_analysis(db, item_id, competitors=["Alpha Framework"])

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={})
        watcher = CompetitorWatcher()
        result = watcher.execute(ctx)

        # No connections should be created (self-match filtered out)
        with db.connect() as conn:
            connections = conn.execute("SELECT * FROM item_connections").fetchall()
        assert len(connections) == 0

    def test_competitor_no_duplicate_connections(self, db, event_bus):
        from agents.researchers.competitor_watch import CompetitorWatcher

        item_a = _seed_item(db, url="https://github.com/test/alpha", title="Alpha Framework")
        item_b = _seed_item(db, url="https://github.com/test/beta", title="Beta Tool")
        _bookmark_item(db, item_a)
        _add_deep_dive_analysis(db, item_a, competitors=["Beta Tool"])

        ctx = AgentContext(db=db, event_bus=event_bus, config={}, payload={})
        watcher = CompetitorWatcher()

        # Run twice
        watcher.execute(ctx)
        watcher.execute(ctx)

        # Should have only 1 connection, not duplicated
        with db.connect() as conn:
            connections = conn.execute("SELECT * FROM item_connections").fetchall()
        assert len(connections) == 1
