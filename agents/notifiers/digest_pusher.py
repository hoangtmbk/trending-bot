from __future__ import annotations
import asyncio
import json
import logging
import os

from agents.base import BaseAgent, AgentContext, AgentResult
from interfaces.telegram.formatters import format_digest, format_deep_dives_followup

logger = logging.getLogger(__name__)


class DigestPusher(BaseAgent):
    """Pushes a Telegram digest of newly-tracked items on a cron schedule.

    Selection: items the filter has promoted to status='tracking' whose filter
    analysis was recorded after the last 'daily' digest row — so each item is
    pushed at most once even if the cron fires more often than the filter.
    """

    name = "digest_pusher"
    schedule = "0 8,20 * * *"  # 08:00 + 20:00 container-local (TZ=Asia/Bangkok, UTC+7)

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

        summaries, deep_dives = self._load_analyses(ctx, [item["id"] for item in items])

        digest_text = format_digest(items, title="Trending", summaries=summaries)
        self._send(bot_token, chat_id, digest_text)

        followup_text = format_deep_dives_followup(items, deep_dives)
        if followup_text:
            self._send(bot_token, chat_id, followup_text)

        self._record_digest(ctx, items)

        message = f"Sent digest with {len(items)} items"
        if followup_text:
            message += f" + deep-dive follow-up ({len(deep_dives)} items)"

        return AgentResult(
            success=True,
            message=message,
            data={"count": len(items), "deep_dives": bool(followup_text)},
        )

    def _load_analyses(
        self, ctx: AgentContext, item_ids: list[int],
    ) -> tuple[dict[int, str], dict[int, dict]]:
        """Return (summaries, deep_dives) keyed by item_id.

        summaries[item_id] -> the filter row's `summary` field (str).
        deep_dives[item_id] -> the parsed deep_dive payload (dict).
        When multiple rows exist for the same (item_id, type) the most recent wins.
        """
        if not item_ids:
            return {}, {}

        placeholders = ",".join("?" * len(item_ids))
        summaries: dict[int, str] = {}
        deep_dives: dict[int, dict] = {}
        with ctx.db.connect() as conn:
            rows = conn.execute(
                f"SELECT item_id, analysis_type, content FROM item_analysis "
                f"WHERE analysis_type IN ('filter', 'deep_dive') "
                f"  AND item_id IN ({placeholders}) "
                f"ORDER BY created_at DESC",
                item_ids,
            ).fetchall()

        for row in rows:
            item_id = row["item_id"]
            try:
                payload = json.loads(row["content"]) if row["content"] else {}
            except (ValueError, TypeError):
                logger.debug("Malformed %s analysis for item %s", row["analysis_type"], item_id)
                continue
            if row["analysis_type"] == "filter":
                if item_id in summaries:
                    continue
                summary = payload.get("summary") if isinstance(payload, dict) else None
                if isinstance(summary, str) and summary.strip():
                    summaries[item_id] = summary.strip()
            elif row["analysis_type"] == "deep_dive":
                if item_id in deep_dives:
                    continue
                if isinstance(payload, dict):
                    deep_dives[item_id] = payload

        return summaries, deep_dives

    def _select_items(self, ctx: AgentContext, limit: int) -> list[dict]:
        """Pick tracked items whose filter analysis is newer than the last
        digest. Orders by interest_score DESC then normalized_score DESC — so
        the LLM's quality call leads, with topic-affinity (baked into
        normalized_score via C3) as tiebreaker.
        """
        with ctx.db.connect() as conn:
            last = conn.execute(
                "SELECT created_at FROM digests WHERE digest_type='daily' "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            cutoff = last["created_at"] if last else None

            # Latest filter row per item (same pattern as get_items_with_filter).
            query = """
                SELECT i.*,
                       CAST(json_extract(ia.content, '$.interest_score') AS INTEGER) AS interest_score
                FROM items i
                JOIN (
                    SELECT item_id, MAX(created_at) AS max_created
                    FROM item_analysis
                    WHERE analysis_type = 'filter'
                    GROUP BY item_id
                ) latest ON latest.item_id = i.id
                JOIN item_analysis ia
                  ON ia.item_id = latest.item_id
                 AND ia.analysis_type = 'filter'
                 AND ia.created_at = latest.max_created
                WHERE i.status = 'tracking'
            """
            params: list = []
            if cutoff:
                query += " AND ia.created_at > ?"
                params.append(cutoff)
            query += " ORDER BY interest_score DESC, i.normalized_score DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
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
