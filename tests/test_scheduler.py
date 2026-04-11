import pytest
from unittest.mock import MagicMock, patch
from db.database import Database
from orchestrator.events import EventBus
from orchestrator.scheduler import AgentScheduler
from agents.base import BaseAgent, AgentContext, AgentResult


class ScheduledAgent(BaseAgent):
    name = "scheduled"
    schedule = "*/5 * * * *"
    run_count = 0

    def execute(self, ctx: AgentContext) -> AgentResult:
        ScheduledAgent.run_count += 1
        return AgentResult(success=True, message="done")


class OnDemandAgent(BaseAgent):
    name = "on_demand_agent"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(success=True, message="done")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def scheduler(db, event_bus):
    return AgentScheduler(db=db, event_bus=event_bus, config={})


def test_register_scheduled_agent(scheduler):
    agent = ScheduledAgent()
    scheduler.register(agent)
    assert "scheduled" in scheduler.agents


def test_register_on_demand_agent_skips_scheduling(scheduler):
    agent = OnDemandAgent()
    scheduler.register(agent)
    assert "on_demand_agent" in scheduler.agents
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) == 0


def test_register_scheduled_agent_adds_job(scheduler):
    agent = ScheduledAgent()
    scheduler.register(agent)
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "scheduled"


def test_run_agent_directly(scheduler, db, event_bus):
    ScheduledAgent.run_count = 0
    agent = ScheduledAgent()
    scheduler.register(agent)
    scheduler.run_agent("scheduled")
    assert ScheduledAgent.run_count == 1


def test_run_agent_unknown_name(scheduler):
    with pytest.raises(KeyError):
        scheduler.run_agent("nonexistent")
