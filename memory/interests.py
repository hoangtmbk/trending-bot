from __future__ import annotations
import logging
from db.database import Database

logger = logging.getLogger(__name__)


def get_interest_profile(db: Database) -> dict[str, float]:
    """Return {topic_name: weight} for all topics with user interest."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT t.name, ui.weight FROM topics t "
            "JOIN user_interests ui ON t.id = ui.topic_id "
            "WHERE t.is_active = 1 ORDER BY ui.weight DESC"
        ).fetchall()
    return {row["name"]: row["weight"] for row in rows}


def set_interest(db: Database, topic_name: str, weight: float, source: str = "explicit") -> None:
    """Set interest weight for a topic. Creates topic if needed."""
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO topics (name, source, created_at) VALUES (?, ?, datetime('now'))",
            (topic_name, "user" if source == "explicit" else "llm-inferred"),
        )
        topic = conn.execute("SELECT id FROM topics WHERE name=?", (topic_name,)).fetchone()
        if topic:
            existing = conn.execute(
                "SELECT id FROM user_interests WHERE topic_id=?", (topic["id"],)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE user_interests SET weight=?, source=?, updated_at=datetime('now') "
                    "WHERE id=?",
                    (weight, source, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO user_interests (topic_id, weight, source, updated_at) "
                    "VALUES (?, ?, ?, datetime('now'))",
                    (topic["id"], weight, source),
                )
        conn.commit()


def apply_feedback_boost(db: Database, item_id: int, action: str) -> None:
    """Adjust topic weights based on user action on an item.
    bookmark -> boost topics +0.2
    dismissed -> decay topics -0.1
    """
    deltas = {"bookmarked": 0.2, "dismissed": -0.1}
    delta = deltas.get(action, 0)
    if delta == 0:
        return

    with db.connect() as conn:
        # Get topics for this item
        topics = conn.execute(
            "SELECT it.topic_id, t.name, COALESCE(ui.weight, 1.0) as current_weight "
            "FROM item_topics it "
            "JOIN topics t ON it.topic_id = t.id "
            "LEFT JOIN user_interests ui ON t.id = ui.topic_id "
            "WHERE it.item_id = ?",
            (item_id,),
        ).fetchall()

        for topic in topics:
            new_weight = max(0.0, min(3.0, topic["current_weight"] + delta))
            existing = conn.execute(
                "SELECT id FROM user_interests WHERE topic_id=?", (topic["topic_id"],)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE user_interests SET weight=?, source='inferred', updated_at=datetime('now') "
                    "WHERE id=?",
                    (new_weight, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO user_interests (topic_id, weight, source, updated_at) "
                    "VALUES (?, ?, 'inferred', datetime('now'))",
                    (topic["topic_id"], new_weight),
                )
        conn.commit()
        if topics:
            logger.info(f"Adjusted {len(topics)} topic weights by {delta:+.1f} for item {item_id}")


def compute_personal_relevance(db: Database, item_id: int) -> float:
    """Compute personal relevance score for an item based on user interests.
    Returns max topic weight for the item's topics, or 1.0 if no topics.
    """
    with db.connect() as conn:
        row = conn.execute(
            "SELECT MAX(COALESCE(ui.weight, 1.0)) as max_weight "
            "FROM item_topics it "
            "LEFT JOIN user_interests ui ON it.topic_id = ui.topic_id "
            "WHERE it.item_id = ?",
            (item_id,),
        ).fetchone()
    return row["max_weight"] if row and row["max_weight"] is not None else 1.0
