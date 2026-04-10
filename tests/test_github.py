import json
from unittest.mock import patch, MagicMock
from collectors.github import GitHubCollector
from models import RawItem


def _mock_rising_stars_response():
    return {
        "items": [
            {
                "full_name": "new-org/cool-agent",
                "html_url": "https://github.com/new-org/cool-agent",
                "description": "A brand new AI agent framework",
                "stargazers_count": 500,
                "forks_count": 30,
                "created_at": "2026-04-05T00:00:00Z",
                "pushed_at": "2026-04-08T00:00:00Z",
                "topics": ["ai", "agents"],
                "language": "Python",
            }
        ]
    }


def _mock_breakout_response():
    return {
        "items": [
            {
                "full_name": "big-org/established-ml",
                "html_url": "https://github.com/big-org/established-ml",
                "description": "Well-known ML library with major update",
                "stargazers_count": 8000,
                "forks_count": 400,
                "created_at": "2025-01-01T00:00:00Z",
                "pushed_at": "2026-04-08T00:00:00Z",
                "topics": ["ai", "machine-learning"],
                "language": "Python",
            }
        ]
    }


def test_github_collector_uses_two_strategies():
    """Collector should make both rising-stars and breakout queries per topic."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = [_mock_rising_stars_response(), _mock_breakout_response()]

    with patch("collectors.github.requests.get", return_value=mock_resp) as mock_get:
        collector = GitHubCollector(token="fake", topics=["ai"])
        items = collector.collect()
        assert mock_get.call_count == 2


def test_github_collector_computes_age_days():
    """Items should have age_days in metrics."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_rising_stars_response()

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake", topics=["ai"])
        items = collector.collect()
        assert len(items) >= 1
        assert "age_days" in items[0].metrics
        assert items[0].metrics["age_days"] > 0


def test_github_collector_uses_description_as_title():
    """Title should use description when available, not bare full_name."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_rising_stars_response()

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake", topics=["ai"])
        items = collector.collect()
        assert items[0].title == "A brand new AI agent framework"


def test_github_collector_falls_back_to_full_name():
    """Title falls back to full_name when description is empty."""
    resp_data = _mock_rising_stars_response()
    resp_data["items"][0]["description"] = ""

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = resp_data

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake", topics=["ai"])
        items = collector.collect()
        assert items[0].title == "new-org/cool-agent"


def test_github_collector_deduplicates_across_strategies():
    """Same repo appearing in both strategies should be deduplicated."""
    same_repo = {
        "full_name": "org/repo",
        "html_url": "https://github.com/org/repo",
        "description": "Shared repo",
        "stargazers_count": 1000,
        "forks_count": 50,
        "created_at": "2026-04-03T00:00:00Z",
        "pushed_at": "2026-04-08T00:00:00Z",
        "topics": ["ai"],
        "language": "Python",
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": [same_repo]}

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake", topics=["ai"])
        items = collector.collect()
        assert len(items) == 1


def test_github_collector_saves_to_file(tmp_data_dir):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_rising_stars_response()

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake", topics=["ai"])
        items = collector.run(tmp_data_dir)
        saved = tmp_data_dir / "raw" / "github.json"
        assert saved.exists()
        data = json.loads(saved.read_text())
        assert len(data) == len(items)


def test_github_collector_reads_config_thresholds():
    """Collector should accept min_stars_new and min_stars_established."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": []}

    with patch("collectors.github.requests.get", return_value=mock_resp) as mock_get:
        collector = GitHubCollector(
            token="fake", topics=["ai"],
            min_stars_new=50, min_stars_established=1000,
        )
        collector.collect()
        calls = mock_get.call_args_list
        queries = [c.kwargs.get("params", {}).get("q", "") for c in calls]
        assert any("stars:>50" in q for q in queries)
        assert any("stars:>1000" in q for q in queries)
