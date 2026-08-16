"""Supervision for the Telegram polling thread.

python-telegram-bot self-heals once polling is running, but the startup
path (`Application.initialize()` -> `get_me()`) does network I/O before
that loop exists. On 2026-08-15 a transient DNS failure there killed the
telegram thread outright and the bot stayed dead until a manual restart.

The retry loop lives here rather than in main.py so it can be tested
without a network, a real clock, or a running bot.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)

INITIAL_DELAY = 5.0
MAX_DELAY = 60.0
DEGRADED_AFTER_SECONDS = 300.0


class BotState:
    DISABLED = "disabled"
    STARTING = "starting"
    RUNNING = "running"
    RETRYING = "retrying"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BotSnapshot:
    """An immutable view, so a reader never sees a half-written state."""

    state: str
    since: datetime
    last_error: str | None = None

    def is_degraded(
        self,
        now: datetime | None = None,
        grace_seconds: float = DEGRADED_AFTER_SECONDS,
    ) -> bool:
        """True once the bot has been down long enough to be worth alarming on.

        Only `retrying` can degrade: `disabled` means the bot was turned off
        deliberately, and the grace period keeps ordinary short DNS blips
        from flapping the container between healthy and unhealthy.
        """
        if self.state != BotState.RETRYING:
            return False
        now = now or _utcnow()
        return (now - self.since).total_seconds() > grace_seconds

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "since": self.since.isoformat(),
            "last_error": self.last_error,
        }


class BotStatus:
    """Thread-safe state, written by the telegram thread and read by the web app."""

    def __init__(
        self,
        state: str = BotState.DISABLED,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self._clock = clock
        self._lock = threading.Lock()
        self._state = state
        self._since = clock()
        self._last_error: str | None = None

    def _set(self, state: str, error: BaseException | None = None) -> None:
        with self._lock:
            self._state = state
            self._since = self._clock()
            if error is not None:
                self._last_error = f"{type(error).__name__}: {error}"

    def mark_disabled(self) -> None:
        self._set(BotState.DISABLED)

    def mark_starting(self) -> None:
        self._set(BotState.STARTING)

    def mark_running(self) -> None:
        self._set(BotState.RUNNING)

    def mark_retrying(self, error: BaseException) -> None:
        self._set(BotState.RETRYING, error)

    def snapshot(self) -> BotSnapshot:
        with self._lock:
            return BotSnapshot(self._state, self._since, self._last_error)

    def is_degraded(self, grace_seconds: float = DEGRADED_AFTER_SECONDS) -> bool:
        """Judge degradation against this status's own clock, not wall time."""
        return self.snapshot().is_degraded(now=self._clock(), grace_seconds=grace_seconds)


def supervise(
    attempt: Callable[[], None],
    status: BotStatus,
    sleep: Callable[[float], None] = time.sleep,
    initial_delay: float = INITIAL_DELAY,
    max_delay: float = MAX_DELAY,
) -> None:
    """Run `attempt` forever, retrying with capped exponential backoff.

    `attempt` is expected to block until shutdown. Returning normally means
    an intentional shutdown and ends supervision; raising means a failure
    worth retrying. Retries are unbounded on purpose — a bounded loop would
    reintroduce the very failure this exists to prevent.
    """
    delay = initial_delay
    while True:
        try:
            status.mark_starting()
            attempt()
            return
        except Exception as exc:
            # Read the state before overwriting it: reaching `running` means
            # the bot worked for a while, so the next reconnect should be
            # fast rather than inheriting a long backoff.
            if status.snapshot().state == BotState.RUNNING:
                delay = initial_delay
            status.mark_retrying(exc)
            logger.error(
                "Telegram bot failed (%s: %s) — retrying in %.0fs",
                type(exc).__name__, exc, delay,
            )
            sleep(delay)
            delay = min(delay * 2, max_delay)
