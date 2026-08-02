import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from db.database import Database
from db.queries import upsert_item, enqueue_task, snapshot_score
from interfaces.web.app import create_app


@pytest.fixture
def db(tmp_path):
    database = Database(db_path=tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def client(db):
    app = create_app(db, config={})
    return TestClient(app)


@pytest.fixture
def seeded_db(db):
    """Insert a couple of items for tests that need data."""
    upsert_item(
        db,
        url="https://github.com/example/repo1",
        title="Example Repo One",
        source="github",
        description="A cool AI framework",
        raw_metrics={"stars_24h": 500, "total_stars": 2000},
        momentum_score=75.0,
        normalized_score=85.0,
    )
    upsert_item(
        db,
        url="https://reddit.com/r/ml/post2",
        title="Reddit ML Post",
        source="reddit",
        description="Discussion about transformers",
        raw_metrics={"upvotes": 300},
        momentum_score=50.0,
        normalized_score=60.0,
    )
    return db


@pytest.fixture
def seeded_client(seeded_db):
    app = create_app(seeded_db, config={})
    return TestClient(app)


@pytest.fixture
def filtered_client(seeded_db):
    """seeded_db plus filter analyses so /api/items and / return the seeded items."""
    with seeded_db.connect() as conn:
        for item_id, score in [(1, 8), (2, 7)]:
            conn.execute(
                "INSERT INTO item_analysis (item_id, analysis_type, created_at, content) "
                "VALUES (?, 'filter', datetime('now'), ?)",
                (item_id, json.dumps({
                    "novel": True, "ai_relevant": True,
                    "interest_score": score, "summary": f"Summary {item_id}",
                    "category": "tool",
                })),
            )
        conn.commit()
    app = create_app(seeded_db, config={})
    return TestClient(app)


# ── GET /api/items ──

class TestApiItems:
    def test_empty_db(self, client):
        resp = client.get("/api/items")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["count"] == 0

    def test_with_data(self, filtered_client):
        resp = filtered_client.get("/api/items")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        # Ordered by interest_score DESC (item 1 has 8, item 2 has 7).
        assert data["items"][0]["interest_score"] == 8
        assert data["items"][1]["interest_score"] == 7

    def test_filter_by_source(self, filtered_client):
        resp = filtered_client.get("/api/items?source=github")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["source"] == "github"

    def test_limit(self, filtered_client):
        resp = filtered_client.get("/api/items?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_raw_metrics_parsed(self, filtered_client):
        resp = filtered_client.get("/api/items")
        data = resp.json()
        item = data["items"][0]
        assert isinstance(item["raw_metrics"], dict)
        assert "stars_24h" in item["raw_metrics"]


def _insert_filter_analysis(db, item_id: int, *, novel=True, ai_relevant=True,
                            interest_score=7, summary="S", category="tool"):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO item_analysis (item_id, analysis_type, created_at, content) "
            "VALUES (?, 'filter', datetime('now'), ?)",
            (item_id, json.dumps({
                "novel": novel, "ai_relevant": ai_relevant,
                "interest_score": interest_score, "summary": summary,
                "category": category,
            })),
        )
        conn.commit()


class TestFilterGatedItems:
    """GET /api/items only returns items with a latest filter verdict,
    gated on novel AND ai_relevant AND interest_score >= threshold.
    Why: the bare items table ordered by normalized_score surfaces low-signal
    Reddit chatter ('lol', 'Hollywood is so screwed') at the top — see review
    2026-04-19."""

    def test_excludes_unfiltered(self, seeded_client, seeded_db):
        # Neither seeded item has a filter row yet.
        resp = seeded_client.get("/api/items")
        assert resp.json()["count"] == 0

    def test_excludes_low_interest(self, seeded_client, seeded_db):
        _insert_filter_analysis(seeded_db, 1, interest_score=3)
        _insert_filter_analysis(seeded_db, 2, interest_score=7)
        resp = seeded_client.get("/api/items")
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["id"] == 2

    def test_excludes_not_novel(self, seeded_client, seeded_db):
        _insert_filter_analysis(seeded_db, 1, novel=False, interest_score=9)
        _insert_filter_analysis(seeded_db, 2, interest_score=7)
        resp = seeded_client.get("/api/items")
        data = resp.json()
        ids = [it["id"] for it in data["items"]]
        assert 1 not in ids and 2 in ids

    def test_returns_llm_summary_and_interest(self, seeded_client, seeded_db):
        _insert_filter_analysis(seeded_db, 1, interest_score=8,
                                summary="Why it matters", category="model")
        resp = seeded_client.get("/api/items")
        item = resp.json()["items"][0]
        assert item["llm_summary"] == "Why it matters"
        assert item["interest_score"] == 8
        assert item["category"] == "model"

    def test_orders_by_interest_then_score(self, seeded_client, seeded_db):
        _insert_filter_analysis(seeded_db, 1, interest_score=7)  # normalized 85
        _insert_filter_analysis(seeded_db, 2, interest_score=9)  # normalized 60
        resp = seeded_client.get("/api/items")
        ids = [it["id"] for it in resp.json()["items"]]
        assert ids == [2, 1]

    def test_uses_latest_filter_row(self, seeded_client, seeded_db):
        # Insert an old low score, then a newer high score for the same item.
        with seeded_db.connect() as conn:
            conn.execute(
                "INSERT INTO item_analysis (item_id, analysis_type, created_at, content) "
                "VALUES (?, 'filter', '2020-01-01 00:00:00', ?)",
                (1, json.dumps({"novel": True, "ai_relevant": True,
                                "interest_score": 1, "summary": "old"})),
            )
            conn.commit()
        _insert_filter_analysis(seeded_db, 1, interest_score=8, summary="new")
        resp = seeded_client.get("/api/items")
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["interest_score"] == 8
        assert data["items"][0]["llm_summary"] == "new"


# ── GET /api/items/{id} ──

class TestApiItemDetail:
    def test_found(self, seeded_client):
        resp = seeded_client.get("/api/items/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Example Repo One"
        assert isinstance(data["raw_metrics"], dict)

    def test_not_found(self, client):
        resp = client.get("/api/items/999")
        assert resp.status_code == 404


# ── GET /api/items/{id}/analysis ──

class TestApiItemAnalysis:
    def test_no_analyses(self, seeded_client):
        resp = seeded_client.get("/api/items/1/analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert data["analyses"] == []

    def test_with_analysis(self, seeded_db):
        with seeded_db.connect() as conn:
            conn.execute(
                "INSERT INTO item_analysis (item_id, analysis_type, created_at, content) "
                "VALUES (?, ?, datetime('now'), ?)",
                (1, "deep_dive", json.dumps({"summary": "Great project", "rating": 9})),
            )
            conn.commit()
        app = create_app(seeded_db, config={})
        client = TestClient(app)
        resp = client.get("/api/items/1/analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["analyses"]) == 1
        assert data["analyses"][0]["content"]["summary"] == "Great project"


# ── GET /api/items/{id}/scores ──

class TestApiItemScores:
    def test_score_history(self, seeded_db):
        snapshot_score(seeded_db, item_id=1, momentum_score=70.0, normalized_score=80.0,
                       raw_metrics={"stars_24h": 400})
        snapshot_score(seeded_db, item_id=1, momentum_score=75.0, normalized_score=85.0,
                       raw_metrics={"stars_24h": 500})
        app = create_app(seeded_db, config={})
        client = TestClient(app)
        resp = client.get("/api/items/1/scores")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["scores"]) == 2


# ── POST /api/items/{id}/action ──

class TestApiItemAction:
    def test_valid_action(self, seeded_client, seeded_db):
        resp = seeded_client.post("/api/items/1/action", json={"action": "bookmarked"})
        assert resp.status_code == 200
        assert resp.json()["action"] == "bookmarked"
        # Verify persisted
        with seeded_db.connect() as conn:
            row = conn.execute("SELECT * FROM user_actions WHERE item_id=1").fetchone()
            assert row is not None
            assert row["action"] == "bookmarked"

    def test_invalid_action(self, seeded_client):
        resp = seeded_client.post("/api/items/1/action", json={"action": "invalid_action"})
        assert resp.status_code == 400

    def test_deep_dive_requested_enqueues_task(self, seeded_client, seeded_db):
        resp = seeded_client.post("/api/items/1/action", json={"action": "deep_dive_requested"})
        assert resp.status_code == 200
        with seeded_db.connect() as conn:
            task = conn.execute(
                "SELECT * FROM task_queue WHERE agent_type='deep_diver'"
            ).fetchone()
            assert task is not None
            payload = json.loads(task["payload"])
            assert payload["item_id"] == 1


# ── POST /api/research/deepdive ──

class TestApiResearchDeepdive:
    def test_enqueue(self, seeded_client, seeded_db):
        resp = seeded_client.post("/api/research/deepdive", json={"item_id": 1})
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_missing_item_id(self, seeded_client):
        resp = seeded_client.post("/api/research/deepdive", json={})
        assert resp.status_code == 400


# ── GET /api/topics & POST /api/topics ──

class TestApiTopics:
    def test_empty_topics(self, client):
        resp = client.get("/api/topics")
        assert resp.status_code == 200
        assert resp.json()["topics"] == []

    def test_create_and_list_topic(self, client):
        resp = client.post("/api/topics", json={"name": "LLM Agents", "weight": 3.0})
        assert resp.status_code == 200
        assert resp.json()["topic"] == "llm agents"

        resp = client.get("/api/topics")
        assert resp.status_code == 200
        topics = resp.json()["topics"]
        assert len(topics) == 1
        assert topics[0]["name"] == "llm agents"
        assert topics[0]["weight"] == 3.0

    def test_create_topic_missing_name(self, client):
        resp = client.post("/api/topics", json={"name": ""})
        assert resp.status_code == 400


# ── GET /api/connections ──

class TestApiConnections:
    def test_empty_connections(self, client):
        resp = client.get("/api/connections")
        assert resp.status_code == 200
        assert resp.json()["connections"] == []

    def test_with_connections(self, seeded_db):
        with seeded_db.connect() as conn:
            conn.execute(
                "INSERT INTO item_connections (item_a_id, item_b_id, relationship, description, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (1, 2, "same_topic", "Both about AI"),
            )
            conn.commit()
        app = create_app(seeded_db, config={})
        client = TestClient(app)
        resp = client.get("/api/connections")
        assert resp.status_code == 200
        conns = resp.json()["connections"]
        assert len(conns) == 1
        assert conns[0]["title_a"] == "Example Repo One"

    def test_filter_by_item_id(self, seeded_db):
        with seeded_db.connect() as conn:
            conn.execute(
                "INSERT INTO item_connections (item_a_id, item_b_id, relationship, description, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (1, 2, "same_topic", "Both about AI"),
            )
            conn.commit()
        app = create_app(seeded_db, config={})
        client = TestClient(app)
        resp = client.get("/api/connections?item_id=1")
        assert resp.status_code == 200
        assert len(resp.json()["connections"]) == 1


# ── GET /api/digests ──

class TestApiDigests:
    def test_empty(self, client):
        resp = client.get("/api/digests")
        assert resp.status_code == 200
        assert resp.json()["digests"] == []


# ── HTML Pages ──

class TestHtmlPages:
    def test_home_page(self, filtered_client):
        resp = filtered_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Trending Items" in resp.text
        assert "Example Repo One" in resp.text

    def test_home_page_empty(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "No filter-approved items yet" in resp.text

    def test_item_page(self, seeded_client):
        resp = seeded_client.get("/item/1")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Example Repo One" in resp.text

    def test_item_page_not_found(self, client):
        resp = client.get("/item/999")
        assert resp.status_code == 404

    def test_topics_page(self, client):
        resp = client.get("/topics")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Topics" in resp.text


# ── GET /api/health ──

class TestApiHealth:
    def test_returns_ok_true(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_includes_version_field(self, client):
        resp = client.get("/api/health")
        body = resp.json()
        assert "version" in body
        assert isinstance(body["version"], str)

    def test_does_not_require_seeded_db(self, client):
        # Same fixture as the other tests — uses an empty db via tmp_path.
        # Health must not read from the schema.
        resp = client.get("/api/health")
        assert resp.status_code == 200


# ── HTML routes (regression for Starlette 1.0 TemplateResponse signature) ──

class TestHtmlRoutes:
    def test_home_page_renders_on_empty_db(self, client):
        # Reproduces the `TypeError: unhashable type: 'dict'` regression
        # caused by Starlette 1.0's TemplateResponse signature flip.
        resp = client.get("/")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "").lower()

    def test_home_page_renders_with_items(self, seeded_client):
        resp = seeded_client.get("/")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "").lower()

    def test_item_detail_renders(self, seeded_client):
        # seeded_client has 2 items; id 1 should exist.
        resp = seeded_client.get("/item/1")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "").lower()

    def test_item_detail_404_for_missing(self, client):
        resp = client.get("/item/9999")
        assert resp.status_code == 404

    def test_topics_page_renders_on_empty_db(self, client):
        resp = client.get("/topics")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "").lower()


# ── Full-list browsing: the dashboard shows every eligible item ──

def _seed_many_filtered(db, count: int, interest_score: int = 7):
    for n in range(count):
        item_id = upsert_item(db, url=f"https://bulk.example/{n}",
                              title=f"Bulk Item {n}", source="hackernews",
                              description="", raw_metrics={},
                              normalized_score=float(count - n))
        _insert_filter_analysis(db, item_id, interest_score=interest_score)


class TestDashboardShowsAllItems:
    def test_home_page_renders_every_eligible_item(self, db):
        """The dashboard was capped at 30 cards; it must list the whole pool."""
        _seed_many_filtered(db, 42)
        client = TestClient(create_app(db, config={}))

        resp = client.get("/")

        assert resp.status_code == 200
        assert resp.text.count('data-item-id="') == 42

    def test_home_page_shows_the_total_count(self, db):
        _seed_many_filtered(db, 42)
        client = TestClient(create_app(db, config={}))

        resp = client.get("/")

        assert "Trending Items (42)" in resp.text


class TestApiItemsLimit:
    def test_accepts_limit_above_the_old_100_cap(self, db):
        _seed_many_filtered(db, 120)
        client = TestClient(create_app(db, config={}))

        resp = client.get("/api/items?limit=500")

        assert resp.status_code == 200
        assert resp.json()["count"] == 120

    def test_rejects_limit_beyond_the_hard_cap(self, client):
        resp = client.get("/api/items?limit=99999")
        assert resp.status_code == 422


# ── Card freshness: staleness must be visible at a glance ──

class TestAgeLabel:
    def test_minutes_old_reads_as_now(self):
        from interfaces.web.app import _age_label
        now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
        assert _age_label("2026-08-02T11:40:00+00:00", now=now) == "just now"

    def test_hours_old(self):
        from interfaces.web.app import _age_label
        now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
        assert _age_label("2026-08-02T07:00:00+00:00", now=now) == "5h ago"

    def test_days_old(self):
        from interfaces.web.app import _age_label
        now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
        assert _age_label("2026-05-22T12:00:00+00:00", now=now) == "72d ago"

    def test_unparseable_timestamp_yields_empty_label(self):
        from interfaces.web.app import _age_label
        assert _age_label("not-a-date") == ""

    def test_missing_timestamp_yields_empty_label(self):
        from interfaces.web.app import _age_label
        assert _age_label(None) == ""


class TestDashboardShowsItemAge:
    def test_card_renders_the_age_label(self, db):
        item_id = upsert_item(db, url="https://old.example/x", title="Stale One",
                              source="hackernews", description="", raw_metrics={})
        stale = (datetime.now(timezone.utc) - timedelta(days=72)).isoformat()
        with db.connect() as conn:
            conn.execute("UPDATE items SET last_seen=? WHERE id=?", (stale, item_id))
            conn.commit()
        _insert_filter_analysis(db, item_id, interest_score=8)
        client = TestClient(create_app(db, config={}))

        resp = client.get("/")

        assert "72d ago" in resp.text
