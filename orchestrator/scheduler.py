from __future__ import annotations
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from db.database import Database
from orchestrator.events import EventBus
from agents.base import BaseAgent, AgentContext

logger = logging.getLogger(__name__)


class AgentScheduler:
    def __init__(self, db: Database, event_bus: EventBus, config: dict):
        self.db = db
        self.event_bus = event_bus
        self.config = config
        self.agents: dict[str, BaseAgent] = {}
        self.scheduler = BackgroundScheduler()

    def register(self, agent: BaseAgent) -> None:
        self.agents[agent.name] = agent
        if agent.schedule != "on_demand":
            trigger = CronTrigger.from_crontab(agent.schedule)
            self.scheduler.add_job(
                self.run_agent,
                trigger=trigger,
                id=agent.name,
                args=[agent.name],
                replace_existing=True,
            )
            logger.info(f"Scheduled agent '{agent.name}' with cron '{agent.schedule}'")
        else:
            logger.info(f"Registered on-demand agent '{agent.name}'")

    def run_agent(self, name: str) -> None:
        agent = self.agents[name]
        ctx = AgentContext(db=self.db, event_bus=self.event_bus, config=self.config)
        agent.run(ctx)

    def start(self) -> None:
        self.scheduler.start()
        logger.info("Agent scheduler started")

    def stop(self) -> None:
        self.scheduler.shutdown(wait=True)
        logger.info("Agent scheduler stopped")
