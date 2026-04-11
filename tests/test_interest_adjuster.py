import json
import pytest
from unittest.mock import patch
from db.database import Database
from db.queries import upsert_item
from orchestrator.events import EventBus
from agents.base import AgentContext
from agents.analysts.interest_adjuster import InterestAdjuster
from memory.interests import set_interest, get_interest_profile


# ---------- fixtures ----------

@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def event_bus():
    return EventBus()


def _seed_item(db, title="Test Item", url="https://example.com/item"):
    return upsert_item(
        db, url=url, title=title, source="github",
        description="Desc", raw_metrics={"stars": 42},
    )


def _add_user_action(db, item_id, action="bookmarked"):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO user_actions (item_id, action, created_at) "
            "VALUES (?, ?, datetime('now'))",
            (item_id, action),
        )
        conn.commit()


# ========== InterestAdjuster Tests ==========

class TestInterestAdjuster:

    @patch("claude_cli.call_claude_json")
    def test_applies_adjustments(self, mock_claude, db, event_bus):
        # Set up profile and actions
        set_interest(db, "ml-frameworks", 1.5)
        set_interest(db, "datasets", 1.0)

        item_id = _seed_item(db, title="New ML Tool", url="https://example.com/1")
        _add_user_action(db, item_id, "bookmarked")

        mock_claude.return_value = {
            "adjustments": [
                {"topic": "ml-frameworks", "delta": 0.2, "reason": "User bookmarked ML item"},
                {"topic": "datasets", "delta": -0.1, "reason": "No interest shown"},
            ]
        }

        ctx = AgentContext(db=db, event_bus=event_bus, config={})
        adjuster = InterestAdjuster()
        result = adjuster.execute(ctx)

        assert result.success is True
        assert result.data["adjustments_count"] == 2

        profile = get_interest_profile(db)
        assert profile["ml-frameworks"] == pytest.approx(1.7)
        assert profile["datasets"] == pytest.approx(0.9)

    def test_no_actions_returns_early(self, db, event_bus):
        # Profile exists but no actions
        set_interest(db, "topic-a", 1.0)

        ctx = AgentContext(db=db, event_bus=event_bus, config={})
        adjuster = InterestAdjuster()
        result = adjuster.execute(ctx)

        assert result.success is True
        assert "No recent actions" in result.message

    @patch("claude_cli.call_claude_json")
    def test_caps_deltas(self, mock_claude, db, event_bus):
        set_interest(db, "over-adjusted", 1.0)

        item_id = _seed_item(db)
        _add_user_action(db, item_id)

        # LLM returns delta > 0.3 — should be capped
        mock_claude.return_value = {
            "adjustments": [
                {"topic": "over-adjusted", "delta": 0.9, "reason": "Exaggerated boost"},
            ]
        }

        ctx = AgentContext(db=db, event_bus=event_bus, config={})
        adjuster = InterestAdjuster()
        result = adjuster.execute(ctx)

        assert result.success is True
        assert result.data["adjustments_count"] == 1

        profile = get_interest_profile(db)
        # 1.0 + 0.3 (capped from 0.9) = 1.3
        assert profile["over-adjusted"] == pytest.approx(1.3)

    def test_no_profile_returns_early(self, db, event_bus):
        ctx = AgentContext(db=db, event_bus=event_bus, config={})
        adjuster = InterestAdjuster()
        result = adjuster.execute(ctx)

        assert result.success is True
        assert "No interest profile" in result.message

    @patch("claude_cli.call_claude_json")
    def test_llm_failure(self, mock_claude, db, event_bus):
        set_interest(db, "topic-x", 1.0)
        item_id = _seed_item(db)
        _add_user_action(db, item_id)

        mock_claude.side_effect = RuntimeError("LLM down")

        ctx = AgentContext(db=db, event_bus=event_bus, config={})
        adjuster = InterestAdjuster()
        result = adjuster.execute(ctx)

        assert result.success is False
        assert "LLM down" in result.message
