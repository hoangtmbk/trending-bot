"""POST /api/items/{id}/action with bookmarked/dismissed adjusts
user_interests.weight for each topic attached to the item. Closes the
feedback loop: the more you bookmark one topic, the more scorer prefers
related items next cycle."""
import json
import pytest
from fastapi.testclient import TestClient

from db.database import Database
from db.queries import upsert_item
from interfaces.web.app import create_app


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.initialize()
    return d


@pytest.fixture
def client(db):
    return TestClient(create_app(db, config={}))


def _make_item_with_topic(db, topic_name="tool"):
    item_id = upsert_item(db, url="https://x.com/a", title="A", source="github",
                          description="", raw_metrics={})
    with db.connect() as conn:
        conn.execute("INSERT INTO topics (name, created_at) VALUES (?, datetime('now'))", (topic_name,))
        topic = conn.execute("SELECT id FROM topics WHERE name=?", (topic_name,)).fetchone()
        conn.execute(
            "INSERT INTO item_topics (item_id, topic_id, confidence) VALUES (?, ?, 1.0)",
            (item_id, topic["id"]),
        )
        conn.commit()
    return item_id, topic["id"]


def _weight(db, topic_id: int) -> float | None:
    with db.connect() as conn:
        row = conn.execute("SELECT weight FROM user_interests WHERE topic_id=?", (topic_id,)).fetchone()
    return row["weight"] if row else None


def test_bookmarked_creates_user_interest_at_1_1(db, client):
    item_id, topic_id = _make_item_with_topic(db)
    resp = client.post(f"/api/items/{item_id}/action", json={"action": "bookmarked"})
    assert resp.status_code == 200
    assert _weight(db, topic_id) == pytest.approx(1.1)


def test_dismissed_creates_user_interest_at_0_95(db, client):
    item_id, topic_id = _make_item_with_topic(db)
    resp = client.post(f"/api/items/{item_id}/action", json={"action": "dismissed"})
    assert resp.status_code == 200
    assert _weight(db, topic_id) == pytest.approx(0.95)


def test_repeated_bookmarks_accumulate(db, client):
    item_id, topic_id = _make_item_with_topic(db)
    for _ in range(5):
        client.post(f"/api/items/{item_id}/action", json={"action": "bookmarked"})
    # 1.0 + 5 × 0.1 = 1.5
    assert _weight(db, topic_id) == pytest.approx(1.5)


def test_weight_capped_at_5(db, client):
    item_id, topic_id = _make_item_with_topic(db)
    for _ in range(100):
        client.post(f"/api/items/{item_id}/action", json={"action": "bookmarked"})
    assert _weight(db, topic_id) == pytest.approx(5.0)


def test_weight_floored_at_0_1(db, client):
    item_id, topic_id = _make_item_with_topic(db)
    for _ in range(100):
        client.post(f"/api/items/{item_id}/action", json={"action": "dismissed"})
    assert _weight(db, topic_id) == pytest.approx(0.1)


def test_item_without_topics_is_noop(db, client):
    item_id = upsert_item(db, url="https://x.com/a", title="A", source="github",
                          description="", raw_metrics={})
    resp = client.post(f"/api/items/{item_id}/action", json={"action": "bookmarked"})
    assert resp.status_code == 200
    with db.connect() as conn:
        rows = list(conn.execute("SELECT * FROM user_interests"))
    assert rows == []


def test_deep_dive_request_action_does_not_adjust_weights(db, client):
    item_id, topic_id = _make_item_with_topic(db)
    client.post(f"/api/items/{item_id}/action", json={"action": "deep_dive_requested"})
    assert _weight(db, topic_id) is None
