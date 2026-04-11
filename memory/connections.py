from __future__ import annotations
import logging
from db.database import Database

logger = logging.getLogger(__name__)


def get_related_items(db: Database, item_id: int) -> list[dict]:
    """Get all items related to the given item through connections."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT i.*, c.relationship, c.description as connection_desc "
            "FROM item_connections c "
            "JOIN items i ON (CASE WHEN c.item_a_id = ? THEN c.item_b_id ELSE c.item_a_id END) = i.id "
            "WHERE c.item_a_id = ? OR c.item_b_id = ? "
            "ORDER BY i.normalized_score DESC",
            (item_id, item_id, item_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_topic_graph(db: Database, topic_name: str) -> dict:
    """Get items and their connections for a specific topic."""
    with db.connect() as conn:
        # Get items in this topic
        items = [dict(r) for r in conn.execute(
            "SELECT i.* FROM items i "
            "JOIN item_topics it ON i.id = it.item_id "
            "JOIN topics t ON it.topic_id = t.id "
            "WHERE t.name = ? ORDER BY i.normalized_score DESC",
            (topic_name,),
        ).fetchall()]

        item_ids = {i["id"] for i in items}

        # Get connections between these items
        if item_ids:
            placeholders = ",".join("?" * len(item_ids))
            connections = [dict(r) for r in conn.execute(
                f"SELECT * FROM item_connections "
                f"WHERE item_a_id IN ({placeholders}) AND item_b_id IN ({placeholders})",
                list(item_ids) + list(item_ids),
            ).fetchall()]
        else:
            connections = []

    return {"items": items, "connections": connections}
