from __future__ import annotations
import json
from unittest.mock import patch

import pytest

from agents.base import AgentContext
from agents.notifiers.digest_pusher import DigestPusher, _chunk
from db.database import Database
from db.queries import upsert_item
from orchestrator.events import EventBus


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "test.db")
    db.initialize()
    return db


@pytest.fixture
def ctx(db):
    return AgentContext(
        db=db,
        event_bus=EventBus(),
        config={"delivery": {"telegram": {"enabled": True}},
                "scoring": {"digest_size": 10}},
    )


def _filter_analysis(db: Database, item_id: int, when: str = "datetime('now')") -> None:
    with db.connect() as conn:
        conn.execute(
            f"INSERT INTO item_analysis (item_id, analysis_type, created_at, content, prompt_version) "
            f"VALUES (?, 'filter', {when}, '{{}}', 'v1')",
            (item_id,),
        )
        conn.execute("UPDATE items SET status='tracking' WHERE id=?", (item_id,))
        conn.commit()


class TestDigestPusher:
    def test_returns_ok_when_telegram_disabled(self, db):
        ctx = AgentContext(
            db=db, event_bus=EventBus(),
            config={"delivery": {"telegram": {"enabled": False}}},
        )
        result = DigestPusher().execute(ctx)
        assert result.success
        assert "disabled" in result.message.lower()

    def test_fails_when_env_missing(self, ctx, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        result = DigestPusher().execute(ctx)
        assert not result.success
        assert "TELEGRAM_BOT_TOKEN" in result.message

    def test_noop_when_no_tracked_items(self, ctx, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
        with patch.object(DigestPusher, "_send") as send:
            result = DigestPusher().execute(ctx)
        assert result.success
        assert "No new" in result.message
        send.assert_not_called()

    def test_sends_and_records_when_items_present(self, ctx, db, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
        item_id = upsert_item(db, url="https://example.com/a", title="A",
                              source="github", normalized_score=90.0)
        _filter_analysis(db, item_id)

        with patch.object(DigestPusher, "_send") as send:
            result = DigestPusher().execute(ctx)

        assert result.success
        assert result.data["count"] == 1
        send.assert_called_once()
        sent_text = send.call_args[0][2]
        assert "https://example.com/a" in sent_text

        # Digest row was recorded
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM digests WHERE digest_type='daily'").fetchone()
            assert row is not None
            assert json.loads(row["item_ids"]) == [item_id]

    def test_excludes_items_seen_before_last_digest(self, ctx, db, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")

        # Old item filtered an hour ago
        old_id = upsert_item(db, url="https://example.com/old", title="Old",
                             source="github", normalized_score=50.0)
        _filter_analysis(db, old_id, when="datetime('now', '-1 hour')")

        # Previous digest recorded 30min ago
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO digests (digest_type, created_at, item_ids) "
                "VALUES ('daily', datetime('now', '-30 minutes'), '[]')"
            )
            conn.commit()

        # Fresh item filtered just now
        new_id = upsert_item(db, url="https://example.com/new", title="New",
                             source="reddit", normalized_score=75.0)
        _filter_analysis(db, new_id)

        with patch.object(DigestPusher, "_send") as send:
            result = DigestPusher().execute(ctx)

        assert result.data["count"] == 1
        sent_text = send.call_args[0][2]
        assert "https://example.com/new" in sent_text
        assert "https://example.com/old" not in sent_text


class TestChunk:
    def test_short_text_returns_single_chunk(self):
        assert _chunk("hello", limit=100) == ["hello"]

    def test_splits_on_newline_boundaries(self):
        text = "aaaa\nbbbb\ncccc\ndddd"
        chunks = _chunk(text, limit=10)
        assert len(chunks) >= 2
        for c in chunks:
            assert len(c) <= 10
        assert "\n".join(chunks).replace("\n\n", "\n") == text
