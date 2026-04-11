from __future__ import annotations
import logging
from agents.base import BaseAgent, AgentContext, AgentResult
from db.queries import upsert_item, snapshot_score

logger = logging.getLogger(__name__)


class GitHubScout(BaseAgent):
    name = "github_scout"
    schedule = "0 */4 * * *"

    def execute(self, ctx: AgentContext) -> AgentResult:
        from collectors.github import GitHubCollector
        from config import get_env
        from scoring.momentum import compute_momentum_score

        sources_cfg = ctx.config.get("sources", {}).get("github", {})
        if not sources_cfg.get("enabled", False):
            return AgentResult(success=True, message="GitHub disabled in config")

        try:
            token = get_env("GITHUB_TOKEN")
        except EnvironmentError as e:
            return AgentResult(success=False, message=str(e))

        collector = GitHubCollector(
            token=token,
            topics=sources_cfg.get("topics"),
            min_stars_new=sources_cfg.get("min_stars_new_repo", 20),
            min_stars_established=sources_cfg.get("min_stars_established", 500),
        )

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
            "source": "github",
            "count": len(raw_items),
            "item_ids": item_ids,
        })

        return AgentResult(
            success=True,
            message=f"GitHub: {len(raw_items)} items collected",
            data={"item_ids": item_ids, "count": len(raw_items)},
        )
