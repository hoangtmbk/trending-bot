from __future__ import annotations
import json
import logging
from db.database import Database
from db.queries import get_items, get_item_by_id

logger = logging.getLogger(__name__)


def get_item_context(db: Database, item_id: int) -> dict:
    """Get full context for an item: item + analyses + connections + score history."""
    item = get_item_by_id(db, item_id)
    if not item:
        return {}

    if item.get("raw_metrics"):
        item["raw_metrics"] = json.loads(item["raw_metrics"])

    with db.connect() as conn:
        # Analyses
        analyses = [dict(r) for r in conn.execute(
            "SELECT * FROM item_analysis WHERE item_id=? ORDER BY created_at DESC",
            (item_id,),
        ).fetchall()]
        for a in analyses:
            if a.get("content"):
                a["content"] = json.loads(a["content"])

        # Connections
        connections = [dict(r) for r in conn.execute(
            "SELECT c.*, ia.title as other_title FROM item_connections c "
            "JOIN items ia ON (CASE WHEN c.item_a_id = ? THEN c.item_b_id ELSE c.item_a_id END) = ia.id "
            "WHERE c.item_a_id = ? OR c.item_b_id = ?",
            (item_id, item_id, item_id),
        ).fetchall()]

        # Topics
        topics = [dict(r) for r in conn.execute(
            "SELECT t.name, it.confidence FROM item_topics it "
            "JOIN topics t ON it.topic_id = t.id WHERE it.item_id = ?",
            (item_id,),
        ).fetchall()]

        # Score history
        scores = [dict(r) for r in conn.execute(
            "SELECT * FROM item_scores WHERE item_id=? ORDER BY recorded_at ASC",
            (item_id,),
        ).fetchall()]

    return {
        "item": item,
        "analyses": analyses,
        "connections": connections,
        "topics": topics,
        "score_history": scores,
    }


def get_trending_summary(db: Database, days: int = 7, limit: int = 20) -> list[dict]:
    """Get a summary of trending items for the past N days with personal relevance."""
    from datetime import datetime, timedelta, timezone
    from memory.interests import compute_personal_relevance

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    items = get_items(db, since=since, limit=limit * 2, order_by="normalized_score DESC")

    # Enrich with personal relevance
    for item in items:
        item["personal_relevance"] = compute_personal_relevance(db, item["id"])
        item["effective_score"] = (item.get("normalized_score", 0) or 0) * item["personal_relevance"]

    # Re-sort by effective score
    items.sort(key=lambda x: x["effective_score"], reverse=True)
    return items[:limit]


def search_items(db: Database, query: str, limit: int = 20) -> list[dict]:
    """Search items by title or description."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM items WHERE title LIKE ? OR description LIKE ? "
            "ORDER BY normalized_score DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
    return [dict(r) for r in rows]
