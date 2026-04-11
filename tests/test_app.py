import pytest
import time
import threading
from pathlib import Path
from db.database import Database
from db.queries import enqueue_task
from orchestrator.app import Application
from agents.base import BaseAgent, AgentContext, AgentResult


class PingAgent(BaseAgent):
    name = "ping"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(success=True, message="pong", data={"pong": True})


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def app(db):
    application = Application(db=db, config={})
    application.register_agent(PingAgent())
    return application


def test_application_creates_event_bus(app):
    assert app.event_bus is not None


def test_application_creates_scheduler(app):
    assert app.scheduler is not None


def test_application_creates_dispatcher(app):
    assert app.dispatcher is not None


def test_application_registers_agent_in_both(app):
    assert "ping" in app.scheduler.agents
    assert "ping" in app.dispatcher.agents


def test_application_process_tasks(app, db):
    enqueue_task(db, agent_type="ping", payload={})
    count = app.dispatcher.process_all()
    assert count == 1


def test_application_subscribe_to_events(app):
    received = []
    app.on_event("test_event", lambda d: received.append(d))
    app.event_bus.emit("test_event", {"x": 1})
    assert len(received) == 1
