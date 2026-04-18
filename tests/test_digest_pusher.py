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


def _deep_dive_analysis(db: Database, item_id: int, content: dict) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO item_analysis (item_id, analysis_type, created_at, content, prompt_version) "
            "VALUES (?, 'deep_dive', datetime('now'), ?, 'v1')",
            (item_id, json.dumps(content)),
        )
        conn.commit()


def _set_filter_content(db: Database, item_id: int, content: dict) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE item_analysis SET content=? "
            "WHERE item_id=? AND analysis_type='filter'",
            (json.dumps(content), item_id),
        )
        conn.commit()


class TestDigestDetails:
    def test_digest_includes_filter_summary(self, ctx, db, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
        item_id = upsert_item(db, url="https://example.com/s", title="S",
                              source="github", normalized_score=90.0)
        _filter_analysis(db, item_id)
        _set_filter_content(db, item_id, {"summary": "A memorable one-liner."})

        with patch.object(DigestPusher, "_send") as send:
            DigestPusher().execute(ctx)

        assert send.call_count == 1
        digest_text = send.call_args_list[0][0][2]
        assert "A memorable one-liner." in digest_text

    def test_no_followup_when_no_deep_dive(self, ctx, db, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
        item_id = upsert_item(db, url="https://example.com/n", title="N",
                              source="github", normalized_score=90.0)
        _filter_analysis(db, item_id)

        with patch.object(DigestPusher, "_send") as send:
            DigestPusher().execute(ctx)

        assert send.call_count == 1

    def test_sends_followup_when_deep_dive_present(self, ctx, db, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
        item_id = upsert_item(db, url="https://example.com/d", title="DeepItem",
                              source="github", normalized_score=95.0)
        _filter_analysis(db, item_id)
        _set_filter_content(db, item_id, {"summary": "Short summary"})
        _deep_dive_analysis(db, item_id, {
            "what_it_is": "A novel thing.",
            "why_trending": "People love it.",
            "pain_point": "Real pain.",
            "app_idea": "Build this.",
            "competitors": ["A", "B"],
        })

        with patch.object(DigestPusher, "_send") as send:
            DigestPusher().execute(ctx)

        assert send.call_count == 2
        digest_text = send.call_args_list[0][0][2]
        followup_text = send.call_args_list[1][0][2]
        assert "Short summary" in digest_text
        assert "Deep Dives" in followup_text
        assert "#1" in followup_text
        assert "DeepItem" in followup_text
        assert "A novel thing." in followup_text

    def test_followup_uses_newest_analysis_row(self, ctx, db, monkeypatch):
        """If two deep_dive rows exist for the same item, use the newer one."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
        item_id = upsert_item(db, url="https://example.com/dup", title="Dup",
                              source="github", normalized_score=95.0)
        _filter_analysis(db, item_id)
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO item_analysis (item_id, analysis_type, created_at, content, prompt_version) "
                "VALUES (?, 'deep_dive', datetime('now', '-1 hour'), ?, 'v1')",
                (item_id, json.dumps({"what_it_is": "OLD VERSION"})),
            )
            conn.commit()
        _deep_dive_analysis(db, item_id, {"what_it_is": "NEW VERSION"})

        with patch.object(DigestPusher, "_send") as send:
            DigestPusher().execute(ctx)

        followup_text = send.call_args_list[1][0][2]
        assert "NEW VERSION" in followup_text
        assert "OLD VERSION" not in followup_text


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
