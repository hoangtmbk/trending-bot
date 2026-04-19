from __future__ import annotations
import logging

from agents.base import BaseAgent, AgentContext, AgentResult
from db.queries import upsert_item, snapshot_score

logger = logging.getLogger(__name__)


class PapersWithCodeScout(BaseAgent):
    name = "papers_with_code_scout"
    schedule = "0 */12 * * *"

    def execute(self, ctx: AgentContext) -> AgentResult:
        from collectors.papers_with_code import PapersWithCodeCollector
        from scoring.momentum import compute_momentum_score

        sources_cfg = ctx.config.get("sources", {}).get("papers_with_code", {})
        if not sources_cfg.get("enabled", False):
            return AgentResult(success=True, message="Papers With Code disabled in config")

        raw_items = PapersWithCodeCollector().collect()

        item_ids: list[int] = []
        for raw in raw_items:
            try:
                momentum = compute_momentum_score(raw)
            except Exception:
                momentum = 0.0
            item_id = upsert_item(
                ctx.db, url=raw.url, title=raw.title, source=raw.source,
                description=raw.description, raw_metrics=raw.metrics,
                momentum_score=momentum,
            )
            item_ids.append(item_id)
            snapshot_score(ctx.db, item_id, momentum_score=momentum,
                           normalized_score=0.0, raw_metrics=raw.metrics)

        ctx.emit("items_updated", {
            "source": "papers_with_code", "count": len(raw_items),
            "item_ids": item_ids,
        })
        return AgentResult(
            success=True,
            message=f"Papers With Code: {len(raw_items)} items",
            data={"item_ids": item_ids, "count": len(raw_items)},
        )
