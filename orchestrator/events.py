from __future__ import annotations
import logging
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)

EventHandler = Callable[[dict], None]


class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event: str, handler: EventHandler) -> None:
        self._handlers[event].append(handler)

    def unsubscribe(self, event: str, handler: EventHandler) -> None:
        handlers = self._handlers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    def emit(self, event: str, data: dict) -> None:
        handlers = self._handlers.get(event, [])
        for handler in handlers:
            try:
                handler(data)
            except Exception:
                logger.exception(f"Error in handler for event '{event}'")
