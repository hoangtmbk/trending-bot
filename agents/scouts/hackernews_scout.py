from __future__ import annotations
import logging
from agents.base import BaseAgent, AgentContext, AgentResult
from db.queries import upsert_item, snapshot_score

logger = logging.getLogger(__name__)


class HackerNewsScout(BaseAgent):
    name = "hackernews_scout"
    schedule = "0 */4 * * *"

    def execute(self, ctx: AgentContext) -> AgentResult:
        from collectors.hackernews import HackerNewsCollector
        from scoring.momentum import compute_momentum_score

        sources_cfg = ctx.config.get("sources", {}).get("hackernews", {})
        if not sources_cfg.get("enabled", False):
            return AgentResult(success=True, message="Hacker News disabled in config")

        collector = HackerNewsCollector()

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
            "source": "hackernews",
            "count": len(raw_items),
            "item_ids": item_ids,
        })

        return AgentResult(
            success=True,
            message=f"Hacker News: {len(raw_items)} items collected",
            data={"item_ids": item_ids, "count": len(raw_items)},
        )
