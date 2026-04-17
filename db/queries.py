from __future__ import annotations
import json
import logging
from datetime import datetime, timezone

from db.database import Database

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- Items --

def upsert_item(
    db: Database,
    url: str,
    title: str,
    source: str,
    description: str = "",
    source_id: str | None = None,
    raw_metrics: dict | None = None,
    momentum_score: float = 0.0,
    normalized_score: float = 0.0,
) -> int:
    now = _now_iso()
    metrics_json = json.dumps(raw_metrics or {})
    with db.connect() as conn:
        existing = conn.execute("SELECT id, times_seen FROM items WHERE url=?", (url,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE items SET title=?, description=?, last_seen=?, times_seen=?, "
                "raw_metrics=?, momentum_score=?, normalized_score=? WHERE id=?",
                (title, description, now, existing["times_seen"] + 1,
                 metrics_json, momentum_score, normalized_score, existing["id"]),
            )
            conn.commit()
            return existing["id"]
        else:
            cursor = conn.execute(
                "INSERT INTO items (url, title, source, source_id, description, "
                "first_seen, last_seen, raw_metrics, momentum_score, normalized_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (url, title, source, source_id, description,
                 now, now, metrics_json, momentum_score, normalized_score),
            )
            conn.commit()
            return cursor.lastrowid


def get_item_by_id(db: Database, item_id: int) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    return dict(row) if row else None


def get_item_by_url(db: Database, url: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM items WHERE url=?", (url,)).fetchone()
    return dict(row) if row else None


_ALLOWED_ORDER_COLUMNS = {
    "last_seen", "first_seen", "normalized_score", "momentum_score",
    "times_seen", "id", "title", "source",
}
_ALLOWED_DIRECTIONS = {"ASC", "DESC"}


def get_items(
    db: Database,
    source: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int | None = None,
    order_by: str = "last_seen DESC",
) -> list[dict]:
    parts = order_by.strip().split()
    col = parts[0] if parts else "last_seen"
    direction = parts[1].upper() if len(parts) > 1 else "DESC"
    if col not in _ALLOWED_ORDER_COLUMNS or direction not in _ALLOWED_DIRECTIONS:
        col, direction = "last_seen", "DESC"

    query = "SELECT * FROM items WHERE 1=1"
    params: list = []

    if source:
        query += " AND source=?"
        params.append(source)
    if status:
        query += " AND status=?"
        params.append(status)
    if since:
        query += " AND last_seen >= ?"
        params.append(since)

    query += f" ORDER BY {col} {direction}"

    if limit:
        query += " LIMIT ?"
        params.append(limit)

    with db.connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


# -- Score History --

def snapshot_score(
    db: Database,
    item_id: int,
    momentum_score: float,
    normalized_score: float,
    raw_metrics: dict | None = None,
) -> int:
    now = _now_iso()
    metrics_json = json.dumps(raw_metrics or {})
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT INTO item_scores (item_id, recorded_at, momentum_score, "
            "normalized_score, raw_metrics) VALUES (?, ?, ?, ?, ?)",
            (item_id, now, momentum_score, normalized_score, metrics_json),
        )
        conn.commit()
        return cursor.lastrowid


def get_score_history(db: Database, item_id: int) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM item_scores WHERE item_id=? ORDER BY recorded_at ASC",
            (item_id,),
        ).fetchall()
    return [dict(row) for row in rows]


# -- Task Queue --

def enqueue_task(
    db: Database,
    agent_type: str,
    payload: dict,
    priority: int = 0,
) -> int:
    now = _now_iso()
    payload_json = json.dumps(payload)
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT INTO task_queue (agent_type, payload, priority, created_at) "
            "VALUES (?, ?, ?, ?)",
            (agent_type, payload_json, priority, now),
        )
        conn.commit()
        return cursor.lastrowid


def claim_next_task(db: Database, agent_type: str | None = None) -> dict | None:
    now = _now_iso()
    with db.connect() as conn:
        query = "SELECT * FROM task_queue WHERE status='pending'"
        params: list = []
        if agent_type:
            query += " AND agent_type=?"
            params.append(agent_type)
        query += " ORDER BY priority DESC, created_at ASC LIMIT 1"

        row = conn.execute(query, params).fetchone()
        if not row:
            return None
        task = dict(row)
        conn.execute(
            "UPDATE task_queue SET status='running', started_at=? WHERE id=?",
            (now, task["id"]),
        )
        conn.commit()
    return task


def complete_task(db: Database, task_id: int, result: dict | None = None) -> None:
    now = _now_iso()
    result_json = json.dumps(result) if result else None
    with db.connect() as conn:
        conn.execute(
            "UPDATE task_queue SET status='completed', completed_at=?, result=? WHERE id=?",
            (now, result_json, task_id),
        )
        conn.commit()


def fail_task(db: Database, task_id: int, error: str) -> None:
    now = _now_iso()
    with db.connect() as conn:
        conn.execute(
            "UPDATE task_queue SET status='failed', completed_at=?, error=? WHERE id=?",
            (now, error, task_id),
        )
        conn.commit()


def promote_item_to_tracking(db: Database, item_id: int) -> None:
    """Promote an item from 'new' → 'tracking'. No-op if already tracking/archived/dismissed."""
    with db.connect() as conn:
        conn.execute(
            "UPDATE items SET status='tracking' WHERE id=? AND status='new'",
            (item_id,),
        )
        conn.commit()


def reset_stuck_tasks(db: Database, max_age_seconds: int = 3600) -> int:
    """Mark tasks that have been in 'running' for too long as 'failed'.

    Why: if the process dies mid-task, the row stays 'running' forever and
    blocks any sane retry/observability. Run on dispatcher startup.
    """
    now = _now_iso()
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_seconds
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, started_at FROM task_queue WHERE status='running'"
        ).fetchall()
        stale_ids: list[int] = []
        for row in rows:
            started = row["started_at"]
            if not started:
                stale_ids.append(row["id"])
                continue
            try:
                ts = datetime.fromisoformat(started).timestamp()
            except ValueError:
                stale_ids.append(row["id"])
                continue
            if ts < cutoff:
                stale_ids.append(row["id"])

        for tid in stale_ids:
            conn.execute(
                "UPDATE task_queue SET status='failed', completed_at=?, "
                "error='reset on startup: task was stuck in running' WHERE id=?",
                (now, tid),
            )
        conn.commit()
    return len(stale_ids)


def get_pending_tasks(db: Database, agent_type: str | None = None) -> list[dict]:
    with db.connect() as conn:
        query = "SELECT * FROM task_queue WHERE status='pending'"
        params: list = []
        if agent_type:
            query += " AND agent_type=?"
            params.append(agent_type)
        query += " ORDER BY priority DESC, created_at ASC"
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
