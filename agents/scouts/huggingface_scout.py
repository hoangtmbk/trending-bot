from __future__ import annotations
import logging
from agents.base import BaseAgent, AgentContext, AgentResult
from db.queries import upsert_item, snapshot_score

logger = logging.getLogger(__name__)


class HuggingFaceScout(BaseAgent):
    name = "huggingface_scout"
    schedule = "0 */6 * * *"

    def execute(self, ctx: AgentContext) -> AgentResult:
        from collectors.huggingface import HuggingFaceCollector
        from scoring.momentum import compute_momentum_score

        sources_cfg = ctx.config.get("sources", {}).get("huggingface", {})
        if not sources_cfg.get("enabled", False):
            return AgentResult(success=True, message="HuggingFace disabled in config")

        collector = HuggingFaceCollector()

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
            "source": "huggingface",
            "count": len(raw_items),
            "item_ids": item_ids,
        })

        return AgentResult(
            success=True,
            message=f"HuggingFace: {len(raw_items)} items collected",
            data={"item_ids": item_ids, "count": len(raw_items)},
        )
