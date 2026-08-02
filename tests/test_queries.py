import json
import pytest
from pathlib import Path
from db.database import Database
from datetime import datetime, timezone, timedelta
from db.queries import (
    upsert_item,
    get_item_by_url,
    get_item_by_id,
    get_items,
    get_items_with_filter,
    snapshot_score,
    get_score_history,
    enqueue_task,
    claim_next_task,
    complete_task,
    fail_task,
    get_pending_tasks,
    has_active_task,
    reset_stuck_tasks,
    bulk_update_scores,
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


def test_reset_stuck_tasks_marks_old_running_as_failed(db):
    """Tasks left in 'running' past the cutoff should be reset to 'failed'."""
    stuck_id = enqueue_task(db, agent_type="scorer", payload={})
    fresh_id = enqueue_task(db, agent_type="scorer", payload={})

    long_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    just_now = datetime.now(timezone.utc).isoformat()
    with db.connect() as conn:
        conn.execute("UPDATE task_queue SET status='running', started_at=? WHERE id=?",
                     (long_ago, stuck_id))
        conn.execute("UPDATE task_queue SET status='running', started_at=? WHERE id=?",
                     (just_now, fresh_id))
        conn.commit()

    reset_count = reset_stuck_tasks(db, max_age_seconds=3600)
    assert reset_count == 1

    with db.connect() as conn:
        rows = {r["id"]: dict(r) for r in conn.execute(
            "SELECT id, status, error FROM task_queue").fetchall()}
    assert rows[stuck_id]["status"] == "failed"
    assert "stuck" in rows[stuck_id]["error"]
    assert rows[fresh_id]["status"] == "running"


def test_reset_stuck_tasks_handles_null_started_at(db):
    """Defensive: rows with status='running' but no started_at are treated as stuck."""
    task_id = enqueue_task(db, agent_type="scorer", payload={})
    with db.connect() as conn:
        conn.execute(
            "UPDATE task_queue SET status='running', started_at=NULL WHERE id=?",
            (task_id,),
        )
        conn.commit()

    reset_count = reset_stuck_tasks(db, max_age_seconds=3600)
    assert reset_count == 1

    with db.connect() as conn:
        row = conn.execute(
            "SELECT status FROM task_queue WHERE id=?", (task_id,)
        ).fetchone()
    assert row["status"] == "failed"


def test_reset_stuck_tasks_no_op_when_clean(db):
    enqueue_task(db, agent_type="scorer", payload={})  # pending
    assert reset_stuck_tasks(db) == 0


class TestHasActiveTask:
    """has_active_task returns True iff a pending or running task of the given
    type exists. Used by event-driven debounce in main.py — see scorer
    re-entrance issue in review 2026-04-19."""

    def test_false_on_empty(self, db):
        assert has_active_task(db, "scorer") is False

    def test_true_for_pending(self, db):
        enqueue_task(db, agent_type="scorer", payload={})
        assert has_active_task(db, "scorer") is True

    def test_true_for_running(self, db):
        enqueue_task(db, agent_type="scorer", payload={})
        claim_next_task(db, agent_type="scorer")  # → running
        assert has_active_task(db, "scorer") is True

    def test_false_after_completion(self, db):
        enqueue_task(db, agent_type="scorer", payload={})
        task = claim_next_task(db, agent_type="scorer")
        complete_task(db, task["id"])
        assert has_active_task(db, "scorer") is False

    def test_scopes_by_agent_type(self, db):
        enqueue_task(db, agent_type="filter", payload={})
        assert has_active_task(db, "scorer") is False
        assert has_active_task(db, "filter") is True


class TestBulkUpdateScores:
    """bulk_update_scores rewrites momentum_score + normalized_score in one
    commit. Replaces the N-commit hot-path in the scorer — see review 2026-04-19."""

    def test_updates_existing_rows(self, db):
        id1 = upsert_item(db, url="https://a.com", title="A", source="github",
                          description="", raw_metrics={})
        id2 = upsert_item(db, url="https://b.com", title="B", source="reddit",
                          description="", raw_metrics={})
        n = bulk_update_scores(db, [
            (0.9, 87.5, "https://a.com"),
            (0.4, 42.0, "https://b.com"),
        ])
        assert n == 2
        a = get_item_by_id(db, id1)
        b = get_item_by_id(db, id2)
        assert a["momentum_score"] == 0.9
        assert a["normalized_score"] == 87.5
        assert b["momentum_score"] == 0.4
        assert b["normalized_score"] == 42.0

    def test_empty_rows_is_noop(self, db):
        assert bulk_update_scores(db, []) == 0

    def test_bulk_faster_than_per_row_upsert(self, db):
        """Functional smoke: 200 bulk updates complete in <200ms, demonstrating
        the single-commit path. Per-row upsert_item calls fsync each commit and
        take far longer. Keeps us from regressing back to the N-commit pattern."""
        import time
        for i in range(200):
            upsert_item(db, url=f"https://x.com/{i}", title=f"T{i}",
                        source="github", description="", raw_metrics={})
        rows = [(0.1 * i, float(i), f"https://x.com/{i}") for i in range(200)]
        t0 = time.monotonic()
        bulk_update_scores(db, rows)
        elapsed = time.monotonic() - t0
        assert elapsed < 1.0, f"bulk update should be fast, took {elapsed:.2f}s"

    def test_missing_url_is_skipped(self, db):
        """UPDATE on a non-existent URL affects zero rows but doesn't error."""
        upsert_item(db, url="https://a.com", title="A", source="github",
                    description="", raw_metrics={})
        n = bulk_update_scores(db, [
            (0.9, 87.5, "https://a.com"),
            (0.5, 50.0, "https://missing.com"),
        ])
        # Returns rows attempted, not rows matched. Callers treat input as authoritative.
        assert n == 2
        a = get_item_by_url(db, "https://a.com")
        assert a["normalized_score"] == 87.5


def _import_bulk_update_scores_symbol_present():
    # Regression: scorer imports bulk_update_scores from db.queries.
    from db.queries import bulk_update_scores  # noqa: F401


# ── get_items_with_filter: recency-blended ranking + unbounded listing ──

def _seed_filtered_item(db, *, url, title, interest_score, age_days=0.0,
                        normalized_score=10.0, source="hackernews"):
    """Insert an item with a filter verdict, backdating last_seen by age_days."""
    item_id = upsert_item(db, url=url, title=title, source=source,
                          description="", raw_metrics={},
                          normalized_score=normalized_score)
    seen = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
    with db.connect() as conn:
        conn.execute("UPDATE items SET first_seen=?, last_seen=? WHERE id=?",
                     (seen, seen, item_id))
        conn.execute(
            "INSERT INTO item_analysis (item_id, analysis_type, created_at, content) "
            "VALUES (?, 'filter', ?, ?)",
            (item_id, seen, json.dumps({
                "novel": True, "ai_relevant": True,
                "interest_score": interest_score,
                "summary": f"Summary for {title}", "category": "model",
            })),
        )
        conn.commit()
    return item_id


class TestGetItemsWithFilterRecency:
    def test_fresh_item_outranks_older_item_with_higher_interest_score(self, db):
        """A 60-day-old 10/10 must not outrank a same-day 9/10.

        This is the dashboard staleness bug: interest_score is a coarse 1-10
        integer, so without decay the handful of all-time 10s pin the top of
        the list forever.
        """
        _seed_filtered_item(db, url="https://old.example/erdos", title="Old Ten",
                            interest_score=10, age_days=60)
        _seed_filtered_item(db, url="https://new.example/today", title="Fresh Nine",
                            interest_score=9, age_days=0)

        items = get_items_with_filter(db, limit=10, min_interest=6)

        assert [i["title"] for i in items] == ["Fresh Nine", "Old Ten"]

    def test_equal_interest_scores_order_by_recency(self, db):
        _seed_filtered_item(db, url="https://a.example/1", title="Older",
                            interest_score=8, age_days=10)
        _seed_filtered_item(db, url="https://b.example/2", title="Newer",
                            interest_score=8, age_days=1)

        items = get_items_with_filter(db, limit=10, min_interest=6)

        assert [i["title"] for i in items] == ["Newer", "Older"]

    def test_interest_score_still_leads_among_equally_fresh_items(self, db):
        """Decay must not swamp quality: same-day items rank by interest_score."""
        _seed_filtered_item(db, url="https://c.example/1", title="Good",
                            interest_score=7, age_days=0)
        _seed_filtered_item(db, url="https://d.example/2", title="Great",
                            interest_score=9, age_days=0)

        items = get_items_with_filter(db, limit=10, min_interest=6)

        assert [i["title"] for i in items] == ["Great", "Good"]

    def test_rank_score_is_exposed_to_callers(self, db):
        _seed_filtered_item(db, url="https://e.example/1", title="Only",
                            interest_score=8, age_days=0)

        items = get_items_with_filter(db, limit=10, min_interest=6)

        # Fresh item: rank_score ≈ interest_score (no decay applied yet).
        assert items[0]["rank_score"] == pytest.approx(8.0, abs=0.1)


class TestGetItemsWithFilterUnbounded:
    def test_limit_none_returns_every_eligible_item(self, db):
        for n in range(45):
            _seed_filtered_item(db, url=f"https://bulk.example/{n}",
                                title=f"Item {n}", interest_score=7, age_days=n)

        items = get_items_with_filter(db, limit=None, min_interest=6)

        assert len(items) == 45

    def test_limit_none_still_applies_the_min_interest_gate(self, db):
        _seed_filtered_item(db, url="https://f.example/keep", title="Keep",
                            interest_score=8, age_days=0)
        _seed_filtered_item(db, url="https://f.example/drop", title="Drop",
                            interest_score=3, age_days=0)

        items = get_items_with_filter(db, limit=None, min_interest=6)

        assert [i["title"] for i in items] == ["Keep"]
