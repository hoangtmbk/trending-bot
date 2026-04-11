from __future__ import annotations
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from db.database import Database
from orchestrator.events import EventBus

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    db: Database
    event_bus: EventBus
    config: dict

    def emit(self, event: str, data: dict) -> None:
        self.event_bus.emit(event, data)


@dataclass
class AgentResult:
    success: bool
    message: str = ""
    data: dict = field(default_factory=dict)


class BaseAgent(ABC):
    name: str = ""
    schedule: str = "on_demand"
    timeout: int = 300

    def __init__(self):
        if not self.name:
            self.name = self.__class__.__name__.lower()

    @abstractmethod
    def execute(self, ctx: AgentContext) -> AgentResult:
        ...

    def run(self, ctx: AgentContext) -> AgentResult:
        logger.info(f"Agent '{self.name}' starting")
        start = time.monotonic()
        try:
            result = self.execute(ctx)
            elapsed = time.monotonic() - start
            logger.info(f"Agent '{self.name}' completed in {elapsed:.1f}s: {result.message}")
            return result
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.error(f"Agent '{self.name}' failed after {elapsed:.1f}s: {e}", exc_info=True)
            return AgentResult(success=False, message=str(e))
