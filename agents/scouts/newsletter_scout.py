from __future__ import annotations
import logging

from agents.base import BaseAgent, AgentContext, AgentResult
from db.queries import upsert_item, snapshot_score

logger = logging.getLogger(__name__)


class NewsletterScout(BaseAgent):
    """Pulls AI newsletters (Import AI, Interconnects, TLDR AI, Rundown).

    Separate from blogs because newsletters are already curated editorial —
    momentum branch weights them 2× to reflect that prior.
    """
    name = "newsletter_scout"
    schedule = "0 */12 * * *"

    def execute(self, ctx: AgentContext) -> AgentResult:
        from collectors.rss import RSSCollector
        from scoring.momentum import compute_momentum_score

        sources_cfg = ctx.config.get("sources", {}).get("newsletters", {})
        if not sources_cfg.get("enabled", False):
            return AgentResult(success=True, message="Newsletters disabled in config")

        feeds: list[dict] = sources_cfg.get("feeds", [])
        if not feeds:
            return AgentResult(success=True, message="No newsletter feeds configured")

        total_ids: list[int] = []
        total_count = 0
        for feed in feeds:
            feed_url = feed.get("url")
            feed_name = feed.get("name", feed_url)
            if not feed_url:
                continue
            try:
                collector = RSSCollector(feed_url=feed_url, source_name="newsletter")
                raw_items = collector.collect()
            except Exception as e:
                logger.warning(f"Newsletter scout: {feed_name} failed: {e}")
                continue

            for raw in raw_items:
                raw.metrics["feed_name"] = feed_name
                try:
                    momentum = compute_momentum_score(raw)
                except Exception:
                    momentum = 0.0
                item_id = upsert_item(
                    ctx.db, url=raw.url, title=raw.title, source=raw.source,
                    description=raw.description, raw_metrics=raw.metrics,
                    momentum_score=momentum,
                )
                total_ids.append(item_id)
                snapshot_score(ctx.db, item_id, momentum_score=momentum,
                               normalized_score=0.0, raw_metrics=raw.metrics)
            total_count += len(raw_items)

        ctx.emit("items_updated", {
            "source": "newsletter", "count": total_count, "item_ids": total_ids,
        })
        return AgentResult(
            success=True,
            message=f"Newsletters: {total_count} items from {len(feeds)} feeds",
            data={"item_ids": total_ids, "count": total_count},
        )
