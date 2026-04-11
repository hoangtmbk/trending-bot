from __future__ import annotations
import json
import logging
from agents.base import BaseAgent, AgentContext, AgentResult
from db.queries import get_items, upsert_item

logger = logging.getLogger(__name__)


class TrendScorer(BaseAgent):
    name = "scorer"
    schedule = "on_demand"  # triggered by scout events

    def execute(self, ctx: AgentContext) -> AgentResult:
        from scoring.momentum import compute_momentum_score, compute_final_score, normalize_by_source
        from models import RawItem
        from datetime import datetime, timedelta, timezone

        scoring_cfg = ctx.config.get("scoring", {})
        freshness_half_life = scoring_cfg.get("freshness_half_life_hours", 48)
        boost_config = scoring_cfg.get("cross_platform_boost", {2: 1.5, 3: 2.5, 4: 4.0})
        min_score = scoring_cfg.get("min_momentum_score", 0.3)

        # Get all items seen in last 48 hours
        since = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        db_items = get_items(ctx.db, since=since)

        if not db_items:
            return AgentResult(success=True, message="No recent items to score")

        # Convert DB items back to RawItem for existing scoring functions
        raw_items = []
        for db_item in db_items:
            metrics = json.loads(db_item["raw_metrics"]) if db_item["raw_metrics"] else {}
            raw = RawItem(
                title=db_item["title"],
                url=db_item["url"],
                source=db_item["source"],
                description=db_item.get("description", ""),
                metrics=metrics,
                timestamp=db_item["last_seen"],
            )
            raw_items.append(raw)

        # Compute momentum scores
        raw_scores = {}
        for item in raw_items:
            score = compute_momentum_score(item)
            if item.url not in raw_scores or score > raw_scores[item.url]:
                raw_scores[item.url] = score

        # Normalize per source
        normalized = normalize_by_source(raw_items, raw_scores)

        # Compute final scores with actual age from first_seen
        updated = 0
        for db_item in db_items:
            url = db_item["url"]
            norm_score = normalized.get(url, 0.0)
            raw_score = raw_scores.get(url, 0.0)

            # Compute actual age in hours from first_seen
            try:
                first_seen = datetime.fromisoformat(db_item["first_seen"])
                age_hours = (datetime.now(timezone.utc) - first_seen).total_seconds() / 3600
            except (ValueError, TypeError):
                age_hours = 24.0

            # Count sources (times_seen > 1 could indicate cross-platform)
            num_sources = db_item.get("times_seen", 1)
            # Cap at reasonable value for boost
            num_sources = min(num_sources, 4)

            final = compute_final_score(
                momentum_score=norm_score,
                age_hours=age_hours,
                freshness_half_life=freshness_half_life,
                num_sources=num_sources,
                boost_config=boost_config,
            )

            # Update DB with new scores
            upsert_item(
                ctx.db,
                url=url,
                title=db_item["title"],
                source=db_item["source"],
                description=db_item.get("description", ""),
                raw_metrics=json.loads(db_item["raw_metrics"]) if db_item["raw_metrics"] else {},
                momentum_score=raw_score,
                normalized_score=norm_score,
            )
            updated += 1

        ctx.emit("scores_updated", {"count": updated})
        return AgentResult(success=True, message=f"Scored {updated} items",
                           data={"scored_count": updated})
