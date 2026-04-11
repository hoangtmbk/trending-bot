from __future__ import annotations
import logging
from agents.base import BaseAgent, AgentContext, AgentResult
from db.queries import upsert_item, snapshot_score

logger = logging.getLogger(__name__)


class RedditScout(BaseAgent):
    name = "reddit_scout"
    schedule = "0 */4 * * *"

    def execute(self, ctx: AgentContext) -> AgentResult:
        from config import get_env
        from scoring.momentum import compute_momentum_score

        sources_cfg = ctx.config.get("sources", {}).get("reddit", {})
        if not sources_cfg.get("enabled", False):
            return AgentResult(success=True, message="Reddit disabled in config")

        subreddits = sources_cfg.get("subreddits")
        collector = None

        # Try PRAW-based collector first, fall back to public API
        try:
            from collectors.reddit import RedditCollector
            client_id = get_env("REDDIT_CLIENT_ID")
            client_secret = get_env("REDDIT_CLIENT_SECRET")
            collector = RedditCollector(
                client_id=client_id,
                client_secret=client_secret,
                user_agent="trending-bot/1.0",
                subreddits=subreddits,
            )
        except (EnvironmentError, Exception) as e:
            logger.warning(f"PRAW collector unavailable ({e}), using public API")
            from collectors.reddit import RedditPublicCollector
            collector = RedditPublicCollector(subreddits=subreddits)

        raw_items = collector.collect()

        item_ids = []
        for raw in raw_items:
            try:
                momentum = compute_momentum_score(raw)
            except Exception:
                momentum = 0.0

            item_id = upsert_item(
                ctx.db,
                url=raw.url,
                title=raw.title,
                source=raw.source,
                description=raw.description,
                raw_metrics=raw.metrics,
                momentum_score=momentum,
            )
            item_ids.append(item_id)

            snapshot_score(
                ctx.db, item_id,
                momentum_score=momentum,
                normalized_score=0.0,
                raw_metrics=raw.metrics,
            )

        ctx.emit("items_updated", {
            "source": "reddit",
            "count": len(raw_items),
            "item_ids": item_ids,
        })

        return AgentResult(
            success=True,
            message=f"Reddit: {len(raw_items)} items collected",
            data={"item_ids": item_ids, "count": len(raw_items)},
        )
