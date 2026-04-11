import json
import pytest
from pathlib import Path
from db.database import Database
from db.queries import enqueue_task, get_pending_tasks
from orchestrator.events import EventBus
from orchestrator.dispatcher import TaskDispatcher
from agents.base import BaseAgent, AgentContext, AgentResult


class EchoAgent(BaseAgent):
    name = "echo"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(success=True, message="echoed",
                           data={"echo": True})


class BrokenAgent(BaseAgent):
    name = "broken"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        raise RuntimeError("Agent crashed")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def dispatcher(db, event_bus):
    d = TaskDispatcher(db=db, event_bus=event_bus, config={})
    d.register_agent(EchoAgent())
    d.register_agent(BrokenAgent())
    return d


def test_register_agent(dispatcher):
    assert "echo" in dispatcher.agents
    assert "broken" in dispatcher.agents


def test_process_one_task_success(dispatcher, db):
    enqueue_task(db, agent_type="echo", payload={"msg": "hello"})
    processed = dispatcher.process_one()
    assert processed is True
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM task_queue WHERE id=1").fetchone()
    assert row["status"] == "completed"
    assert json.loads(row["result"]) == {"echo": True}


def test_process_one_task_failure(dispatcher, db):
    enqueue_task(db, agent_type="broken", payload={})
    processed = dispatcher.process_one()
    assert processed is True
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM task_queue WHERE id=1").fetchone()
    assert row["status"] == "failed"
    assert "Agent crashed" in row["error"]


def test_process_one_returns_false_when_empty(dispatcher):
    processed = dispatcher.process_one()
    assert processed is False


def test_process_unknown_agent_type(dispatcher, db):
    enqueue_task(db, agent_type="nonexistent", payload={})
    processed = dispatcher.process_one()
    assert processed is True
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM task_queue WHERE id=1").fetchone()
    assert row["status"] == "failed"
    assert "Unknown agent type" in row["error"]


def test_process_all_drains_queue(dispatcher, db):
    enqueue_task(db, agent_type="echo", payload={"a": 1})
    enqueue_task(db, agent_type="echo", payload={"b": 2})
    enqueue_task(db, agent_type="echo", payload={"c": 3})
    count = dispatcher.process_all()
    assert count == 3
    pending = get_pending_tasks(db)
    assert len(pending) == 0
