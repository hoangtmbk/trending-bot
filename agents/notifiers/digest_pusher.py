from __future__ import annotations
import asyncio
import json
import logging
import os

from agents.base import BaseAgent, AgentContext, AgentResult
from interfaces.telegram.formatters import format_digest

logger = logging.getLogger(__name__)


class DigestPusher(BaseAgent):
    """Pushes a Telegram digest of newly-tracked items on a cron schedule.

    Selection: items the filter has promoted to status='tracking' whose filter
    analysis was recorded after the last 'daily' digest row — so each item is
    pushed at most once even if the cron fires more often than the filter.
    """

    name = "digest_pusher"
    schedule = "0 8,20 * * *"  # 08:00 + 20:00 UTC

    def execute(self, ctx: AgentContext) -> AgentResult:
        delivery_cfg = ctx.config.get("delivery", {}).get("telegram", {})
        if not delivery_cfg.get("enabled", False):
            return AgentResult(success=True, message="Telegram delivery disabled")

        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not bot_token or not chat_id:
            return AgentResult(
                success=False,
                message="TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set",
            )

        limit = ctx.config.get("scoring", {}).get("digest_size", 15)
        items = self._select_items(ctx, limit=limit)
        if not items:
            return AgentResult(success=True, message="No new tracked items to send")

        text = format_digest(items, title="Trending")
        self._send(bot_token, chat_id, text)
        self._record_digest(ctx, items)

        return AgentResult(
            success=True,
            message=f"Sent digest with {len(items)} items",
            data={"count": len(items)},
        )

    def _select_items(self, ctx: AgentContext, limit: int) -> list[dict]:
        with ctx.db.connect() as conn:
            last = conn.execute(
                "SELECT created_at FROM digests WHERE digest_type='daily' "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            cutoff = last["created_at"] if last else None

            if cutoff:
                rows = conn.execute(
                    "SELECT i.* FROM items i "
                    "JOIN item_analysis ia ON ia.item_id = i.id "
                    "WHERE ia.analysis_type='filter' "
                    "  AND ia.created_at > ? "
                    "  AND i.status='tracking' "
                    "GROUP BY i.id "
                    "ORDER BY i.normalized_score DESC "
                    "LIMIT ?",
                    (cutoff, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM items WHERE status='tracking' "
                    "ORDER BY normalized_score DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def _record_digest(self, ctx: AgentContext, items: list[dict]) -> None:
        item_ids = json.dumps([item["id"] for item in items])
        with ctx.db.connect() as conn:
            conn.execute(
                "INSERT INTO digests (digest_type, created_at, item_ids) "
                "VALUES ('daily', datetime('now'), ?)",
                (item_ids,),
            )
            conn.commit()

    def _send(self, bot_token: str, chat_id: str, text: str) -> None:
        """Send via python-telegram-bot, chunking to respect the 4096-char cap."""
        from telegram import Bot

        chunks = _chunk(text, limit=3900)

        async def _do_send():
            bot = Bot(token=bot_token)
            for chunk in chunks:
                await bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )

        asyncio.run(_do_send())


def _chunk(text: str, limit: int) -> list[str]:
    """Split text on newline boundaries so HTML tags never straddle chunks."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.split("\n"):
        line_len = len(line) + 1
        if current_len + line_len > limit and current:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks
