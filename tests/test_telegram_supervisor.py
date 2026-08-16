"""Tests for the Telegram bot supervisor.

Regression cover for 2026-08-15, when a transient DNS failure during
Application.initialize() killed the telegram thread outright and the
container went on reporting healthy.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from db.database import Database
from interfaces.web.app import create_app
from interfaces.telegram.supervisor import (
    INITIAL_DELAY,
    MAX_DELAY,
    BotState,
    BotStatus,
    supervise,
)


class FakeClock:
    """Manually advanced clock so tests never touch real time."""

    def __init__(self, start: datetime | None = None):
        self.now = start or datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class RecordingSleep:
    """Records the delays it is asked to sleep, and can break an infinite loop."""

    class Stop(Exception):
        pass

    def __init__(self, stop_after: int | None = None):
        self.calls: list[float] = []
        self.stop_after = stop_after

    def __call__(self, delay: float) -> None:
        self.calls.append(delay)
        if self.stop_after is not None and len(self.calls) >= self.stop_after:
            raise RecordingSleep.Stop()


@pytest.fixture
def db(tmp_path):
    database = Database(db_path=tmp_path / "test.db")
    database.initialize()
    return database


# ── BotStatus ──

class TestBotStatus:
    def test_defaults_to_disabled(self):
        assert BotStatus().snapshot().state == BotState.DISABLED

    def test_records_transitions(self):
        status = BotStatus()
        status.mark_starting()
        assert status.snapshot().state == BotState.STARTING
        status.mark_running()
        assert status.snapshot().state == BotState.RUNNING

    def test_retrying_records_the_error(self):
        status = BotStatus()
        status.mark_retrying(RuntimeError("httpx.ConnectError: nope"))
        snap = status.snapshot()
        assert snap.state == BotState.RETRYING
        assert "nope" in snap.last_error

    def test_since_advances_on_state_change(self):
        clock = FakeClock()
        status = BotStatus(clock=clock)
        status.mark_starting()
        first = status.snapshot().since
        clock.advance(30)
        status.mark_running()
        assert status.snapshot().since == first + timedelta(seconds=30)

    def test_snapshot_is_isolated_from_later_writes(self):
        status = BotStatus()
        status.mark_running()
        snap = status.snapshot()
        status.mark_retrying(RuntimeError("boom"))
        assert snap.state == BotState.RUNNING

    def test_running_is_not_degraded(self):
        clock = FakeClock()
        status = BotStatus(clock=clock)
        status.mark_running()
        clock.advance(9999)
        assert status.snapshot().is_degraded(now=clock()) is False

    def test_disabled_is_never_degraded(self):
        """A bot intentionally turned off in config is not a fault."""
        clock = FakeClock()
        status = BotStatus(clock=clock)
        clock.advance(9999)
        assert status.snapshot().is_degraded(now=clock()) is False

    def test_retrying_within_grace_is_not_degraded(self):
        clock = FakeClock()
        status = BotStatus(clock=clock)
        status.mark_retrying(RuntimeError("blip"))
        clock.advance(60)
        assert status.snapshot().is_degraded(now=clock()) is False

    def test_retrying_beyond_grace_is_degraded(self):
        clock = FakeClock()
        status = BotStatus(clock=clock)
        status.mark_retrying(RuntimeError("sustained outage"))
        clock.advance(301)
        assert status.snapshot().is_degraded(now=clock()) is True


# ── supervise() ──

class TestSupervise:
    def test_clean_return_exits_without_sleeping(self):
        """A normal return means intentional shutdown, not a failure."""
        status, sleep = BotStatus(), RecordingSleep()
        supervise(lambda: None, status, sleep=sleep)
        assert sleep.calls == []

    def test_recovers_after_transient_failures(self):
        status, sleep = BotStatus(), RecordingSleep()
        attempts = []

        def attempt():
            attempts.append(1)
            if len(attempts) <= 2:
                raise RuntimeError("httpx.ConnectError: All connection attempts failed")
            status.mark_running()

        supervise(attempt, status, sleep=sleep)

        assert len(attempts) == 3
        assert status.snapshot().state == BotState.RUNNING

    def test_backoff_is_exponential(self):
        status, sleep = BotStatus(), RecordingSleep()
        attempts = []

        def attempt():
            attempts.append(1)
            if len(attempts) <= 2:
                raise RuntimeError("boom")

        supervise(attempt, status, sleep=sleep)
        assert sleep.calls == [INITIAL_DELAY, INITIAL_DELAY * 2]

    def test_retries_are_unbounded(self):
        """A long outage must never leave the bot permanently dead."""
        status, sleep = BotStatus(), RecordingSleep(stop_after=20)

        def attempt():
            raise RuntimeError("still down")

        with pytest.raises(RecordingSleep.Stop):
            supervise(attempt, status, sleep=sleep)

        assert len(sleep.calls) == 20
        assert status.snapshot().state == BotState.RETRYING

    def test_backoff_is_capped(self):
        status, sleep = BotStatus(), RecordingSleep(stop_after=8)

        def attempt():
            raise RuntimeError("still down")

        with pytest.raises(RecordingSleep.Stop):
            supervise(attempt, status, sleep=sleep)

        assert max(sleep.calls) == MAX_DELAY
        assert sleep.calls == [5.0, 10.0, 20.0, 40.0, 60.0, 60.0, 60.0, 60.0]

    def test_backoff_resets_after_a_successful_run(self):
        """Failing after a week of uptime should reconnect fast, not at 60s."""
        status, sleep = BotStatus(), RecordingSleep(stop_after=3)
        attempts = []

        def attempt():
            attempts.append(1)
            if len(attempts) == 2:
                status.mark_running()
            raise RuntimeError("boom")

        with pytest.raises(RecordingSleep.Stop):
            supervise(attempt, status, sleep=sleep)

        # 1st failure -> 5s. 2nd attempt reached running, so the backoff
        # resets instead of climbing to 10s. Then it climbs again.
        assert sleep.calls == [INITIAL_DELAY, INITIAL_DELAY, INITIAL_DELAY * 2]

    def test_marks_starting_before_each_attempt(self):
        status, sleep = BotStatus(), RecordingSleep()
        seen = []

        def attempt():
            seen.append(status.snapshot().state)

        supervise(attempt, status, sleep=sleep)
        assert seen == [BotState.STARTING]


# ── /api/health ──

class TestHealthReportsBotState:
    def test_defaults_to_disabled_when_no_status_passed(self, db):
        """The 17 existing create_app call sites must keep working."""
        resp = TestClient(create_app(db, config={})).get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["telegram"]["state"] == BotState.DISABLED

    def test_running_is_healthy(self, db):
        status = BotStatus()
        status.mark_running()
        resp = TestClient(create_app(db, config={}, bot_status=status)).get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["telegram"]["state"] == BotState.RUNNING

    def test_brief_outage_stays_healthy(self, db):
        """Short DNS blips must not flap the container to unhealthy."""
        clock = FakeClock()
        status = BotStatus(clock=clock)
        status.mark_retrying(RuntimeError("blip"))
        clock.advance(60)
        resp = TestClient(create_app(db, config={}, bot_status=status)).get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_sustained_outage_is_degraded(self, db):
        clock = FakeClock()
        status = BotStatus(clock=clock)
        status.mark_retrying(RuntimeError("httpx.ConnectError: All connection attempts failed"))
        clock.advance(301)
        resp = TestClient(create_app(db, config={}, bot_status=status)).get("/api/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["ok"] is False
        assert body["telegram"]["state"] == BotState.RETRYING
        assert "ConnectError" in body["telegram"]["last_error"]

    def test_still_reports_version(self, db):
        status = BotStatus()
        status.mark_running()
        resp = TestClient(create_app(db, config={}, bot_status=status)).get("/api/health")
        assert isinstance(resp.json()["version"], str)
