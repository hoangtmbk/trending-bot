from __future__ import annotations
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db.database import Database
from db.queries import get_items, enqueue_task
from interfaces.telegram.formatters import format_item, format_digest, format_deep_dive, format_topics

logger = logging.getLogger(__name__)


def make_item_keyboard(item_id: int) -> InlineKeyboardMarkup:
    """Create inline keyboard for item actions."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\U0001F516 Bookmark", callback_data=f"bookmark:{item_id}"),
            InlineKeyboardButton("\U0001F50D Deep Dive", callback_data=f"deepdive:{item_id}"),
        ],
        [
            InlineKeyboardButton("\U0001F44E Not Relevant", callback_data=f"dismiss:{item_id}"),
            InlineKeyboardButton("\U0001F4CC Track Topic", callback_data=f"track:{item_id}"),
        ],
    ])


async def cmd_trending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show today's top trending items."""
    db: Database = context.bot_data["db"]
    args = context.args or []
    topic_filter = args[0] if args else None

    items = get_items(db, limit=15, order_by="normalized_score DESC")

    if topic_filter:
        # Filter by topic if specified
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT i.* FROM items i "
                "JOIN item_topics it ON i.id = it.item_id "
                "JOIN topics t ON it.topic_id = t.id "
                "WHERE t.name = ? ORDER BY i.normalized_score DESC LIMIT 15",
                (topic_filter,),
            ).fetchall()
            items = [dict(r) for r in rows]

    text = format_digest(items, title=f"Trending \u2014 {topic_filter}" if topic_filter else "Trending")
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_deepdive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Request a deep dive on an item."""
    db: Database = context.bot_data["db"]
    args = context.args or []

    if not args:
        await update.message.reply_text("Usage: /deepdive <url or #id>")
        return

    target = args[0]

    # Find item by URL or ID
    from db.queries import get_item_by_url, get_item_by_id
    if target.startswith("#"):
        item = get_item_by_id(db, int(target[1:]))
    else:
        item = get_item_by_url(db, target)

    if not item:
        await update.message.reply_text("Item not found.")
        return

    # Check if analysis already exists
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT * FROM item_analysis WHERE item_id=? AND analysis_type='deep_dive'",
            (item["id"],),
        ).fetchone()

    if existing:
        text = format_deep_dive(dict(existing))
        await update.message.reply_text(text, parse_mode="HTML")
    else:
        enqueue_task(db, agent_type="deep_diver", payload={"item_id": item["id"], "url": item["url"]})
        await update.message.reply_text(f"\U0001F50D Deep dive queued for: {item['title']}\nI'll notify you when it's ready.")


async def cmd_track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start tracking a topic."""
    db: Database = context.bot_data["db"]
    args = context.args or []

    if not args:
        await update.message.reply_text("Usage: /track <topic name>")
        return

    topic_name = " ".join(args).lower()

    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO topics (name, source, created_at) VALUES (?, 'user', datetime('now'))",
            (topic_name,),
        )
        topic = conn.execute("SELECT id FROM topics WHERE name=?", (topic_name,)).fetchone()
        if topic:
            conn.execute(
                "INSERT OR REPLACE INTO user_interests (topic_id, weight, source, updated_at) "
                "VALUES (?, 2.0, 'explicit', datetime('now'))",
                (topic["id"],),
            )
        conn.commit()

    await update.message.reply_text(f"\U0001F4CC Now tracking: <b>{topic_name}</b> (weight: 2.0)", parse_mode="HTML")


async def cmd_untrack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop tracking a topic."""
    db: Database = context.bot_data["db"]
    args = context.args or []

    if not args:
        await update.message.reply_text("Usage: /untrack <topic name>")
        return

    topic_name = " ".join(args).lower()

    with db.connect() as conn:
        topic = conn.execute("SELECT id FROM topics WHERE name=?", (topic_name,)).fetchone()
        if topic:
            conn.execute("UPDATE user_interests SET weight=0.0, updated_at=datetime('now') WHERE topic_id=?",
                         (topic["id"],))
            conn.commit()
            await update.message.reply_text(f"Untracked: {topic_name}")
        else:
            await update.message.reply_text(f"Topic not found: {topic_name}")


async def cmd_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List active topics."""
    db: Database = context.bot_data["db"]

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT t.name, COALESCE(ui.weight, 1.0) as weight "
            "FROM topics t LEFT JOIN user_interests ui ON t.id = ui.topic_id "
            "WHERE t.is_active = 1 ORDER BY weight DESC",
        ).fetchall()

    topics = [dict(r) for r in rows]
    text = format_topics(topics)
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask a free-form question using knowledge base context."""
    db: Database = context.bot_data["db"]
    args = context.args or []

    if not args:
        await update.message.reply_text("Usage: /ask <your question>")
        return

    question = " ".join(args)

    # Build context from recent items
    recent_items = get_items(db, limit=20, order_by="normalized_score DESC")
    context_lines = []
    for item in recent_items:
        context_lines.append(f"- {item['title']} ({item['source']}, score: {item.get('normalized_score', 0):.0f})")

    try:
        from claude_cli import call_claude
        prompt = (
            f"You are a personal AI trends assistant. Based on the following recent trending items, "
            f"answer the user's question.\n\n"
            f"Recent items:\n{''.join(context_lines)}\n\n"
            f"User question: {question}"
        )
        answer = call_claude(prompt)
        await update.message.reply_text(answer[:4000])
    except Exception as e:
        logger.error(f"Ask command failed: {e}")
        await update.message.reply_text("Sorry, I couldn't process that question right now.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show system status."""
    db: Database = context.bot_data["db"]

    with db.connect() as conn:
        item_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        analysis_count = conn.execute("SELECT COUNT(*) FROM item_analysis").fetchone()[0]
        topic_count = conn.execute("SELECT COUNT(*) FROM topics WHERE is_active=1").fetchone()[0]
        pending_tasks = conn.execute("SELECT COUNT(*) FROM task_queue WHERE status='pending'").fetchone()[0]

    lines = [
        "\U0001F4CA <b>TrendBot Status</b>",
        "",
        f"Items tracked: {item_count}",
        f"Analyses: {analysis_count}",
        f"Active topics: {topic_count}",
        f"Pending tasks: {pending_tasks}",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    db: Database = context.bot_data["db"]
    data = query.data
    action, item_id_str = data.split(":", 1)
    item_id = int(item_id_str)

    if action == "bookmark":
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO user_actions (item_id, action, created_at) VALUES (?, 'bookmarked', datetime('now'))",
                (item_id,),
            )
            conn.commit()
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("\U0001F516 Bookmarked!")

    elif action == "dismiss":
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO user_actions (item_id, action, created_at) VALUES (?, 'dismissed', datetime('now'))",
                (item_id,),
            )
            conn.commit()
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("\U0001F44E Dismissed")

    elif action == "deepdive":
        enqueue_task(db, agent_type="deep_diver", payload={"item_id": item_id})
        await query.message.reply_text("\U0001F50D Deep dive queued!")

    elif action == "track":
        from db.queries import get_item_by_id
        item = get_item_by_id(db, item_id)
        if item:
            # Get item's topics and track them
            with db.connect() as conn:
                topics = conn.execute(
                    "SELECT t.id, t.name FROM topics t JOIN item_topics it ON t.id = it.topic_id WHERE it.item_id = ?",
                    (item_id,),
                ).fetchall()
                for topic in topics:
                    conn.execute(
                        "INSERT OR REPLACE INTO user_interests (topic_id, weight, source, updated_at) "
                        "VALUES (?, 2.0, 'explicit', datetime('now'))",
                        (topic["id"],),
                    )
                conn.commit()
                topic_names = [t["name"] for t in topics]
            if topic_names:
                await query.message.reply_text(f"\U0001F4CC Tracking: {', '.join(topic_names)}")
            else:
                await query.message.reply_text("No topics assigned to this item yet.")
