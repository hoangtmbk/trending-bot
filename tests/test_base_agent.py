import pytest
from pathlib import Path
from db.database import Database
from orchestrator.events import EventBus
from agents.base import BaseAgent, AgentContext, AgentResult


class CountingAgent(BaseAgent):
    name = "counter"
    schedule = "*/5 * * * *"

    def __init__(self):
        super().__init__()
        self.run_count = 0

    def execute(self, ctx: AgentContext) -> AgentResult:
        self.run_count += 1
        return AgentResult(success=True, message=f"Run #{self.run_count}",
                           data={"count": self.run_count})


class FailingAgent(BaseAgent):
    name = "failer"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        raise RuntimeError("Something broke")


class EventEmittingAgent(BaseAgent):
    name = "emitter"
    schedule = "0 */4 * * *"

    def execute(self, ctx: AgentContext) -> AgentResult:
        ctx.emit("items_updated", {"source": "test", "count": 5})
        return AgentResult(success=True, message="Emitted event")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def event_bus():
    return EventBus()


def test_agent_has_name():
    agent = CountingAgent()
    assert agent.name == "counter"


def test_agent_has_schedule():
    agent = CountingAgent()
    assert agent.schedule == "*/5 * * * *"


def test_agent_run_returns_result(db, event_bus):
    agent = CountingAgent()
    ctx = AgentContext(db=db, event_bus=event_bus, config={})
    result = agent.run(ctx)
    assert result.success is True
    assert result.data == {"count": 1}


def test_agent_run_handles_exception(db, event_bus):
    agent = FailingAgent()
    ctx = AgentContext(db=db, event_bus=event_bus, config={})
    result = agent.run(ctx)
    assert result.success is False
    assert "Something broke" in result.message


def test_agent_can_emit_events(db, event_bus):
    received = []
    event_bus.subscribe("items_updated", lambda d: received.append(d))
    agent = EventEmittingAgent()
    ctx = AgentContext(db=db, event_bus=event_bus, config={})
    agent.run(ctx)
    assert len(received) == 1
    assert received[0] == {"source": "test", "count": 5}


def test_agent_run_count(db, event_bus):
    agent = CountingAgent()
    ctx = AgentContext(db=db, event_bus=event_bus, config={})
    agent.run(ctx)
    agent.run(ctx)
    assert agent.run_count == 2


def test_on_demand_schedule():
    agent = FailingAgent()
    assert agent.schedule == "on_demand"
