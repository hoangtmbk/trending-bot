from __future__ import annotations
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from interfaces.telegram.formatters import (
    format_item, format_digest, format_deep_dive, format_topics, _escape_html,
)
from interfaces.telegram.commands import (
    make_item_keyboard, cmd_trending, cmd_track, cmd_status,
    cmd_deepdive, cmd_untrack, cmd_topics, handle_callback,
)
from db.database import Database


@pytest.fixture
def db(tmp_path):
    """Create an initialized in-memory-like temp database."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    return db


@pytest.fixture
def sample_item():
    return {
        "title": "AgentKit v2",
        "url": "https://github.com/example/agentkit",
        "source": "github",
        "normalized_score": 85.5,
        "times_seen": 3,
    }


@pytest.fixture
def mock_update():
    """Create a mock Telegram Update object."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_context(db):
    """Create a mock Telegram context with db in bot_data."""
    context = MagicMock()
    context.bot_data = {"db": db, "config": {}}
    context.args = []
    return context


# -- Formatter tests --

class TestEscapeHtml:
    def test_escapes_ampersand(self):
        assert _escape_html("A & B") == "A &amp; B"

    def test_escapes_angle_brackets(self):
        assert _escape_html("<script>alert('x')</script>") == "&lt;script&gt;alert('x')&lt;/script&gt;"

    def test_escapes_all_special_chars(self):
        result = _escape_html("a < b & c > d")
        assert result == "a &lt; b &amp; c &gt; d"

    def test_no_change_for_safe_text(self):
        text = "Hello World 123"
        assert _escape_html(text) == text


class TestFormatItem:
    def test_formats_github_item(self, sample_item):
        result = format_item(sample_item)
        assert "<b>AgentKit v2</b>" in result
        assert "https://github.com/example/agentkit" in result
        assert "Score: 86" in result
        assert "Seen: 3x" in result
        assert "Source: github" in result

    def test_uses_source_icon(self, sample_item):
        result = format_item(sample_item)
        # GitHub icon is a star
        assert "\u2b50" in result

    def test_handles_missing_url(self):
        item = {"title": "Test", "source": "reddit", "normalized_score": 50}
        result = format_item(item)
        assert "Test" in result
        assert "\U0001F517" not in result  # No link icon when no URL

    def test_truncates_long_title(self):
        item = {"title": "A" * 200, "source": "github", "url": "", "normalized_score": 10}
        result = format_item(item)
        # Title should be truncated to 100 chars
        assert "A" * 100 in result
        assert "A" * 101 not in result

    def test_unknown_source_uses_bullet(self):
        item = {"title": "Test", "source": "unknown_source", "normalized_score": 10}
        result = format_item(item)
        assert "\u2022" in result


class TestFormatDigest:
    def test_empty_items_returns_message(self):
        result = format_digest([])
        assert result == "No trending items found."

    def test_formats_items_with_numbers(self, sample_item):
        items = [sample_item, {**sample_item, "title": "Second Item"}]
        result = format_digest(items)
        assert "1." in result
        assert "2." in result
        assert "2 items" in result

    def test_custom_title(self, sample_item):
        result = format_digest([sample_item], title="My Custom Title")
        assert "My Custom Title" in result

    def test_limits_to_15_items(self):
        items = [{"title": f"Item {i}", "source": "github", "normalized_score": i} for i in range(20)]
        result = format_digest(items)
        assert "15." in result
        assert "16." not in result

    def test_includes_url_when_present(self, sample_item):
        result = format_digest([sample_item])
        assert "https://github.com/example/agentkit" in result
        assert 'href="https://github.com/example/agentkit"' in result

    def test_omits_link_when_url_missing(self):
        item = {"title": "No URL", "source": "github", "normalized_score": 50}
        result = format_digest([item])
        assert "No URL" in result
        assert "href=" not in result

    def test_escapes_url_special_chars(self):
        item = {"title": "Tricky", "source": "github",
                "url": "https://example.com/q?a=1&b=<x>", "normalized_score": 10}
        result = format_digest([item])
        assert "&amp;" in result
        assert "&lt;x&gt;" in result


class TestFormatDeepDive:
    def test_formats_analysis_content(self):
        analysis = {
            "content": json.dumps({
                "what_it_is": "A framework for building agents",
                "why_trending": "New release with major improvements",
                "pain_point": "Agent orchestration is hard",
                "app_idea": "Build a no-code agent builder",
                "competitors": ["LangChain", "AutoGen"],
            })
        }
        result = format_deep_dive(analysis)
        assert "Deep Dive" in result
        assert "A framework for building agents" in result
        assert "New release" in result
        assert "Agent orchestration is hard" in result
        assert "no-code agent builder" in result
        assert "LangChain, AutoGen" in result

    def test_handles_dict_content(self):
        analysis = {
            "content": {
                "what_it_is": "A tool",
                "why_trending": "Popular",
                "pain_point": "Complexity",
                "app_idea": "Simplify it",
            }
        }
        result = format_deep_dive(analysis)
        assert "A tool" in result


class TestFormatTopics:
    def test_empty_topics(self):
        result = format_topics([])
        assert result == "No active topics."

    def test_formats_topics_with_weights(self):
        topics = [
            {"name": "llm agents", "weight": 2.5},
            {"name": "rag", "weight": 1.0},
            {"name": "deprecated", "weight": 0.5},
        ]
        result = format_topics(topics)
        assert "llm agents" in result
        assert "weight: 2.5" in result
        assert "\U0001F534" in result  # High weight indicator
        assert "\U0001F7E1" in result  # Medium weight indicator
        assert "\u26aa" in result  # Low weight indicator


# -- Keyboard tests --

class TestMakeItemKeyboard:
    def test_returns_inline_keyboard(self):
        keyboard = make_item_keyboard(42)
        assert keyboard is not None
        # Should have 2 rows
        assert len(keyboard.inline_keyboard) == 2

    def test_first_row_has_bookmark_and_deepdive(self):
        keyboard = make_item_keyboard(42)
        row1 = keyboard.inline_keyboard[0]
        assert len(row1) == 2
        assert row1[0].callback_data == "bookmark:42"
        assert row1[1].callback_data == "deepdive:42"

    def test_second_row_has_dismiss_and_track(self):
        keyboard = make_item_keyboard(42)
        row2 = keyboard.inline_keyboard[1]
        assert len(row2) == 2
        assert row2[0].callback_data == "dismiss:42"
        assert row2[1].callback_data == "track:42"

    def test_button_labels(self):
        keyboard = make_item_keyboard(1)
        row1 = keyboard.inline_keyboard[0]
        assert "Bookmark" in row1[0].text
        assert "Deep Dive" in row1[1].text


# -- Command handler tests --

class TestCmdTrending:
    @pytest.mark.asyncio
    async def test_trending_empty_db(self, mock_update, mock_context):
        await cmd_trending(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        call_args = mock_update.message.reply_text.call_args
        assert "No trending items found." in call_args[0][0]

    @pytest.mark.asyncio
    async def test_trending_with_items(self, mock_update, mock_context, db):
        # Insert test items
        from db.queries import upsert_item
        upsert_item(db, url="https://example.com/1", title="Test Item 1",
                     source="github", normalized_score=90.0)
        upsert_item(db, url="https://example.com/2", title="Test Item 2",
                     source="reddit", normalized_score=80.0)

        await cmd_trending(mock_update, mock_context)
        call_args = mock_update.message.reply_text.call_args
        text = call_args[0][0]
        assert "Test Item 1" in text
        assert "Test Item 2" in text
        assert "2 items" in text


class TestCmdTrack:
    @pytest.mark.asyncio
    async def test_track_no_args(self, mock_update, mock_context):
        mock_context.args = []
        await cmd_track(mock_update, mock_context)
        call_args = mock_update.message.reply_text.call_args
        assert "Usage:" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_track_creates_topic(self, mock_update, mock_context, db):
        mock_context.args = ["llm", "agents"]
        await cmd_track(mock_update, mock_context)

        # Verify topic was created
        with db.connect() as conn:
            topic = conn.execute("SELECT * FROM topics WHERE name='llm agents'").fetchone()
            assert topic is not None
            assert topic["source"] == "user"

            interest = conn.execute(
                "SELECT * FROM user_interests WHERE topic_id=?", (topic["id"],)
            ).fetchone()
            assert interest is not None
            assert interest["weight"] == 2.0

        call_args = mock_update.message.reply_text.call_args
        assert "llm agents" in call_args[0][0]


class TestCmdStatus:
    @pytest.mark.asyncio
    async def test_status_shows_counts(self, mock_update, mock_context, db):
        # Insert some test data
        from db.queries import upsert_item, enqueue_task
        upsert_item(db, url="https://example.com/1", title="Item 1", source="github")
        enqueue_task(db, agent_type="scout", payload={"test": True})

        await cmd_status(mock_update, mock_context)
        call_args = mock_update.message.reply_text.call_args
        text = call_args[0][0]
        assert "TrendBot Status" in text
        assert "Items tracked: 1" in text
        assert "Pending tasks: 1" in text


class TestCmdDeepDive:
    @pytest.mark.asyncio
    async def test_deepdive_no_args(self, mock_update, mock_context):
        mock_context.args = []
        await cmd_deepdive(mock_update, mock_context)
        call_args = mock_update.message.reply_text.call_args
        assert "Usage:" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_deepdive_item_not_found(self, mock_update, mock_context):
        mock_context.args = ["https://nonexistent.com"]
        await cmd_deepdive(mock_update, mock_context)
        call_args = mock_update.message.reply_text.call_args
        assert "not found" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_deepdive_queues_task(self, mock_update, mock_context, db):
        from db.queries import upsert_item
        item_id = upsert_item(db, url="https://example.com/test", title="Test", source="github")

        mock_context.args = [f"#{item_id}"]
        await cmd_deepdive(mock_update, mock_context)
        call_args = mock_update.message.reply_text.call_args
        assert "queued" in call_args[0][0].lower()

        # Verify task was enqueued
        with db.connect() as conn:
            task = conn.execute("SELECT * FROM task_queue WHERE status='pending'").fetchone()
            assert task is not None
            assert json.loads(task["payload"])["item_id"] == item_id


class TestCmdUntrack:
    @pytest.mark.asyncio
    async def test_untrack_no_args(self, mock_update, mock_context):
        mock_context.args = []
        await cmd_untrack(mock_update, mock_context)
        call_args = mock_update.message.reply_text.call_args
        assert "Usage:" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_untrack_nonexistent_topic(self, mock_update, mock_context):
        mock_context.args = ["nonexistent"]
        await cmd_untrack(mock_update, mock_context)
        call_args = mock_update.message.reply_text.call_args
        assert "not found" in call_args[0][0].lower()


class TestCmdTopics:
    @pytest.mark.asyncio
    async def test_topics_empty(self, mock_update, mock_context):
        await cmd_topics(mock_update, mock_context)
        call_args = mock_update.message.reply_text.call_args
        assert "No active topics." in call_args[0][0]


class TestHandleCallback:
    @pytest.mark.asyncio
    async def test_bookmark_callback(self, mock_context, db):
        from db.queries import upsert_item
        item_id = upsert_item(db, url="https://example.com/cb", title="CB Item", source="github")

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.data = f"bookmark:{item_id}"
        update.callback_query.edit_message_reply_markup = AsyncMock()
        update.callback_query.message = MagicMock()
        update.callback_query.message.reply_text = AsyncMock()

        await handle_callback(update, mock_context)

        update.callback_query.answer.assert_awaited_once()
        update.callback_query.edit_message_reply_markup.assert_awaited_once()

        # Verify action was recorded in DB
        with db.connect() as conn:
            action = conn.execute(
                "SELECT * FROM user_actions WHERE item_id=? AND action='bookmarked'",
                (item_id,),
            ).fetchone()
            assert action is not None
