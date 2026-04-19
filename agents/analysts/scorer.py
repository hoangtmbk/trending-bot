from __future__ import annotations
import json
import logging
from agents.base import BaseAgent, AgentContext, AgentResult
from db.queries import get_items, bulk_update_scores

logger = logging.getLogger(__name__)


class TrendScorer(BaseAgent):
    name = "scorer"
    schedule = "on_demand"  # triggered by scout events

    def execute(self, ctx: AgentContext) -> AgentResult:
        from scoring.momentum import compute_momentum_score, compute_final_score, normalize_by_source
        from scoring.dedup import deduplicate
        from scoring.prior import org_prior
        from models import RawItem
        from datetime import datetime, timedelta, timezone

        scoring_cfg = ctx.config.get("scoring", {})
        freshness_half_life = scoring_cfg.get("freshness_half_life_hours", 48)
        boost_config = scoring_cfg.get("cross_platform_boost", {2: 1.5, 3: 2.5, 4: 4.0})
        min_score = scoring_cfg.get("min_momentum_score", 0.3)
        priors_cfg = scoring_cfg.get("org_priors", {})

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

        # Fuzzy-title / URL deduplication to drive the cross-platform boost.
        # A paper seen on arxiv + hf_papers + hackernews counts as 3 sources.
        # `times_seen` counted same-URL re-observations only, which meant the
        # boost configured in config.yaml never actually fired.
        groups = deduplicate(raw_items)
        url_to_num_sources: dict[str, int] = {}
        for group in groups:
            n = min(len({it.source for it in group}), 4)
            for it in group:
                url_to_num_sources[it.url] = n

        # Build (momentum, final, url) tuples and flush in one commit.
        # Persisting `final` (percentile × freshness × cross-platform boost)
        # as normalized_score — the old code computed it then threw it away.
        now = datetime.now(timezone.utc)
        update_rows: list[tuple[float, float, str]] = []
        for db_item in db_items:
            url = db_item["url"]
            norm_score = normalized.get(url, 0.0)
            raw_score = raw_scores.get(url, 0.0)

            try:
                first_seen = datetime.fromisoformat(db_item["first_seen"])
                age_hours = (now - first_seen).total_seconds() / 3600
            except (ValueError, TypeError):
                age_hours = 24.0

            num_sources = url_to_num_sources.get(url, 1)
            prior = org_prior(url, priors_cfg)
            final = compute_final_score(
                momentum_score=norm_score,
                age_hours=age_hours,
                freshness_half_life=freshness_half_life,
                num_sources=num_sources,
                boost_config=boost_config,
                prior=prior,
            )
            update_rows.append((raw_score, final, url))

        updated = bulk_update_scores(ctx.db, update_rows)
        ctx.emit("scores_updated", {"count": updated})
        return AgentResult(success=True, message=f"Scored {updated} items",
                           data={"scored_count": updated})
