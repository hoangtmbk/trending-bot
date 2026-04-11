"""Integration test: wire up DB + agents + orchestrator and process a task end-to-end."""
import json
import pytest
from pathlib import Path
from db.database import Database
from db.queries import enqueue_task, get_item_by_url, get_score_history
from orchestrator.app import Application
from agents.base import BaseAgent, AgentContext, AgentResult


class FakeScoutAgent(BaseAgent):
    """Simulates a scout agent that discovers items and writes to DB."""
    name = "fake_scout"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        from db.queries import upsert_item, snapshot_score
        item_id = upsert_item(
            ctx.db,
            url="https://github.com/test/repo",
            title="Test Repo",
            source="github",
            description="A test repository",
            raw_metrics={"stars": 500, "forks": 50},
            momentum_score=0.85,
            normalized_score=75.0,
        )
        snapshot_score(
            ctx.db, item_id,
            momentum_score=0.85,
            normalized_score=75.0,
            raw_metrics={"stars": 500},
        )
        ctx.emit("items_updated", {"source": "github", "count": 1, "new_count": 1})
        return AgentResult(success=True, message="Discovered 1 item",
                           data={"item_ids": [item_id]})


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


def test_full_stack_task_processing(db):
    app = Application(db=db, config={})
    app.register_agent(FakeScoutAgent())

    # Track events
    events_received = []
    app.on_event("items_updated", lambda d: events_received.append(d))

    # Enqueue a scout run
    enqueue_task(db, agent_type="fake_scout", payload={})

    # Process it
    count = app.dispatcher.process_all()
    assert count == 1

    # Verify item was written to DB
    item = get_item_by_url(db, "https://github.com/test/repo")
    assert item is not None
    assert item["title"] == "Test Repo"
    assert item["source"] == "github"
    assert item["momentum_score"] == 0.85

    # Verify score history
    history = get_score_history(db, item["id"])
    assert len(history) == 1
    assert history[0]["momentum_score"] == 0.85

    # Verify event was emitted
    assert len(events_received) == 1
    assert events_received[0]["source"] == "github"


def test_event_triggers_downstream_agent(db):
    """Test that events can wire agents together."""
    app = Application(db=db, config={})
    app.register_agent(FakeScoutAgent())

    # Track what happens when items_updated fires
    downstream_runs = []

    class FakeAnalystAgent(BaseAgent):
        name = "fake_analyst"
        schedule = "on_demand"

        def execute(self, ctx: AgentContext) -> AgentResult:
            downstream_runs.append(True)
            return AgentResult(success=True, message="Analyzed")

    analyst = FakeAnalystAgent()
    app.register_agent(analyst)

    # Wire: when items_updated fires, enqueue analyst
    def on_items_updated(data):
        enqueue_task(db, agent_type="fake_analyst",
                     payload={"triggered_by": data["source"]})

    app.on_event("items_updated", on_items_updated)

    # Enqueue scout, process it (fires event, which enqueues analyst)
    enqueue_task(db, agent_type="fake_scout", payload={})
    app.dispatcher.process_all()  # processes scout + analyst

    assert len(downstream_runs) == 1


def test_multiple_scouts_accumulate_items(db):
    """Multiple scout runs for the same item should update, not duplicate."""
    app = Application(db=db, config={})
    app.register_agent(FakeScoutAgent())

    enqueue_task(db, agent_type="fake_scout", payload={})
    enqueue_task(db, agent_type="fake_scout", payload={})
    app.dispatcher.process_all()

    item = get_item_by_url(db, "https://github.com/test/repo")
    assert item["times_seen"] == 2

    history = get_score_history(db, item["id"])
    assert len(history) == 2
