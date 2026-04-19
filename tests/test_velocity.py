"""Tests for scoring.velocity — per-topic rolling-window counts."""
from datetime import datetime, timezone, timedelta
import pytest

from db.database import Database
from db.queries import upsert_item
from scoring.velocity import compute_topic_velocities, record_velocities


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.initialize()
    return d


def _create_topic(db, name="qwen"):
    with db.connect() as conn:
        conn.execute("INSERT INTO topics (name, created_at) VALUES (?, datetime('now'))", (name,))
        topic = conn.execute("SELECT id FROM topics WHERE name=?", (name,)).fetchone()
        conn.commit()
    return topic["id"]


def _tag(db, item_id, topic_id):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO item_topics (item_id, topic_id, confidence) VALUES (?, ?, 1.0)",
            (item_id, topic_id),
        )
        conn.commit()


def _backdate_first_seen(db, item_id: int, hours_ago: int):
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    with db.connect() as conn:
        conn.execute("UPDATE items SET first_seen=? WHERE id=?", (ts, item_id))
        conn.commit()


def test_rising_topic_reports_high_ratio(db):
    topic_id = _create_topic(db, "qwen")
    # 5 items in last 24h
    for i in range(5):
        iid = upsert_item(db, url=f"https://x.com/recent{i}",
                          title=f"Qwen news {i}", source="github",
                          description="", raw_metrics={})
        _backdate_first_seen(db, iid, hours_ago=2)
        _tag(db, iid, topic_id)
    # 1 item in prior 24h (24–48h ago)
    iid = upsert_item(db, url="https://x.com/older",
                      title="Older qwen", source="github",
                      description="", raw_metrics={})
    _backdate_first_seen(db, iid, hours_ago=30)
    _tag(db, iid, topic_id)

    results = compute_topic_velocities(db, window_hours=24)
    assert len(results) == 1
    r = results[0]
    assert r["topic_name"] == "qwen"
    assert r["item_count"] == 5
    assert r["prev_count"] == 1
    assert r["velocity_ratio"] == 5.0


def test_topics_without_items_excluded(db):
    _create_topic(db, "empty-topic")
    results = compute_topic_velocities(db, window_hours=24)
    assert results == []


def test_no_prev_window_ratio_equals_current_count(db):
    """Avoid ZeroDivisionError when prev_count=0."""
    topic_id = _create_topic(db, "brand-new")
    iid = upsert_item(db, url="https://x.com/a", title="A", source="github",
                      description="", raw_metrics={})
    _backdate_first_seen(db, iid, hours_ago=1)
    _tag(db, iid, topic_id)
    results = compute_topic_velocities(db, window_hours=24)
    assert results[0]["velocity_ratio"] == 1.0  # 1 / max(0, 1) = 1


def test_record_velocities_persists_rows(db):
    topic_id = _create_topic(db, "t")
    velocities = [{
        "topic_id": topic_id, "topic_name": "t",
        "item_count": 3, "prev_count": 1, "velocity_ratio": 3.0,
    }]
    n = record_velocities(db, velocities, window_hours=24)
    assert n == 1
    with db.connect() as conn:
        rows = list(conn.execute("SELECT * FROM topic_velocity"))
    assert len(rows) == 1
    assert rows[0]["item_count"] == 3
    assert rows[0]["velocity_ratio"] == 3.0


def test_record_empty_no_writes(db):
    assert record_velocities(db, [], window_hours=24) == 0
