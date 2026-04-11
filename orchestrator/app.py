from __future__ import annotations
import logging
import signal
import threading
import time
from typing import Callable

from db.database import Database
from orchestrator.events import EventBus
from orchestrator.dispatcher import TaskDispatcher
from orchestrator.scheduler import AgentScheduler
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class Application:
    def __init__(self, db: Database, config: dict):
        self.db = db
        self.config = config
        self.event_bus = EventBus()
        self.scheduler = AgentScheduler(db=db, event_bus=self.event_bus, config=config)
        self.dispatcher = TaskDispatcher(db=db, event_bus=self.event_bus, config=config)
        self._running = False
        self._dispatcher_thread: threading.Thread | None = None

    def register_agent(self, agent: BaseAgent) -> None:
        self.scheduler.register(agent)
        self.dispatcher.register_agent(agent)

    def on_event(self, event: str, handler: Callable[[dict], None]) -> None:
        self.event_bus.subscribe(event, handler)

    def start(self) -> None:
        logger.info("Starting TrendBot application")
        self._running = True
        self.scheduler.start()
        self._dispatcher_thread = threading.Thread(
            target=self._dispatch_loop, daemon=True
        )
        self._dispatcher_thread.start()
        logger.info("TrendBot application started")

    def _dispatch_loop(self) -> None:
        while self._running:
            try:
                processed = self.dispatcher.process_one()
                if not processed:
                    poll_interval = self.config.get("orchestrator", {}).get("task_poll_interval", 2)
                    time.sleep(poll_interval)
            except Exception:
                logger.exception("Dispatcher error")
                time.sleep(5)

    def stop(self) -> None:
        logger.info("Stopping TrendBot application")
        self._running = False
        self.scheduler.stop()
        if self._dispatcher_thread:
            self._dispatcher_thread.join(timeout=10)
        logger.info("TrendBot application stopped")

    def run_forever(self) -> None:
        self.start()
        shutdown = threading.Event()

        def handle_signal(signum, frame):
            logger.info(f"Received signal {signum}, shutting down")
            shutdown.set()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            shutdown.wait()
        finally:
            self.stop()
