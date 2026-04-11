import json
import pytest
from pathlib import Path
from db.database import Database
from db.queries import (
    upsert_item,
    get_item_by_url,
    get_item_by_id,
    get_items,
    snapshot_score,
    get_score_history,
    enqueue_task,
    claim_next_task,
    complete_task,
    fail_task,
    get_pending_tasks,
)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    database.initialize()
    return database


def test_upsert_item_creates_new(db):
    item_id = upsert_item(
        db,
        url="https://github.com/example/repo",
        title="Example Repo",
        source="github",
        description="An example",
        raw_metrics={"stars": 100},
    )
    assert item_id is not None
    item = get_item_by_id(db, item_id)
    assert item["title"] == "Example Repo"
    assert item["source"] == "github"
    assert item["times_seen"] == 1
    assert json.loads(item["raw_metrics"]) == {"stars": 100}


def test_upsert_item_updates_existing(db):
    item_id_1 = upsert_item(
        db,
        url="https://github.com/example/repo",
        title="Example Repo",
        source="github",
        description="An example",
        raw_metrics={"stars": 100},
    )
    item_id_2 = upsert_item(
        db,
        url="https://github.com/example/repo",
        title="Example Repo Updated",
        source="github",
        description="An example updated",
        raw_metrics={"stars": 500},
    )
    assert item_id_1 == item_id_2
    item = get_item_by_id(db, item_id_1)
    assert item["title"] == "Example Repo Updated"
    assert item["times_seen"] == 2
    assert json.loads(item["raw_metrics"]) == {"stars": 500}


def test_get_item_by_url(db):
    upsert_item(db, url="https://a.com", title="A", source="github",
                description="", raw_metrics={})
    item = get_item_by_url(db, "https://a.com")
    assert item is not None
    assert item["title"] == "A"


def test_get_item_by_url_not_found(db):
    item = get_item_by_url(db, "https://doesnotexist.com")
    assert item is None


def test_get_items_filters_by_source(db):
    upsert_item(db, url="https://a.com", title="A", source="github",
                description="", raw_metrics={})
    upsert_item(db, url="https://b.com", title="B", source="reddit",
                description="", raw_metrics={})
    github_items = get_items(db, source="github")
    assert len(github_items) == 1
    assert github_items[0]["source"] == "github"


def test_get_items_filters_by_status(db):
    item_id = upsert_item(db, url="https://a.com", title="A", source="github",
                          description="", raw_metrics={})
    with db.connect() as conn:
        conn.execute("UPDATE items SET status='tracking' WHERE id=?", (item_id,))
        conn.commit()
    new_items = get_items(db, status="new")
    tracking_items = get_items(db, status="tracking")
    assert len(new_items) == 0
    assert len(tracking_items) == 1


def test_get_items_with_limit(db):
    for i in range(10):
        upsert_item(db, url=f"https://{i}.com", title=f"Item {i}",
                    source="github", description="", raw_metrics={})
    items = get_items(db, limit=3)
    assert len(items) == 3


def test_get_items_since(db):
    upsert_item(db, url="https://old.com", title="Old", source="github",
                description="", raw_metrics={})
    with db.connect() as conn:
        conn.execute("UPDATE items SET last_seen='2026-01-01T00:00:00Z' WHERE url='https://old.com'")
        conn.commit()
    upsert_item(db, url="https://new.com", title="New", source="github",
                description="", raw_metrics={})
    items = get_items(db, since="2026-04-01T00:00:00Z")
    assert len(items) == 1
    assert items[0]["title"] == "New"


def test_snapshot_score(db):
    item_id = upsert_item(db, url="https://a.com", title="A", source="github",
                          description="", raw_metrics={})
    snapshot_score(db, item_id, momentum_score=0.8, normalized_score=75.0,
                   raw_metrics={"stars": 200})
    history = get_score_history(db, item_id)
    assert len(history) == 1
    assert history[0]["momentum_score"] == 0.8
    assert history[0]["normalized_score"] == 75.0


def test_score_history_ordered_by_time(db):
    item_id = upsert_item(db, url="https://a.com", title="A", source="github",
                          description="", raw_metrics={})
    snapshot_score(db, item_id, momentum_score=0.5, normalized_score=50.0,
                   raw_metrics={})
    snapshot_score(db, item_id, momentum_score=0.9, normalized_score=90.0,
                   raw_metrics={})
    history = get_score_history(db, item_id)
    assert len(history) == 2
    assert history[0]["momentum_score"] == 0.5
    assert history[1]["momentum_score"] == 0.9


# -- Task Queue --

def test_enqueue_task(db):
    task_id = enqueue_task(db, agent_type="deep_diver",
                           payload={"item_id": 1, "url": "https://a.com"})
    assert task_id is not None
    tasks = get_pending_tasks(db)
    assert len(tasks) == 1
    assert tasks[0]["agent_type"] == "deep_diver"
    assert json.loads(tasks[0]["payload"]) == {"item_id": 1, "url": "https://a.com"}


def test_claim_next_task(db):
    enqueue_task(db, agent_type="deep_diver", payload={"url": "https://a.com"})
    task = claim_next_task(db)
    assert task is not None
    assert task["status"] == "pending"  # returned before status update visible
    # verify it's now running in DB
    with db.connect() as conn:
        row = conn.execute("SELECT status FROM task_queue WHERE id=?",
                           (task["id"],)).fetchone()
    assert row["status"] == "running"


def test_claim_next_task_filters_by_agent_type(db):
    enqueue_task(db, agent_type="deep_diver", payload={"a": 1})
    enqueue_task(db, agent_type="topic_tracker", payload={"b": 2})
    task = claim_next_task(db, agent_type="topic_tracker")
    assert task is not None
    assert task["agent_type"] == "topic_tracker"


def test_claim_next_task_returns_none_when_empty(db):
    task = claim_next_task(db)
    assert task is None


def test_claim_next_task_respects_priority(db):
    enqueue_task(db, agent_type="deep_diver", payload={"low": True}, priority=0)
    enqueue_task(db, agent_type="deep_diver", payload={"high": True}, priority=10)
    task = claim_next_task(db)
    assert json.loads(task["payload"]) == {"high": True}


def test_complete_task(db):
    task_id = enqueue_task(db, agent_type="deep_diver", payload={})
    claim_next_task(db)
    complete_task(db, task_id, result={"status": "done"})
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM task_queue WHERE id=?", (task_id,)).fetchone()
    assert row["status"] == "completed"
    assert json.loads(row["result"]) == {"status": "done"}
    assert row["completed_at"] is not None


def test_fail_task(db):
    task_id = enqueue_task(db, agent_type="deep_diver", payload={})
    claim_next_task(db)
    fail_task(db, task_id, error="Connection timeout")
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM task_queue WHERE id=?", (task_id,)).fetchone()
    assert row["status"] == "failed"
    assert row["error"] == "Connection timeout"


def test_completed_tasks_not_in_pending(db):
    task_id = enqueue_task(db, agent_type="deep_diver", payload={})
    claim_next_task(db)
    complete_task(db, task_id, result={})
    pending = get_pending_tasks(db)
    assert len(pending) == 0
