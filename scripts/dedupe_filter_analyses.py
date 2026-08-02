#!/usr/bin/env python3
"""One-off cleanup: collapse redundant 'filter' rows in item_analysis.

Before the filter agent became idempotent it INSERTed a fresh verdict on every
run, with no recency bound on selection. Production on 2026-08-02 held 29,983
filter rows across 3,187 distinct items (~9.4x), one paper analyzed 1,191 times.

This keeps the newest filter row per item and deletes the rest. That is safe
because every reader already resolves the newest row per item — see
`db.queries.get_items_with_filter` and `agents.notifiers.digest_pusher`, both of
which join on `MAX(created_at)`. Keeping the newest preserves that value exactly,
so no dashboard or digest output changes.

Only 'filter' rows are touched; deep_dive, connection and topic_report are left
alone. Run it after deploying the idempotency fix, otherwise the agent just
recreates the duplicates.

    python scripts/dedupe_filter_analyses.py --db trendbot.db            # dry run
    python scripts/dedupe_filter_analyses.py --db trendbot.db --apply
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import Database  # noqa: E402

DELETE_CHUNK = 500


def dedupe_filter_analyses(db: Database, *, apply: bool = False) -> int:
    """Delete every 'filter' analysis except the newest per item.

    Returns the number of rows deleted, or that would be deleted when
    `apply` is False.

    Grouping happens in Python rather than SQL: it keeps the tie-break explicit
    (newest `created_at`, then highest `id` — `datetime('now')` has
    second resolution, so same-second duplicates are real) and avoids relying on
    window functions being compiled into whichever SQLite the container ships.
    """
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, item_id, created_at FROM item_analysis "
            "WHERE analysis_type = 'filter'"
        ).fetchall()

        keep: dict[int, tuple[str, int]] = {}
        for row in rows:
            item_id = row["item_id"]
            candidate = (row["created_at"], row["id"])
            if item_id not in keep or candidate > keep[item_id]:
                keep[item_id] = candidate

        keep_ids = {rowid for _, rowid in keep.values()}
        doomed = [row["id"] for row in rows if row["id"] not in keep_ids]

        if not apply or not doomed:
            return len(doomed)

        for start in range(0, len(doomed), DELETE_CHUNK):
            chunk = doomed[start:start + DELETE_CHUNK]
            placeholders = ",".join("?" * len(chunk))
            conn.execute(
                f"DELETE FROM item_analysis WHERE id IN ({placeholders})", chunk
            )
        conn.commit()

    return len(doomed)


def _vacuum(db: Database) -> None:
    """Reclaim the freed pages. Must run outside a transaction."""
    conn = sqlite3.connect(str(db.db_path), timeout=300)
    try:
        conn.isolation_level = None
        conn.execute("VACUUM")
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="trendbot.db", help="path to trendbot.db")
    parser.add_argument("--apply", action="store_true",
                        help="actually delete (default is a dry run)")
    parser.add_argument("--no-vacuum", action="store_true",
                        help="skip VACUUM after deleting")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"error: {db_path} does not exist", file=sys.stderr)
        return 1

    db = Database(db_path)
    size_before = db_path.stat().st_size

    deleted = dedupe_filter_analyses(db, apply=args.apply)

    if not args.apply:
        print(f"dry run: would delete {deleted:,} redundant filter rows")
        print("re-run with --apply to delete")
        return 0

    print(f"deleted {deleted:,} redundant filter rows")

    if deleted and not args.no_vacuum:
        print("vacuuming…")
        _vacuum(db)
        size_after = db_path.stat().st_size
        print(f"size {size_before / 1e6:.1f} MB → {size_after / 1e6:.1f} MB")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
