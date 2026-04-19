from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone

from db.database import Database

logger = logging.getLogger(__name__)


def compute_topic_velocities(
    db: Database,
    window_hours: int = 24,
) -> list[dict]:
    """Count items per topic in the last `window_hours` vs the prior window.

    Returns `[{topic_id, topic_name, item_count, prev_count, velocity_ratio}]`.
    velocity_ratio = current / max(prev, 1). A topic with 5 items this 24h
    and 1 in the prior 24h has ratio 5.0 — "rising fast".

    Why: single-item ranks tell you what's hot right now, but topic velocity
    tells you *themes* accelerating — e.g. "Qwen mentions up 4× this week".
    """
    now = datetime.now(timezone.utc)
    current_cutoff = (now - timedelta(hours=window_hours)).isoformat()
    prev_cutoff = (now - timedelta(hours=2 * window_hours)).isoformat()

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT t.id AS topic_id,
                   t.name AS topic_name,
                   SUM(CASE WHEN i.first_seen >= ? THEN 1 ELSE 0 END) AS current_count,
                   SUM(CASE WHEN i.first_seen >= ? AND i.first_seen < ? THEN 1 ELSE 0 END) AS prev_count
            FROM topics t
            JOIN item_topics it ON it.topic_id = t.id
            JOIN items i ON i.id = it.item_id
            WHERE t.is_active = 1
            GROUP BY t.id, t.name
            HAVING current_count > 0
            """,
            (current_cutoff, prev_cutoff, current_cutoff),
        ).fetchall()

    results = []
    for r in rows:
        current = int(r["current_count"] or 0)
        prev = int(r["prev_count"] or 0)
        results.append({
            "topic_id": r["topic_id"],
            "topic_name": r["topic_name"],
            "item_count": current,
            "prev_count": prev,
            "velocity_ratio": current / max(prev, 1),
        })
    return results


def record_velocities(
    db: Database,
    velocities: list[dict],
    window_hours: int,
) -> int:
    """Persist a velocity snapshot. One row per topic.

    Returns the number of rows written.
    """
    if not velocities:
        return 0
    now_iso = datetime.now(timezone.utc).isoformat()
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO topic_velocity "
            "(topic_id, window_hours, item_count, prev_count, velocity_ratio, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (v["topic_id"], window_hours, v["item_count"], v["prev_count"],
                 v["velocity_ratio"], now_iso)
                for v in velocities
            ],
        )
        conn.commit()
    return len(velocities)
