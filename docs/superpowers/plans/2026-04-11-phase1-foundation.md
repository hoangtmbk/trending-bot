# Phase 1: Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation layer — SQLite database, BaseAgent, orchestrator (scheduler + event bus + dispatcher), and a new entry point — so that all subsequent phases (scouts, analysts, researchers, interfaces) have infrastructure to plug into.

**Architecture:** A long-running Python process with APScheduler for scheduled agent runs, an in-process event bus for agent communication, and a task queue backed by SQLite for async work. The existing pipeline continues to work unchanged during this phase.

**Tech Stack:** Python 3.11+, SQLite (stdlib `sqlite3` + `aiosqlite`), APScheduler 3.x, asyncio

**Spec:** `docs/superpowers/specs/2026-04-11-agent-team-assistant-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `db/__init__.py` | Create | Package init |
| `db/schema.sql` | Create | Full SQLite schema (all tables, indexes) |
| `db/database.py` | Create | Database class: init, migrate, connection context manager |
| `db/queries.py` | Create | Named query functions for items, scores, tasks, etc. |
| `agents/__init__.py` | Create | Package init |
| `agents/base.py` | Create | BaseAgent abstract class with schedule, run, event hooks |
| `orchestrator/__init__.py` | Create | Package init |
| `orchestrator/events.py` | Create | EventBus: subscribe, emit, async dispatch |
| `orchestrator/dispatcher.py` | Create | TaskDispatcher: poll task_queue, run agents, update status |
| `orchestrator/scheduler.py` | Create | AgentScheduler: APScheduler wrapper, register agents |
| `orchestrator/app.py` | Create | Application: start/stop scheduler + dispatcher, graceful shutdown |
| `requirements.txt` | Modify | Add `apscheduler`, `aiosqlite` |
| `config.yaml` | Modify | Add `agents` and `orchestrator` sections |
| `config.py` | Modify | Add agent/orchestrator defaults |
| `tests/test_database.py` | Create | Tests for DB init, migrations, connection management |
| `tests/test_queries.py` | Create | Tests for all query functions |
| `tests/test_base_agent.py` | Create | Tests for BaseAgent lifecycle |
| `tests/test_events.py` | Create | Tests for EventBus |
| `tests/test_dispatcher.py` | Create | Tests for TaskDispatcher |
| `tests/test_scheduler.py` | Create | Tests for AgentScheduler |

---

### Task 1: SQLite Schema

**Files:**
- Create: `db/__init__.py`
- Create: `db/schema.sql`

- [ ] **Step 1: Create db package**

```bash
mkdir -p db
```

- [ ] **Step 2: Create `db/__init__.py`**

```python
```

(Empty file — package marker only.)

- [ ] **Step 3: Create `db/schema.sql`**

```sql
-- TrendBot SQLite Schema
-- Version: 1

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    source          TEXT NOT NULL,
    source_id       TEXT,
    description     TEXT DEFAULT '',
    first_seen      TEXT NOT NULL,  -- ISO 8601
    last_seen       TEXT NOT NULL,  -- ISO 8601
    times_seen      INTEGER DEFAULT 1,
    raw_metrics     TEXT,           -- JSON
    momentum_score  REAL DEFAULT 0.0,
    normalized_score REAL DEFAULT 0.0,
    status          TEXT DEFAULT 'new' CHECK(status IN ('new', 'tracking', 'archived', 'dismissed'))
);

CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_last_seen ON items(last_seen);
CREATE INDEX IF NOT EXISTS idx_items_normalized_score ON items(normalized_score);

CREATE TABLE IF NOT EXISTS item_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    recorded_at     TEXT NOT NULL,  -- ISO 8601
    momentum_score  REAL,
    normalized_score REAL,
    raw_metrics     TEXT           -- JSON snapshot
);

CREATE INDEX IF NOT EXISTS idx_item_scores_item_id ON item_scores(item_id);
CREATE INDEX IF NOT EXISTS idx_item_scores_recorded_at ON item_scores(recorded_at);

CREATE TABLE IF NOT EXISTS item_analysis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    analysis_type   TEXT NOT NULL CHECK(analysis_type IN ('filter', 'deep_dive', 'connection', 'topic_report')),
    created_at      TEXT NOT NULL,  -- ISO 8601
    content         TEXT NOT NULL,  -- JSON
    prompt_version  TEXT
);

CREATE INDEX IF NOT EXISTS idx_item_analysis_item_id ON item_analysis(item_id);
CREATE INDEX IF NOT EXISTS idx_item_analysis_type ON item_analysis(analysis_type);

CREATE TABLE IF NOT EXISTS topics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,
    description     TEXT DEFAULT '',
    source          TEXT DEFAULT 'system' CHECK(source IN ('system', 'user', 'llm-inferred')),
    created_at      TEXT NOT NULL,  -- ISO 8601
    is_active       INTEGER DEFAULT 1  -- SQLite boolean
);

CREATE TABLE IF NOT EXISTS item_topics (
    item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    topic_id        INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    confidence      REAL DEFAULT 1.0,
    PRIMARY KEY (item_id, topic_id)
);

CREATE TABLE IF NOT EXISTS user_interests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id        INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    weight          REAL DEFAULT 1.0,
    source          TEXT DEFAULT 'explicit' CHECK(source IN ('explicit', 'inferred')),
    updated_at      TEXT NOT NULL  -- ISO 8601
);

CREATE INDEX IF NOT EXISTS idx_user_interests_topic ON user_interests(topic_id);

CREATE TABLE IF NOT EXISTS item_connections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_a_id       INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    item_b_id       INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    relationship    TEXT NOT NULL CHECK(relationship IN ('competes_with', 'builds_on', 'same_topic', 'evolves_from')),
    description     TEXT DEFAULT '',
    created_at      TEXT NOT NULL  -- ISO 8601
);

CREATE INDEX IF NOT EXISTS idx_connections_a ON item_connections(item_a_id);
CREATE INDEX IF NOT EXISTS idx_connections_b ON item_connections(item_b_id);

CREATE TABLE IF NOT EXISTS digests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_type     TEXT NOT NULL CHECK(digest_type IN ('daily', 'weekly', 'on_demand', 'alert')),
    created_at      TEXT NOT NULL,  -- ISO 8601
    content_md      TEXT,
    content_html    TEXT,
    item_ids        TEXT           -- JSON array of item IDs
);

CREATE TABLE IF NOT EXISTS user_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    action          TEXT NOT NULL CHECK(action IN ('bookmarked', 'dismissed', 'deep_dive_requested', 'feedback')),
    payload         TEXT,          -- JSON
    created_at      TEXT NOT NULL  -- ISO 8601
);

CREATE INDEX IF NOT EXISTS idx_user_actions_item_id ON user_actions(item_id);

CREATE TABLE IF NOT EXISTS task_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_type      TEXT NOT NULL,
    payload         TEXT NOT NULL,  -- JSON
    status          TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'running', 'completed', 'failed')),
    priority        INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL,  -- ISO 8601
    started_at      TEXT,
    completed_at    TEXT,
    result          TEXT,          -- JSON
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status);
CREATE INDEX IF NOT EXISTS idx_task_queue_priority ON task_queue(priority DESC);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL  -- ISO 8601
);
```

- [ ] **Step 4: Commit**

```bash
git add db/__init__.py db/schema.sql
git commit -m "feat: add SQLite schema for agent team architecture"
```

---

### Task 2: Database Connection & Migration

**Files:**
- Create: `db/database.py`
- Create: `tests/test_database.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_database.py`:

```python
import pytest
import sqlite3
from pathlib import Path
from db.database import Database


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    database.initialize()
    return database


def test_initialize_creates_tables(db):
    with db.connect() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
    expected = {
        "items", "item_scores", "item_analysis", "topics", "item_topics",
        "user_interests", "item_connections", "digests", "user_actions",
        "task_queue", "schema_version",
    }
    assert expected.issubset(tables)


def test_initialize_sets_schema_version(db):
    with db.connect() as conn:
        cursor = conn.execute("SELECT version FROM schema_version")
        version = cursor.fetchone()[0]
    assert version == 1


def test_initialize_is_idempotent(db):
    db.initialize()  # second call should not raise
    with db.connect() as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM schema_version")
        count = cursor.fetchone()[0]
    assert count == 1


def test_connect_returns_connection(db):
    with db.connect() as conn:
        assert isinstance(conn, sqlite3.Connection)


def test_foreign_keys_enabled(db):
    with db.connect() as conn:
        cursor = conn.execute("PRAGMA foreign_keys")
        assert cursor.fetchone()[0] == 1


def test_wal_mode_enabled(db):
    with db.connect() as conn:
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
    assert mode == "wal"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_database.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'db.database'`

- [ ] **Step 3: Implement `db/database.py`**

```python
from __future__ import annotations
import sqlite3
import logging
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class Database:
    def __init__(self, db_path: Path | str = "trendbot.db"):
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        schema_sql = Path(__file__).parent / "schema.sql"
        schema = schema_sql.read_text()

        with self.connect() as conn:
            # Check if already initialized
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            if cursor.fetchone():
                existing = conn.execute("SELECT version FROM schema_version").fetchone()
                if existing and existing[0] >= SCHEMA_VERSION:
                    logger.info(f"Database already at version {existing[0]}")
                    return

            conn.executescript(schema)
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version, applied_at) "
                "VALUES (?, datetime('now'))",
                (SCHEMA_VERSION,),
            )
            conn.commit()
            logger.info(f"Database initialized at version {SCHEMA_VERSION}")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_database.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add db/database.py tests/test_database.py
git commit -m "feat: add Database class with init and connection management"
```

---

### Task 3: Query Functions — Items

**Files:**
- Create: `db/queries.py`
- Create: `tests/test_queries.py`

- [ ] **Step 1: Write the failing tests for item queries**

Create `tests/test_queries.py`:

```python
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
    assert history[0]["momentum_score"] == 0.5  # oldest first
    assert history[1]["momentum_score"] == 0.9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_queries.py -v`
Expected: FAIL with `ImportError: cannot import name 'upsert_item' from 'db.queries'`

- [ ] **Step 3: Implement `db/queries.py`**

```python
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone

from db.database import Database

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Items ──────────────────────────────────────────────

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


def get_items(
    db: Database,
    source: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int | None = None,
    order_by: str = "last_seen DESC",
) -> list[dict]:
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

    query += f" ORDER BY {order_by}"

    if limit:
        query += " LIMIT ?"
        params.append(limit)

    with db.connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


# ── Score History ──────────────────────────────────────

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


# ── Task Queue ─────────────────────────────────────────

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_queries.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Commit**

```bash
git add db/queries.py tests/test_queries.py
git commit -m "feat: add query functions for items, scores, and task queue"
```

---

### Task 4: Query Functions — Task Queue Tests

**Files:**
- Modify: `tests/test_queries.py`

- [ ] **Step 1: Add task queue tests to `tests/test_queries.py`**

Append to the end of the file:

```python
# ── Task Queue ─────────────────────────────────────────

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
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_queries.py -v`
Expected: All 19 tests PASS (11 existing + 8 new)

- [ ] **Step 3: Commit**

```bash
git add tests/test_queries.py
git commit -m "test: add task queue query tests"
```

---

### Task 5: Event Bus

**Files:**
- Create: `orchestrator/__init__.py`
- Create: `orchestrator/events.py`
- Create: `tests/test_events.py`

- [ ] **Step 1: Create orchestrator package**

```bash
mkdir -p orchestrator
```

- [ ] **Step 2: Create `orchestrator/__init__.py`**

```python
```

(Empty file — package marker only.)

- [ ] **Step 3: Write the failing tests**

Create `tests/test_events.py`:

```python
import pytest
from orchestrator.events import EventBus


def test_subscribe_and_emit():
    bus = EventBus()
    received = []
    bus.subscribe("items_updated", lambda data: received.append(data))
    bus.emit("items_updated", {"source": "github", "count": 10})
    assert len(received) == 1
    assert received[0] == {"source": "github", "count": 10}


def test_multiple_subscribers():
    bus = EventBus()
    results_a = []
    results_b = []
    bus.subscribe("items_updated", lambda data: results_a.append(data))
    bus.subscribe("items_updated", lambda data: results_b.append(data))
    bus.emit("items_updated", {"count": 5})
    assert len(results_a) == 1
    assert len(results_b) == 1


def test_emit_unknown_event_is_noop():
    bus = EventBus()
    bus.emit("nonexistent", {})  # should not raise


def test_subscriber_error_does_not_break_others():
    bus = EventBus()
    received = []

    def bad_handler(data):
        raise ValueError("boom")

    bus.subscribe("test", bad_handler)
    bus.subscribe("test", lambda data: received.append(data))
    bus.emit("test", {"ok": True})
    assert len(received) == 1


def test_events_are_isolated():
    bus = EventBus()
    a_received = []
    b_received = []
    bus.subscribe("event_a", lambda data: a_received.append(data))
    bus.subscribe("event_b", lambda data: b_received.append(data))
    bus.emit("event_a", {"a": 1})
    assert len(a_received) == 1
    assert len(b_received) == 0


def test_unsubscribe():
    bus = EventBus()
    received = []
    handler = lambda data: received.append(data)
    bus.subscribe("test", handler)
    bus.unsubscribe("test", handler)
    bus.emit("test", {"x": 1})
    assert len(received) == 0
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestrator.events'`

- [ ] **Step 5: Implement `orchestrator/events.py`**

```python
from __future__ import annotations
import logging
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)

EventHandler = Callable[[dict], None]


class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event: str, handler: EventHandler) -> None:
        self._handlers[event].append(handler)

    def unsubscribe(self, event: str, handler: EventHandler) -> None:
        handlers = self._handlers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    def emit(self, event: str, data: dict) -> None:
        handlers = self._handlers.get(event, [])
        for handler in handlers:
            try:
                handler(data)
            except Exception:
                logger.exception(f"Error in handler for event '{event}'")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_events.py -v`
Expected: All 6 tests PASS

- [ ] **Step 7: Commit**

```bash
git add orchestrator/__init__.py orchestrator/events.py tests/test_events.py
git commit -m "feat: add EventBus for inter-agent communication"
```

---

### Task 6: BaseAgent

**Files:**
- Create: `agents/__init__.py`
- Create: `agents/base.py`
- Create: `tests/test_base_agent.py`

- [ ] **Step 1: Create agents package**

```bash
mkdir -p agents
```

- [ ] **Step 2: Create `agents/__init__.py`**

```python
```

(Empty file — package marker only.)

- [ ] **Step 3: Write the failing tests**

Create `tests/test_base_agent.py`:

```python
import pytest
from pathlib import Path
from db.database import Database
from orchestrator.events import EventBus
from agents.base import BaseAgent, AgentContext, AgentResult


class CountingAgent(BaseAgent):
    name = "counter"
    schedule = "*/5 * * * *"

    def __init__(self):
        super().__init__()
        self.run_count = 0

    def execute(self, ctx: AgentContext) -> AgentResult:
        self.run_count += 1
        return AgentResult(success=True, message=f"Run #{self.run_count}",
                           data={"count": self.run_count})


class FailingAgent(BaseAgent):
    name = "failer"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        raise RuntimeError("Something broke")


class EventEmittingAgent(BaseAgent):
    name = "emitter"
    schedule = "0 */4 * * *"

    def execute(self, ctx: AgentContext) -> AgentResult:
        ctx.emit("items_updated", {"source": "test", "count": 5})
        return AgentResult(success=True, message="Emitted event")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def event_bus():
    return EventBus()


def test_agent_has_name():
    agent = CountingAgent()
    assert agent.name == "counter"


def test_agent_has_schedule():
    agent = CountingAgent()
    assert agent.schedule == "*/5 * * * *"


def test_agent_run_returns_result(db, event_bus):
    agent = CountingAgent()
    ctx = AgentContext(db=db, event_bus=event_bus, config={})
    result = agent.run(ctx)
    assert result.success is True
    assert result.data == {"count": 1}


def test_agent_run_handles_exception(db, event_bus):
    agent = FailingAgent()
    ctx = AgentContext(db=db, event_bus=event_bus, config={})
    result = agent.run(ctx)
    assert result.success is False
    assert "Something broke" in result.message


def test_agent_can_emit_events(db, event_bus):
    received = []
    event_bus.subscribe("items_updated", lambda d: received.append(d))
    agent = EventEmittingAgent()
    ctx = AgentContext(db=db, event_bus=event_bus, config={})
    agent.run(ctx)
    assert len(received) == 1
    assert received[0] == {"source": "test", "count": 5}


def test_agent_run_count(db, event_bus):
    agent = CountingAgent()
    ctx = AgentContext(db=db, event_bus=event_bus, config={})
    agent.run(ctx)
    agent.run(ctx)
    assert agent.run_count == 2


def test_on_demand_schedule():
    agent = FailingAgent()
    assert agent.schedule == "on_demand"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_base_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.base'`

- [ ] **Step 5: Implement `agents/base.py`**

```python
from __future__ import annotations
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from db.database import Database
from orchestrator.events import EventBus

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    db: Database
    event_bus: EventBus
    config: dict

    def emit(self, event: str, data: dict) -> None:
        self.event_bus.emit(event, data)


@dataclass
class AgentResult:
    success: bool
    message: str = ""
    data: dict = field(default_factory=dict)


class BaseAgent(ABC):
    name: str = ""
    schedule: str = "on_demand"  # cron expression or "on_demand"
    timeout: int = 300  # max seconds

    def __init__(self):
        if not self.name:
            self.name = self.__class__.__name__.lower()

    @abstractmethod
    def execute(self, ctx: AgentContext) -> AgentResult:
        ...

    def run(self, ctx: AgentContext) -> AgentResult:
        logger.info(f"Agent '{self.name}' starting")
        start = time.monotonic()
        try:
            result = self.execute(ctx)
            elapsed = time.monotonic() - start
            logger.info(f"Agent '{self.name}' completed in {elapsed:.1f}s: {result.message}")
            return result
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.error(f"Agent '{self.name}' failed after {elapsed:.1f}s: {e}", exc_info=True)
            return AgentResult(success=False, message=str(e))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_base_agent.py -v`
Expected: All 7 tests PASS

- [ ] **Step 7: Commit**

```bash
git add agents/__init__.py agents/base.py tests/test_base_agent.py
git commit -m "feat: add BaseAgent with AgentContext and AgentResult"
```

---

### Task 7: Task Dispatcher

**Files:**
- Create: `orchestrator/dispatcher.py`
- Create: `tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dispatcher.py`:

```python
import json
import pytest
from pathlib import Path
from db.database import Database
from db.queries import enqueue_task, get_pending_tasks
from orchestrator.events import EventBus
from orchestrator.dispatcher import TaskDispatcher
from agents.base import BaseAgent, AgentContext, AgentResult


class EchoAgent(BaseAgent):
    name = "echo"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(success=True, message="echoed",
                           data={"echo": True})


class BrokenAgent(BaseAgent):
    name = "broken"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        raise RuntimeError("Agent crashed")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def dispatcher(db, event_bus):
    d = TaskDispatcher(db=db, event_bus=event_bus, config={})
    d.register_agent(EchoAgent())
    d.register_agent(BrokenAgent())
    return d


def test_register_agent(dispatcher):
    assert "echo" in dispatcher.agents
    assert "broken" in dispatcher.agents


def test_process_one_task_success(dispatcher, db):
    enqueue_task(db, agent_type="echo", payload={"msg": "hello"})
    processed = dispatcher.process_one()
    assert processed is True
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM task_queue WHERE id=1").fetchone()
    assert row["status"] == "completed"
    assert json.loads(row["result"]) == {"echo": True}


def test_process_one_task_failure(dispatcher, db):
    enqueue_task(db, agent_type="broken", payload={})
    processed = dispatcher.process_one()
    assert processed is True
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM task_queue WHERE id=1").fetchone()
    assert row["status"] == "failed"
    assert "Agent crashed" in row["error"]


def test_process_one_returns_false_when_empty(dispatcher):
    processed = dispatcher.process_one()
    assert processed is False


def test_process_unknown_agent_type(dispatcher, db):
    enqueue_task(db, agent_type="nonexistent", payload={})
    processed = dispatcher.process_one()
    assert processed is True
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM task_queue WHERE id=1").fetchone()
    assert row["status"] == "failed"
    assert "Unknown agent type" in row["error"]


def test_process_all_drains_queue(dispatcher, db):
    enqueue_task(db, agent_type="echo", payload={"a": 1})
    enqueue_task(db, agent_type="echo", payload={"b": 2})
    enqueue_task(db, agent_type="echo", payload={"c": 3})
    count = dispatcher.process_all()
    assert count == 3
    pending = get_pending_tasks(db)
    assert len(pending) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dispatcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestrator.dispatcher'`

- [ ] **Step 3: Implement `orchestrator/dispatcher.py`**

```python
from __future__ import annotations
import json
import logging

from db.database import Database
from db.queries import claim_next_task, complete_task, fail_task
from orchestrator.events import EventBus
from agents.base import BaseAgent, AgentContext

logger = logging.getLogger(__name__)


class TaskDispatcher:
    def __init__(self, db: Database, event_bus: EventBus, config: dict):
        self.db = db
        self.event_bus = event_bus
        self.config = config
        self.agents: dict[str, BaseAgent] = {}

    def register_agent(self, agent: BaseAgent) -> None:
        self.agents[agent.name] = agent

    def process_one(self) -> bool:
        task = claim_next_task(self.db)
        if not task:
            return False

        agent_type = task["agent_type"]
        task_id = task["id"]

        agent = self.agents.get(agent_type)
        if not agent:
            fail_task(self.db, task_id, f"Unknown agent type: {agent_type}")
            return True

        ctx = AgentContext(db=self.db, event_bus=self.event_bus, config=self.config)
        result = agent.run(ctx)

        if result.success:
            complete_task(self.db, task_id, result=result.data)
        else:
            fail_task(self.db, task_id, error=result.message)

        return True

    def process_all(self) -> int:
        count = 0
        while self.process_one():
            count += 1
        return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dispatcher.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: add TaskDispatcher for async agent work queue"
```

---

### Task 8: Agent Scheduler

**Files:**
- Create: `orchestrator/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scheduler.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from db.database import Database
from orchestrator.events import EventBus
from orchestrator.scheduler import AgentScheduler
from agents.base import BaseAgent, AgentContext, AgentResult


class ScheduledAgent(BaseAgent):
    name = "scheduled"
    schedule = "*/5 * * * *"
    run_count = 0

    def execute(self, ctx: AgentContext) -> AgentResult:
        ScheduledAgent.run_count += 1
        return AgentResult(success=True, message="done")


class OnDemandAgent(BaseAgent):
    name = "on_demand_agent"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(success=True, message="done")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def scheduler(db, event_bus):
    return AgentScheduler(db=db, event_bus=event_bus, config={})


def test_register_scheduled_agent(scheduler):
    agent = ScheduledAgent()
    scheduler.register(agent)
    assert "scheduled" in scheduler.agents


def test_register_on_demand_agent_skips_scheduling(scheduler):
    agent = OnDemandAgent()
    scheduler.register(agent)
    assert "on_demand_agent" in scheduler.agents
    # on_demand agents should be registered but not added to APScheduler
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) == 0


def test_register_scheduled_agent_adds_job(scheduler):
    agent = ScheduledAgent()
    scheduler.register(agent)
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "scheduled"


def test_run_agent_directly(scheduler, db, event_bus):
    ScheduledAgent.run_count = 0
    agent = ScheduledAgent()
    scheduler.register(agent)
    scheduler.run_agent("scheduled")
    assert ScheduledAgent.run_count == 1


def test_run_agent_unknown_name(scheduler):
    with pytest.raises(KeyError):
        scheduler.run_agent("nonexistent")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestrator.scheduler'`

- [ ] **Step 3: Implement `orchestrator/scheduler.py`**

```python
from __future__ import annotations
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from db.database import Database
from orchestrator.events import EventBus
from agents.base import BaseAgent, AgentContext

logger = logging.getLogger(__name__)


class AgentScheduler:
    def __init__(self, db: Database, event_bus: EventBus, config: dict):
        self.db = db
        self.event_bus = event_bus
        self.config = config
        self.agents: dict[str, BaseAgent] = {}
        self.scheduler = BackgroundScheduler()

    def register(self, agent: BaseAgent) -> None:
        self.agents[agent.name] = agent
        if agent.schedule != "on_demand":
            trigger = CronTrigger.from_crontab(agent.schedule)
            self.scheduler.add_job(
                self.run_agent,
                trigger=trigger,
                id=agent.name,
                args=[agent.name],
                replace_existing=True,
            )
            logger.info(f"Scheduled agent '{agent.name}' with cron '{agent.schedule}'")
        else:
            logger.info(f"Registered on-demand agent '{agent.name}'")

    def run_agent(self, name: str) -> None:
        agent = self.agents[name]
        ctx = AgentContext(db=self.db, event_bus=self.event_bus, config=self.config)
        agent.run(ctx)

    def start(self) -> None:
        self.scheduler.start()
        logger.info("Agent scheduler started")

    def stop(self) -> None:
        self.scheduler.shutdown(wait=True)
        logger.info("Agent scheduler stopped")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scheduler.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/scheduler.py tests/test_scheduler.py
git commit -m "feat: add AgentScheduler with APScheduler cron support"
```

---

### Task 9: Application Orchestrator

**Files:**
- Create: `orchestrator/app.py`
- Create: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_app.py`:

```python
import pytest
import time
import threading
from pathlib import Path
from db.database import Database
from db.queries import enqueue_task
from orchestrator.app import Application
from agents.base import BaseAgent, AgentContext, AgentResult


class PingAgent(BaseAgent):
    name = "ping"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(success=True, message="pong", data={"pong": True})


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def app(db):
    application = Application(db=db, config={})
    application.register_agent(PingAgent())
    return application


def test_application_creates_event_bus(app):
    assert app.event_bus is not None


def test_application_creates_scheduler(app):
    assert app.scheduler is not None


def test_application_creates_dispatcher(app):
    assert app.dispatcher is not None


def test_application_registers_agent_in_both(app):
    assert "ping" in app.scheduler.agents
    assert "ping" in app.dispatcher.agents


def test_application_process_tasks(app, db):
    enqueue_task(db, agent_type="ping", payload={})
    count = app.dispatcher.process_all()
    assert count == 1


def test_application_subscribe_to_events(app):
    received = []
    app.on_event("test_event", lambda d: received.append(d))
    app.event_bus.emit("test_event", {"x": 1})
    assert len(received) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestrator.app'`

- [ ] **Step 3: Implement `orchestrator/app.py`**

```python
from __future__ import annotations
import logging
import signal
import threading
import time
from typing import Callable

from db.database import Database
from orchestrator.events import EventBus
from orchestrator.dispatcher import TaskDispatcher
from orchestrator.scheduler import AgentScheduler
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class Application:
    def __init__(self, db: Database, config: dict):
        self.db = db
        self.config = config
        self.event_bus = EventBus()
        self.scheduler = AgentScheduler(db=db, event_bus=self.event_bus, config=config)
        self.dispatcher = TaskDispatcher(db=db, event_bus=self.event_bus, config=config)
        self._running = False
        self._dispatcher_thread: threading.Thread | None = None

    def register_agent(self, agent: BaseAgent) -> None:
        self.scheduler.register(agent)
        self.dispatcher.register_agent(agent)

    def on_event(self, event: str, handler: Callable[[dict], None]) -> None:
        self.event_bus.subscribe(event, handler)

    def start(self) -> None:
        logger.info("Starting TrendBot application")
        self._running = True
        self.scheduler.start()
        self._dispatcher_thread = threading.Thread(
            target=self._dispatch_loop, daemon=True
        )
        self._dispatcher_thread.start()
        logger.info("TrendBot application started")

    def _dispatch_loop(self) -> None:
        while self._running:
            try:
                processed = self.dispatcher.process_one()
                if not processed:
                    time.sleep(2)  # poll interval when queue is empty
            except Exception:
                logger.exception("Dispatcher error")
                time.sleep(5)

    def stop(self) -> None:
        logger.info("Stopping TrendBot application")
        self._running = False
        self.scheduler.stop()
        if self._dispatcher_thread:
            self._dispatcher_thread.join(timeout=10)
        logger.info("TrendBot application stopped")

    def run_forever(self) -> None:
        self.start()
        shutdown = threading.Event()

        def handle_signal(signum, frame):
            logger.info(f"Received signal {signum}, shutting down")
            shutdown.set()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            shutdown.wait()
        finally:
            self.stop()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_app.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app.py tests/test_app.py
git commit -m "feat: add Application orchestrator with scheduler and dispatcher"
```

---

### Task 10: Update Dependencies and Config

**Files:**
- Modify: `requirements.txt`
- Modify: `config.yaml`
- Modify: `config.py`

- [ ] **Step 1: Add new dependencies to `requirements.txt`**

Add after the existing entries:

```
apscheduler>=3.10.0
aiosqlite>=0.19.0
```

- [ ] **Step 2: Add orchestrator config to `config.yaml`**

Add at the end of the file:

```yaml

orchestrator:
  db_path: trendbot.db
  task_poll_interval: 2
  agents:
    github_scout:
      schedule: "0 */4 * * *"
    reddit_scout:
      schedule: "0 */4 * * *"
    arxiv_scout:
      schedule: "0 */12 * * *"
    huggingface_scout:
      schedule: "0 */6 * * *"
    hackernews_scout:
      schedule: "0 */4 * * *"
    twitter_scout:
      schedule: "0 */4 * * *"
    scorer:
      schedule: "on_demand"  # triggered by scout events
    filter:
      schedule: "on_demand"  # triggered by scorer events
    dot_connector:
      schedule: "0 3 * * *"  # daily at 3 AM
    deep_diver:
      schedule: "on_demand"
    topic_tracker:
      schedule: "0 4 * * 1"  # weekly Monday 4 AM
```

- [ ] **Step 3: Add orchestrator defaults to `config.py`**

Add the `"orchestrator"` key to the `DEFAULTS` dict in `config.py`, after the `"delivery"` key:

```python
    "orchestrator": {
        "db_path": "trendbot.db",
        "task_poll_interval": 2,
        "agents": {},
    },
```

- [ ] **Step 4: Install new dependencies**

Run: `pip install apscheduler>=3.10.0 aiosqlite>=0.19.0`

- [ ] **Step 5: Run all existing tests to verify nothing is broken**

Run: `pytest tests/ -v`
Expected: All tests PASS (existing + new)

- [ ] **Step 6: Commit**

```bash
git add requirements.txt config.yaml config.py
git commit -m "chore: add orchestrator dependencies and config"
```

---

### Task 11: Integration Test — Full Stack

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_integration.py`:

```python
"""Integration test: wire up DB + agents + orchestrator and process a task end-to-end."""
import json
import pytest
from pathlib import Path
from db.database import Database
from db.queries import enqueue_task, get_item_by_url, get_score_history
from orchestrator.app import Application
from agents.base import BaseAgent, AgentContext, AgentResult


class FakeScoutAgent(BaseAgent):
    """Simulates a scout agent that discovers items and writes to DB."""
    name = "fake_scout"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        from db.queries import upsert_item, snapshot_score
        item_id = upsert_item(
            ctx.db,
            url="https://github.com/test/repo",
            title="Test Repo",
            source="github",
            description="A test repository",
            raw_metrics={"stars": 500, "forks": 50},
            momentum_score=0.85,
            normalized_score=75.0,
        )
        snapshot_score(
            ctx.db, item_id,
            momentum_score=0.85,
            normalized_score=75.0,
            raw_metrics={"stars": 500},
        )
        ctx.emit("items_updated", {"source": "github", "count": 1, "new_count": 1})
        return AgentResult(success=True, message="Discovered 1 item",
                           data={"item_ids": [item_id]})


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


def test_full_stack_task_processing(db):
    app = Application(db=db, config={})
    app.register_agent(FakeScoutAgent())

    # Track events
    events_received = []
    app.on_event("items_updated", lambda d: events_received.append(d))

    # Enqueue a scout run
    enqueue_task(db, agent_type="fake_scout", payload={})

    # Process it
    count = app.dispatcher.process_all()
    assert count == 1

    # Verify item was written to DB
    item = get_item_by_url(db, "https://github.com/test/repo")
    assert item is not None
    assert item["title"] == "Test Repo"
    assert item["source"] == "github"
    assert item["momentum_score"] == 0.85

    # Verify score history
    history = get_score_history(db, item["id"])
    assert len(history) == 1
    assert history[0]["momentum_score"] == 0.85

    # Verify event was emitted
    assert len(events_received) == 1
    assert events_received[0]["source"] == "github"


def test_event_triggers_downstream_agent(db):
    """Test that events can wire agents together."""
    app = Application(db=db, config={})
    app.register_agent(FakeScoutAgent())

    # Track what happens when items_updated fires
    downstream_runs = []

    class FakeAnalystAgent(BaseAgent):
        name = "fake_analyst"
        schedule = "on_demand"

        def execute(self, ctx: AgentContext) -> AgentResult:
            downstream_runs.append(True)
            return AgentResult(success=True, message="Analyzed")

    analyst = FakeAnalystAgent()
    app.register_agent(analyst)

    # Wire: when items_updated fires, enqueue analyst
    def on_items_updated(data):
        enqueue_task(db, agent_type="fake_analyst",
                     payload={"triggered_by": data["source"]})

    app.on_event("items_updated", on_items_updated)

    # Enqueue scout, process it (fires event, which enqueues analyst)
    enqueue_task(db, agent_type="fake_scout", payload={})
    app.dispatcher.process_all()  # processes scout + analyst

    assert len(downstream_runs) == 1


def test_multiple_scouts_accumulate_items(db):
    """Multiple scout runs for the same item should update, not duplicate."""
    app = Application(db=db, config={})
    app.register_agent(FakeScoutAgent())

    enqueue_task(db, agent_type="fake_scout", payload={})
    enqueue_task(db, agent_type="fake_scout", payload={})
    app.dispatcher.process_all()

    item = get_item_by_url(db, "https://github.com/test/repo")
    assert item["times_seen"] == 2

    history = get_score_history(db, item["id"])
    assert len(history) == 2
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/test_integration.py -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration tests for full agent stack"
```

---

### Task 12: Verify Existing Pipeline Still Works

**Files:** None modified — verification only.

- [ ] **Step 1: Verify existing tests still pass**

Run: `pytest tests/test_models.py tests/test_config.py tests/test_pipeline.py -v`
Expected: All PASS — the foundation adds new code without touching existing code.

- [ ] **Step 2: Verify pipeline can still run in single-stage mode**

Run: `python run.py --stage collect --help` (or similar dry-run check)
Expected: No import errors. The existing pipeline is unaffected by the new `db/`, `agents/`, and `orchestrator/` packages.

- [ ] **Step 3: Final commit with any fixes needed**

If any existing tests needed adjustment (they shouldn't), commit fixes:

```bash
git add -A
git commit -m "chore: verify existing pipeline compatibility with foundation layer"
```
