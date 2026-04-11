import json
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


# ── GET /api/items ──

class TestApiItems:
    def test_empty_db(self, client):
        resp = client.get("/api/items")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["count"] == 0

    def test_with_data(self, seeded_client):
        resp = seeded_client.get("/api/items")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        # Items should be ordered by normalized_score DESC
        assert data["items"][0]["normalized_score"] == 85.0
        assert data["items"][1]["normalized_score"] == 60.0

    def test_filter_by_source(self, seeded_client):
        resp = seeded_client.get("/api/items?source=github")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["source"] == "github"

    def test_limit(self, seeded_client):
        resp = seeded_client.get("/api/items?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_raw_metrics_parsed(self, seeded_client):
        resp = seeded_client.get("/api/items")
        data = resp.json()
        item = data["items"][0]
        assert isinstance(item["raw_metrics"], dict)
        assert "stars_24h" in item["raw_metrics"]


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
    def test_home_page(self, seeded_client):
        resp = seeded_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Trending Items" in resp.text
        assert "Example Repo One" in resp.text

    def test_home_page_empty(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "No items found" in resp.text

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
