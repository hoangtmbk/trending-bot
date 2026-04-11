import pytest
from unittest.mock import patch, MagicMock
from db.database import Database
from db.queries import get_items, get_score_history
from orchestrator.events import EventBus
from agents.base import AgentContext
from agents.scouts.github_scout import GitHubScout
from agents.scouts.reddit_scout import RedditScout
from agents.scouts.arxiv_scout import ArxivScout
from agents.scouts.huggingface_scout import HuggingFaceScout
from agents.scouts.hackernews_scout import HackerNewsScout
from agents.scouts.twitter_scout import TwitterScout
from models import RawItem


# ---------- fixtures ----------

@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture
def event_bus():
    return EventBus()


def _make_ctx(db, event_bus, source_name, enabled=True, extra_cfg=None):
    cfg = {source_name: {"enabled": enabled}}
    if extra_cfg:
        cfg[source_name].update(extra_cfg)
    return AgentContext(
        db=db,
        event_bus=event_bus,
        config={"sources": cfg},
    )


def _make_raw(source, url, title="Test Item", metrics=None):
    return RawItem(
        title=title,
        url=url,
        source=source,
        description="A test item",
        metrics=metrics or {},
        timestamp="2026-04-10T00:00:00Z",
    )


# ========== GitHub Scout ==========

class TestGitHubScout:

    @patch("scoring.momentum.compute_momentum_score", return_value=42.0)
    @patch("collectors.github.GitHubCollector.collect")
    @patch("config.get_env", return_value="fake-token")
    def test_collect_writes_to_db(self, mock_env, mock_collect, mock_momentum, db, event_bus):
        mock_collect.return_value = [
            _make_raw("github", "https://github.com/test/repo1",
                       metrics={"stargazers_count": 100, "forks_count": 10, "age_days": 2}),
            _make_raw("github", "https://github.com/test/repo2",
                       metrics={"stargazers_count": 200, "forks_count": 20, "age_days": 1}),
        ]
        ctx = _make_ctx(db, event_bus, "github", extra_cfg={"topics": ["ai"]})

        scout = GitHubScout()
        result = scout.execute(ctx)

        assert result.success is True
        assert result.data["count"] == 2
        assert len(result.data["item_ids"]) == 2

        items = get_items(db, source="github")
        assert len(items) == 2

        # Verify score snapshots were created
        for item_id in result.data["item_ids"]:
            history = get_score_history(db, item_id)
            assert len(history) == 1
            assert history[0]["momentum_score"] == 42.0

    def test_disabled_returns_early(self, db, event_bus):
        ctx = _make_ctx(db, event_bus, "github", enabled=False)
        scout = GitHubScout()
        result = scout.execute(ctx)
        assert result.success is True
        assert "disabled" in result.message.lower()
        assert get_items(db, source="github") == []

    @patch("config.get_env", side_effect=EnvironmentError("Missing GITHUB_TOKEN"))
    def test_missing_token_handled(self, mock_env, db, event_bus):
        ctx = _make_ctx(db, event_bus, "github")
        scout = GitHubScout()
        result = scout.execute(ctx)
        assert result.success is False
        assert "GITHUB_TOKEN" in result.message

    @patch("scoring.momentum.compute_momentum_score", return_value=10.0)
    @patch("collectors.github.GitHubCollector.collect")
    @patch("config.get_env", return_value="fake-token")
    def test_emits_items_updated(self, mock_env, mock_collect, mock_momentum, db, event_bus):
        mock_collect.return_value = [
            _make_raw("github", "https://github.com/test/repo1",
                       metrics={"stargazers_count": 50, "forks_count": 5, "age_days": 3}),
        ]
        received = []
        event_bus.subscribe("items_updated", lambda d: received.append(d))

        ctx = _make_ctx(db, event_bus, "github", extra_cfg={"topics": ["ai"]})
        scout = GitHubScout()
        scout.execute(ctx)

        assert len(received) == 1
        assert received[0]["source"] == "github"
        assert received[0]["count"] == 1


# ========== Reddit Scout ==========

class TestRedditScout:

    @patch("scoring.momentum.compute_momentum_score", return_value=5.0)
    @patch("collectors.reddit.RedditPublicCollector.collect")
    @patch("config.get_env", side_effect=EnvironmentError("no creds"))
    def test_fallback_to_public_collector(self, mock_env, mock_collect, mock_momentum, db, event_bus):
        mock_collect.return_value = [
            _make_raw("reddit", "https://reddit.com/r/test/1",
                       metrics={"score": 100, "upvote_ratio": 0.95, "num_comments": 30,
                                "total_awards": 0, "num_crossposts": 0, "subreddit": "test"}),
        ]
        ctx = _make_ctx(db, event_bus, "reddit", extra_cfg={"subreddits": ["test"]})

        scout = RedditScout()
        result = scout.execute(ctx)

        assert result.success is True
        assert result.data["count"] == 1
        items = get_items(db, source="reddit")
        assert len(items) == 1

    def test_disabled_returns_early(self, db, event_bus):
        ctx = _make_ctx(db, event_bus, "reddit", enabled=False)
        scout = RedditScout()
        result = scout.execute(ctx)
        assert result.success is True
        assert "disabled" in result.message.lower()

    @patch("scoring.momentum.compute_momentum_score", return_value=8.0)
    @patch("collectors.reddit.RedditPublicCollector.collect")
    @patch("config.get_env", side_effect=EnvironmentError("no creds"))
    def test_emits_event(self, mock_env, mock_collect, mock_momentum, db, event_bus):
        mock_collect.return_value = [
            _make_raw("reddit", "https://reddit.com/r/test/2",
                       metrics={"score": 50, "upvote_ratio": 0.9, "num_comments": 10,
                                "total_awards": 0, "num_crossposts": 0, "subreddit": "test"}),
        ]
        received = []
        event_bus.subscribe("items_updated", lambda d: received.append(d))

        ctx = _make_ctx(db, event_bus, "reddit", extra_cfg={"subreddits": ["test"]})
        scout = RedditScout()
        scout.execute(ctx)

        assert len(received) == 1
        assert received[0]["source"] == "reddit"


# ========== arXiv Scout ==========

class TestArxivScout:

    @patch("scoring.momentum.compute_momentum_score", return_value=3.0)
    @patch("collectors.arxiv.ArxivCollector.collect")
    def test_collect_writes_to_db(self, mock_collect, mock_momentum, db, event_bus):
        mock_collect.return_value = [
            _make_raw("arxiv", "http://arxiv.org/abs/2026.12345",
                       title="Attention Is Still All You Need",
                       metrics={"arxiv_id": "2026.12345", "citation_count": 5,
                                "influential_citations": 1, "categories": ["cs.AI"]}),
        ]
        ctx = _make_ctx(db, event_bus, "arxiv", extra_cfg={"categories": ["cs.AI"]})

        scout = ArxivScout()
        result = scout.execute(ctx)

        assert result.success is True
        assert result.data["count"] == 1
        items = get_items(db, source="arxiv")
        assert len(items) == 1
        assert items[0]["title"] == "Attention Is Still All You Need"

    def test_disabled_returns_early(self, db, event_bus):
        ctx = _make_ctx(db, event_bus, "arxiv", enabled=False)
        scout = ArxivScout()
        result = scout.execute(ctx)
        assert result.success is True
        assert "disabled" in result.message.lower()

    @patch("scoring.momentum.compute_momentum_score", return_value=7.0)
    @patch("collectors.arxiv.ArxivCollector.collect")
    def test_emits_event(self, mock_collect, mock_momentum, db, event_bus):
        mock_collect.return_value = [
            _make_raw("arxiv", "http://arxiv.org/abs/2026.99999",
                       metrics={"arxiv_id": "2026.99999", "citation_count": 0,
                                "influential_citations": 0, "categories": ["cs.CL"]}),
            _make_raw("arxiv", "http://arxiv.org/abs/2026.88888",
                       metrics={"arxiv_id": "2026.88888", "citation_count": 2,
                                "influential_citations": 0, "categories": ["cs.LG"]}),
        ]
        received = []
        event_bus.subscribe("items_updated", lambda d: received.append(d))

        ctx = _make_ctx(db, event_bus, "arxiv")
        scout = ArxivScout()
        scout.execute(ctx)

        assert len(received) == 1
        assert received[0]["count"] == 2


# ========== HuggingFace Scout ==========

class TestHuggingFaceScout:

    @patch("scoring.momentum.compute_momentum_score", return_value=1.5)
    @patch("collectors.huggingface.HuggingFaceCollector.collect")
    def test_collect_writes_to_db(self, mock_collect, mock_momentum, db, event_bus):
        mock_collect.return_value = [
            _make_raw("huggingface", "https://huggingface.co/test/model",
                       title="test/model",
                       metrics={"downloads": 5000, "likes": 100, "tags": ["text-generation"],
                                "pipeline_tag": "text-generation"}),
        ]
        ctx = _make_ctx(db, event_bus, "huggingface")

        scout = HuggingFaceScout()
        result = scout.execute(ctx)

        assert result.success is True
        assert result.data["count"] == 1
        items = get_items(db, source="huggingface")
        assert len(items) == 1

    def test_disabled_returns_early(self, db, event_bus):
        ctx = _make_ctx(db, event_bus, "huggingface", enabled=False)
        scout = HuggingFaceScout()
        result = scout.execute(ctx)
        assert result.success is True
        assert "disabled" in result.message.lower()

    @patch("scoring.momentum.compute_momentum_score", return_value=2.0)
    @patch("collectors.huggingface.HuggingFaceCollector.collect")
    def test_emits_event(self, mock_collect, mock_momentum, db, event_bus):
        mock_collect.return_value = [
            _make_raw("huggingface", "https://huggingface.co/a/b",
                       metrics={"downloads": 100, "likes": 5, "tags": [], "pipeline_tag": ""}),
        ]
        received = []
        event_bus.subscribe("items_updated", lambda d: received.append(d))

        ctx = _make_ctx(db, event_bus, "huggingface")
        scout = HuggingFaceScout()
        scout.execute(ctx)

        assert len(received) == 1
        assert received[0]["source"] == "huggingface"


# ========== Hacker News Scout ==========

class TestHackerNewsScout:

    @patch("scoring.momentum.compute_momentum_score", return_value=12.0)
    @patch("collectors.hackernews.HackerNewsCollector.collect")
    def test_collect_writes_to_db(self, mock_collect, mock_momentum, db, event_bus):
        mock_collect.return_value = [
            _make_raw("hackernews", "https://news.ycombinator.com/item?id=123",
                       title="Show HN: AI thing",
                       metrics={"points": 150, "num_comments": 42, "objectID": "123"}),
        ]
        ctx = _make_ctx(db, event_bus, "hackernews")

        scout = HackerNewsScout()
        result = scout.execute(ctx)

        assert result.success is True
        assert result.data["count"] == 1
        items = get_items(db, source="hackernews")
        assert len(items) == 1
        assert items[0]["title"] == "Show HN: AI thing"

    def test_disabled_returns_early(self, db, event_bus):
        ctx = _make_ctx(db, event_bus, "hackernews", enabled=False)
        scout = HackerNewsScout()
        result = scout.execute(ctx)
        assert result.success is True
        assert "disabled" in result.message.lower()

    @patch("scoring.momentum.compute_momentum_score", return_value=6.0)
    @patch("collectors.hackernews.HackerNewsCollector.collect")
    def test_emits_event(self, mock_collect, mock_momentum, db, event_bus):
        mock_collect.return_value = [
            _make_raw("hackernews", "https://news.ycombinator.com/item?id=456",
                       metrics={"points": 80, "num_comments": 20, "objectID": "456"}),
        ]
        received = []
        event_bus.subscribe("items_updated", lambda d: received.append(d))

        ctx = _make_ctx(db, event_bus, "hackernews")
        scout = HackerNewsScout()
        scout.execute(ctx)

        assert len(received) == 1
        assert received[0]["source"] == "hackernews"
        assert received[0]["count"] == 1


# ========== Twitter Scout ==========

class TestTwitterScout:

    @patch("scoring.momentum.compute_momentum_score", return_value=0.0)
    @patch("collectors.twitter.TwitterCollector.collect")
    def test_collect_writes_to_db(self, mock_collect, mock_momentum, db, event_bus):
        mock_collect.return_value = [
            _make_raw("twitter", "https://twitter.com/user/status/1",
                       title="AI tweet",
                       metrics={"retweets": 50, "quotes": 10}),
        ]
        ctx = _make_ctx(db, event_bus, "twitter", extra_cfg={"fallback_to_rss": True})

        scout = TwitterScout()
        result = scout.execute(ctx)

        assert result.success is True
        assert result.data["count"] == 1
        items = get_items(db, source="twitter")
        assert len(items) == 1

    def test_disabled_returns_early(self, db, event_bus):
        ctx = _make_ctx(db, event_bus, "twitter", enabled=False)
        scout = TwitterScout()
        result = scout.execute(ctx)
        assert result.success is True
        assert "disabled" in result.message.lower()

    @patch("scoring.momentum.compute_momentum_score", return_value=0.0)
    @patch("collectors.twitter.TwitterCollector.collect")
    def test_empty_collect_still_emits(self, mock_collect, mock_momentum, db, event_bus):
        mock_collect.return_value = []
        received = []
        event_bus.subscribe("items_updated", lambda d: received.append(d))

        ctx = _make_ctx(db, event_bus, "twitter")
        scout = TwitterScout()
        scout.execute(ctx)

        assert len(received) == 1
        assert received[0]["source"] == "twitter"
        assert received[0]["count"] == 0


# ========== Cross-cutting tests ==========

class TestScoutUpsertBehavior:
    """Verify that calling a scout twice on the same item updates rather than duplicates."""

    @patch("scoring.momentum.compute_momentum_score", return_value=50.0)
    @patch("collectors.github.GitHubCollector.collect")
    @patch("config.get_env", return_value="fake-token")
    def test_upsert_increments_times_seen(self, mock_env, mock_collect, mock_momentum, db, event_bus):
        raw = _make_raw("github", "https://github.com/test/repo",
                         metrics={"stargazers_count": 100, "forks_count": 10, "age_days": 2})
        mock_collect.return_value = [raw]

        ctx = _make_ctx(db, event_bus, "github", extra_cfg={"topics": ["ai"]})
        scout = GitHubScout()

        # Run twice
        scout.execute(ctx)
        result = scout.execute(ctx)

        items = get_items(db, source="github")
        assert len(items) == 1
        assert items[0]["times_seen"] == 2

        # Two snapshots recorded
        history = get_score_history(db, items[0]["id"])
        assert len(history) == 2
