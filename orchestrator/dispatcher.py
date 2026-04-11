from __future__ import annotations
import json
import logging

from db.database import Database
from db.queries import claim_next_task, complete_task, fail_task
from orchestrator.events import EventBus
from agents.base import BaseAgent, AgentContext

logger = logging.getLogger(__name__)


class TaskDispatcher:
    def __init__(self, db: Database, event_bus: EventBus, config: dict):
        self.db = db
        self.event_bus = event_bus
        self.config = config
        self.agents: dict[str, BaseAgent] = {}

    def register_agent(self, agent: BaseAgent) -> None:
        self.agents[agent.name] = agent

    def process_one(self) -> bool:
        task = claim_next_task(self.db)
        if not task:
            return False

        agent_type = task["agent_type"]
        task_id = task["id"]

        agent = self.agents.get(agent_type)
        if not agent:
            fail_task(self.db, task_id, f"Unknown agent type: {agent_type}")
            return True

        payload = json.loads(task["payload"]) if task["payload"] else {}
        ctx = AgentContext(db=self.db, event_bus=self.event_bus, config=self.config, payload=payload)
        result = agent.run(ctx)

        if result.success:
            complete_task(self.db, task_id, result=result.data)
        else:
            fail_task(self.db, task_id, error=result.message)

        return True

    def process_all(self) -> int:
        count = 0
        while self.process_one():
            count += 1
        return count
