import pytest
import sqlite3
from pathlib import Path
from db.database import Database, SCHEMA_VERSION


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
        "task_queue", "schema_version", "topic_velocity",
    }
    assert expected.issubset(tables)


def test_initialize_sets_schema_version(db):
    with db.connect() as conn:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        version = cursor.fetchone()[0]
    assert version == SCHEMA_VERSION


def test_initialize_is_idempotent(db):
    db.initialize()  # second call should not raise
    with db.connect() as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM schema_version")
        count = cursor.fetchone()[0]
    assert count == 1


def test_initialize_applies_tables_added_after_db_was_created(tmp_path):
    """A DB stamped at an older version picks up tables added to schema.sql later.

    Reproduces the production failure where `topic_velocity` was added to
    schema.sql after the live DB had been stamped at version 1, so the version
    gate short-circuited and the table was never created.
    """
    db_path = tmp_path / "stale.db"
    database = Database(db_path)
    database.initialize()

    # Simulate the older deployment: drop the newer table and roll the stamp back.
    with database.connect() as conn:
        conn.execute("DROP TABLE topic_velocity")
        conn.execute("DELETE FROM schema_version")
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (1, datetime('now'))"
        )
        conn.commit()

    database.initialize()

    with database.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]

    assert "topic_velocity" in tables
    assert version == SCHEMA_VERSION


def test_schema_version_read_is_not_confused_by_multiple_rows(tmp_path):
    """Upgrades leave several rows behind; the gate must read the newest."""
    db_path = tmp_path / "multi.db"
    database = Database(db_path)
    database.initialize()

    with database.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, applied_at) "
            "VALUES (1, datetime('now'))"
        )
        conn.commit()

    # Must not re-run the script or regress: version 1 row is stale history.
    database.initialize()

    with database.connect() as conn:
        version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert version == SCHEMA_VERSION


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
