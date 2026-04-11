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
