"""Tests for the one-off filter-analysis dedup maintenance script.

The script deletes ~26,796 rows from a 146 MB production database, so its
invariant — that `MAX(created_at)` per item is unchanged — is worth pinning
down. Every reader of `item_analysis` resolves the newest filter row per item
(`db.queries.get_items_with_filter`, `agents.notifiers.digest_pusher`), so
preserving that value is what makes the delete safe.
"""
import json
import pytest
from db.database import Database
from scripts.dedupe_filter_analyses import dedupe_filter_analyses


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


def _add_item(db, url):
    from db.queries import upsert_item
    return upsert_item(db, url=url, title=url, source="github",
                       description="", raw_metrics={})


def _add_analysis(db, item_id, created_at, *, analysis_type="filter", summary="s"):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO item_analysis (item_id, analysis_type, created_at, content) "
            "VALUES (?, ?, ?, ?)",
            (item_id, analysis_type, created_at, json.dumps({"summary": summary})),
        )
        conn.commit()


def _filter_rows(db, item_id):
    with db.connect() as conn:
        return conn.execute(
            "SELECT created_at, content FROM item_analysis "
            "WHERE item_id=? AND analysis_type='filter' ORDER BY created_at",
            (item_id,),
        ).fetchall()


class TestDedupeFilterAnalyses:
    def test_keeps_only_the_newest_filter_row_per_item(self, db):
        item = _add_item(db, "https://example.com/a")
        _add_analysis(db, item, "2026-05-14T00:00:00+00:00", summary="oldest")
        _add_analysis(db, item, "2026-06-01T00:00:00+00:00", summary="middle")
        _add_analysis(db, item, "2026-08-02T00:00:00+00:00", summary="newest")

        dedupe_filter_analyses(db, apply=True)

        rows = _filter_rows(db, item)
        assert len(rows) == 1
        assert json.loads(rows[0]["content"])["summary"] == "newest"

    def test_preserves_max_created_at(self, db):
        """The invariant every reader depends on."""
        item = _add_item(db, "https://example.com/b")
        for ts in ("2026-05-14T00:00:00+00:00", "2026-08-02T09:30:00+00:00"):
            _add_analysis(db, item, ts)

        dedupe_filter_analyses(db, apply=True)

        with db.connect() as conn:
            newest = conn.execute(
                "SELECT MAX(created_at) AS m FROM item_analysis "
                "WHERE item_id=? AND analysis_type='filter'", (item,)
            ).fetchone()["m"]
        assert newest == "2026-08-02T09:30:00+00:00"

    def test_leaves_non_filter_analyses_untouched(self, db):
        item = _add_item(db, "https://example.com/c")
        _add_analysis(db, item, "2026-05-01T00:00:00+00:00", analysis_type="deep_dive")
        _add_analysis(db, item, "2026-06-01T00:00:00+00:00", analysis_type="deep_dive")

        dedupe_filter_analyses(db, apply=True)

        with db.connect() as conn:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM item_analysis WHERE analysis_type='deep_dive'"
            ).fetchone()["n"]
        assert n == 2

    def test_leaves_items_with_a_single_filter_row_alone(self, db):
        item = _add_item(db, "https://example.com/d")
        _add_analysis(db, item, "2026-08-01T00:00:00+00:00")

        deleted = dedupe_filter_analyses(db, apply=True)

        assert deleted == 0
        assert len(_filter_rows(db, item)) == 1

    def test_dedupes_each_item_independently(self, db):
        a = _add_item(db, "https://example.com/e")
        b = _add_item(db, "https://example.com/f")
        _add_analysis(db, a, "2026-05-01T00:00:00+00:00")
        _add_analysis(db, a, "2026-06-01T00:00:00+00:00")
        _add_analysis(db, b, "2026-07-01T00:00:00+00:00")

        deleted = dedupe_filter_analyses(db, apply=True)

        assert deleted == 1
        assert len(_filter_rows(db, a)) == 1
        assert len(_filter_rows(db, b)) == 1

    def test_dry_run_reports_without_deleting(self, db):
        item = _add_item(db, "https://example.com/g")
        _add_analysis(db, item, "2026-05-01T00:00:00+00:00")
        _add_analysis(db, item, "2026-06-01T00:00:00+00:00")

        deleted = dedupe_filter_analyses(db, apply=False)

        assert deleted == 1
        assert len(_filter_rows(db, item)) == 2

    def test_ties_on_created_at_collapse_to_one_row(self, db):
        """Two rows written in the same clock tick — datetime('now') is
        second-resolution, so this happens. Must not leave both behind."""
        item = _add_item(db, "https://example.com/h")
        _add_analysis(db, item, "2026-08-02T00:00:00+00:00", summary="one")
        _add_analysis(db, item, "2026-08-02T00:00:00+00:00", summary="two")

        dedupe_filter_analyses(db, apply=True)

        assert len(_filter_rows(db, item)) == 1
