import json
import pytest
from db.database import Database
from db.queries import upsert_item
from memory.interests import (
    get_interest_profile,
    set_interest,
    apply_feedback_boost,
    compute_personal_relevance,
)
from memory.knowledge import get_item_context, get_trending_summary, search_items
from memory.connections import get_related_items, get_topic_graph


# ---------- fixtures ----------

@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


def _seed_item(db, title="Test Repo", url="https://github.com/test/repo", source="github",
               normalized_score=50.0, momentum_score=10.0):
    """Insert a single test item and return its id."""
    return upsert_item(
        db, url=url, title=title, source=source,
        description=f"Desc of {title}",
        raw_metrics={"stars": 100},
        momentum_score=momentum_score,
        normalized_score=normalized_score,
    )


def _seed_topic(db, name="ml-frameworks", source="system"):
    """Insert a topic and return its id."""
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO topics (name, source, created_at) VALUES (?, ?, datetime('now'))",
            (name, source),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM topics WHERE name=?", (name,)).fetchone()
    return row["id"]


def _link_item_topic(db, item_id, topic_id, confidence=1.0):
    """Create item_topics linkage."""
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO item_topics (item_id, topic_id, confidence) VALUES (?, ?, ?)",
            (item_id, topic_id, confidence),
        )
        conn.commit()


def _set_user_interest(db, topic_id, weight=1.5, source="explicit"):
    """Insert a user_interests row."""
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_interests (topic_id, weight, source, updated_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (topic_id, weight, source),
        )
        conn.commit()


def _add_connection(db, item_a_id, item_b_id, relationship="same_topic"):
    """Insert an item_connections row."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO item_connections (item_a_id, item_b_id, relationship, description, created_at) "
            "VALUES (?, ?, ?, 'test connection', datetime('now'))",
            (item_a_id, item_b_id, relationship),
        )
        conn.commit()


def _add_analysis(db, item_id, analysis_type="deep_dive"):
    """Insert an item_analysis row."""
    content = json.dumps({"summary": "Test analysis"})
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO item_analysis (item_id, analysis_type, created_at, content) "
            "VALUES (?, ?, datetime('now'), ?)",
            (item_id, analysis_type, content),
        )
        conn.commit()


# ========== Interest Profile ==========

class TestGetInterestProfile:

    def test_empty_profile(self, db):
        profile = get_interest_profile(db)
        assert profile == {}

    def test_with_data(self, db):
        t1 = _seed_topic(db, "llm")
        t2 = _seed_topic(db, "robotics")
        _set_user_interest(db, t1, weight=2.0)
        _set_user_interest(db, t2, weight=1.0)

        profile = get_interest_profile(db)
        assert profile == {"llm": 2.0, "robotics": 1.0}

    def test_excludes_inactive_topics(self, db):
        t1 = _seed_topic(db, "active-topic")
        _set_user_interest(db, t1, weight=1.5)

        # Deactivate the topic
        with db.connect() as conn:
            conn.execute("UPDATE topics SET is_active=0 WHERE id=?", (t1,))
            conn.commit()

        profile = get_interest_profile(db)
        assert profile == {}


class TestSetInterest:

    def test_creates_topic_and_interest(self, db):
        set_interest(db, "new-topic", 2.0, source="explicit")

        with db.connect() as conn:
            topic = conn.execute("SELECT * FROM topics WHERE name='new-topic'").fetchone()
            interest = conn.execute("SELECT * FROM user_interests WHERE topic_id=?", (topic["id"],)).fetchone()

        assert topic is not None
        assert topic["source"] == "user"
        assert interest["weight"] == 2.0
        assert interest["source"] == "explicit"

    def test_updates_existing(self, db):
        set_interest(db, "ml", 1.0)
        set_interest(db, "ml", 2.5)

        profile = get_interest_profile(db)
        assert profile["ml"] == 2.5

    def test_inferred_source(self, db):
        set_interest(db, "agents", 1.8, source="inferred")

        with db.connect() as conn:
            topic = conn.execute("SELECT * FROM topics WHERE name='agents'").fetchone()
        assert topic["source"] == "llm-inferred"


# ========== Feedback Boost ==========

class TestApplyFeedbackBoost:

    def test_bookmark_boosts(self, db):
        item_id = _seed_item(db)
        topic_id = _seed_topic(db, "frameworks")
        _link_item_topic(db, item_id, topic_id)
        _set_user_interest(db, topic_id, weight=1.0)

        apply_feedback_boost(db, item_id, "bookmarked")

        profile = get_interest_profile(db)
        assert profile["frameworks"] == pytest.approx(1.2)

    def test_dismiss_decays(self, db):
        item_id = _seed_item(db)
        topic_id = _seed_topic(db, "datasets")
        _link_item_topic(db, item_id, topic_id)
        _set_user_interest(db, topic_id, weight=1.0)

        apply_feedback_boost(db, item_id, "dismissed")

        profile = get_interest_profile(db)
        assert profile["datasets"] == pytest.approx(0.9)

    def test_capped_at_upper_bound(self, db):
        item_id = _seed_item(db)
        topic_id = _seed_topic(db, "hot-topic")
        _link_item_topic(db, item_id, topic_id)
        _set_user_interest(db, topic_id, weight=2.9)

        apply_feedback_boost(db, item_id, "bookmarked")

        profile = get_interest_profile(db)
        # 2.9 + 0.2 = 3.1, capped to 3.0
        assert profile["hot-topic"] == 3.0

    def test_capped_at_lower_bound(self, db):
        item_id = _seed_item(db)
        topic_id = _seed_topic(db, "cold-topic")
        _link_item_topic(db, item_id, topic_id)
        _set_user_interest(db, topic_id, weight=0.05)

        apply_feedback_boost(db, item_id, "dismissed")

        profile = get_interest_profile(db)
        # 0.05 - 0.1 = -0.05, capped to 0.0
        assert profile["cold-topic"] == 0.0

    def test_unknown_action_noop(self, db):
        item_id = _seed_item(db)
        topic_id = _seed_topic(db, "stable")
        _link_item_topic(db, item_id, topic_id)
        _set_user_interest(db, topic_id, weight=1.5)

        apply_feedback_boost(db, item_id, "deep_dive_requested")

        profile = get_interest_profile(db)
        assert profile["stable"] == 1.5


# ========== Personal Relevance ==========

class TestComputePersonalRelevance:

    def test_with_matching_topic(self, db):
        item_id = _seed_item(db)
        topic_id = _seed_topic(db, "rl")
        _link_item_topic(db, item_id, topic_id)
        _set_user_interest(db, topic_id, weight=2.5)

        score = compute_personal_relevance(db, item_id)
        assert score == 2.5

    def test_no_topics_returns_default(self, db):
        item_id = _seed_item(db)
        score = compute_personal_relevance(db, item_id)
        assert score == 1.0

    def test_no_interest_returns_default(self, db):
        """Item has topics but no user interest set -> COALESCE gives 1.0."""
        item_id = _seed_item(db)
        topic_id = _seed_topic(db, "untracked")
        _link_item_topic(db, item_id, topic_id)

        score = compute_personal_relevance(db, item_id)
        assert score == 1.0


# ========== Knowledge: get_item_context ==========

class TestGetItemContext:

    def test_returns_full_context(self, db):
        item_id = _seed_item(db, title="Context Test")
        topic_id = _seed_topic(db, "context-topic")
        _link_item_topic(db, item_id, topic_id)
        _add_analysis(db, item_id)

        ctx = get_item_context(db, item_id)
        assert ctx["item"]["title"] == "Context Test"
        assert isinstance(ctx["item"]["raw_metrics"], dict)
        assert len(ctx["analyses"]) == 1
        assert ctx["analyses"][0]["content"]["summary"] == "Test analysis"
        assert len(ctx["topics"]) == 1
        assert ctx["topics"][0]["name"] == "context-topic"

    def test_missing_item_returns_empty(self, db):
        ctx = get_item_context(db, 9999)
        assert ctx == {}

    def test_includes_connections(self, db):
        id1 = _seed_item(db, title="Item A", url="https://a.com")
        id2 = _seed_item(db, title="Item B", url="https://b.com")
        _add_connection(db, id1, id2)

        ctx = get_item_context(db, id1)
        assert len(ctx["connections"]) == 1


# ========== Knowledge: get_trending_summary ==========

class TestGetTrendingSummary:

    def test_sorts_by_effective_score(self, db):
        id1 = _seed_item(db, title="Low Interest", url="https://lo.com",
                         normalized_score=80.0)
        id2 = _seed_item(db, title="High Interest", url="https://hi.com",
                         normalized_score=50.0)

        topic_id = _seed_topic(db, "favorite")
        _link_item_topic(db, id2, topic_id)
        _set_user_interest(db, topic_id, weight=3.0)

        summary = get_trending_summary(db, days=7, limit=10)
        # id2: 50.0 * 3.0 = 150, id1: 80.0 * 1.0 = 80
        assert summary[0]["title"] == "High Interest"
        assert summary[1]["title"] == "Low Interest"


# ========== Knowledge: search_items ==========

class TestSearchItems:

    def test_finds_by_title(self, db):
        _seed_item(db, title="Awesome LLM Tool", url="https://llm.com")
        _seed_item(db, title="Robot Framework", url="https://robot.com")

        results = search_items(db, "LLM")
        assert len(results) == 1
        assert results[0]["title"] == "Awesome LLM Tool"

    def test_no_results(self, db):
        _seed_item(db, title="Something", url="https://x.com")
        results = search_items(db, "nonexistent")
        assert results == []


# ========== Connections: get_related_items ==========

class TestGetRelatedItems:

    def test_returns_connected_items(self, db):
        id1 = _seed_item(db, title="Main Item", url="https://main.com")
        id2 = _seed_item(db, title="Related A", url="https://a.com")
        id3 = _seed_item(db, title="Related B", url="https://b.com")
        _add_connection(db, id1, id2, "same_topic")
        _add_connection(db, id3, id1, "builds_on")

        related = get_related_items(db, id1)
        assert len(related) == 2
        titles = {r["title"] for r in related}
        assert "Related A" in titles
        assert "Related B" in titles

    def test_no_connections(self, db):
        item_id = _seed_item(db)
        related = get_related_items(db, item_id)
        assert related == []


# ========== Connections: get_topic_graph ==========

class TestGetTopicGraph:

    def test_returns_items_and_connections(self, db):
        id1 = _seed_item(db, title="Graph A", url="https://ga.com")
        id2 = _seed_item(db, title="Graph B", url="https://gb.com")
        topic_id = _seed_topic(db, "graph-topic")
        _link_item_topic(db, id1, topic_id)
        _link_item_topic(db, id2, topic_id)
        _add_connection(db, id1, id2)

        graph = get_topic_graph(db, "graph-topic")
        assert len(graph["items"]) == 2
        assert len(graph["connections"]) == 1

    def test_empty_topic(self, db):
        graph = get_topic_graph(db, "nonexistent")
        assert graph["items"] == []
        assert graph["connections"] == []
