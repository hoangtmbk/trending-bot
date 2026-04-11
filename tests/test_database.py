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
