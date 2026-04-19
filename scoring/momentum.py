from __future__ import annotations
import math
import logging
from collections import defaultdict
from datetime import datetime, timezone
from models import RawItem

logger = logging.getLogger(__name__)


def _hours_since(timestamp: str) -> float:
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        return max(delta.total_seconds() / 3600, 0.1)
    except (ValueError, TypeError):
        return 24.0


def compute_momentum_score(item: RawItem) -> float:
    m = item.metrics
    source = item.source

    if source == "github":
        stars = m.get("stargazers_count", 0)
        age_days = m.get("age_days", 365)
        return stars / max(age_days, 1)

    elif source == "reddit":
        score = m.get("score", 0)
        hours = _hours_since(item.timestamp)
        return score / hours

    elif source == "hackernews":
        points = m.get("points", 0)
        hours = _hours_since(item.timestamp)
        return points / hours

    elif source == "arxiv":
        citations = m.get("citation_count", 0)
        influential = m.get("influential_citations", 0)
        return citations + influential * 2

    elif source == "huggingface":
        downloads = m.get("downloads", 0)
        likes = m.get("likes", 0)
        return downloads / max(downloads, 100) + likes / max(likes, 10)

    elif source in {"blog", "newsletter"}:
        # No numeric signal — pure recency. Boost newsletters since they're
        # already curated, and lab-blog posts for known orgs (prior comes
        # from scoring/prior.py, applied later in compute_final_score).
        hours = _hours_since(item.timestamp)
        base = 2.0 if source == "newsletter" else 1.0
        return base / max(hours / 24.0, 0.1)

    else:
        logger.warning(f"Unknown source: {source}")
        return 0.0


def compute_final_score(
    momentum_score: float,
    age_hours: float,
    freshness_half_life: float,
    num_sources: int,
    boost_config: dict[int, float],
) -> float:
    freshness_decay = math.exp(-age_hours / freshness_half_life)
    boost = boost_config.get(num_sources, 1.0)
    if num_sources >= 4:
        boost = boost_config.get(4, 4.0)
    return momentum_score * freshness_decay * boost


def normalize_by_source(
    raw_items: list[RawItem],
    scores: dict[str, float],
) -> dict[str, float]:
    """Normalize raw momentum scores to 0-100 percentile rank within each source."""
    by_source: dict[str, list[RawItem]] = defaultdict(list)
    for item in raw_items:
        by_source[item.source].append(item)

    normalized: dict[str, float] = {}
    for src, items in by_source.items():
        items.sort(key=lambda x: scores.get(x.url, 0))
        n = len(items)
        for i, item in enumerate(items):
            percentile = (i / max(n - 1, 1)) * 100
            if item.url not in normalized or percentile > normalized[item.url]:
                normalized[item.url] = percentile
    return normalized
