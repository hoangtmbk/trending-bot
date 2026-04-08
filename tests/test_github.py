import json
from unittest.mock import patch, MagicMock
from collectors.github import GitHubCollector
from models import RawItem


def _mock_search_response():
    return {
        "items": [
            {
                "full_name": "example/agentkit",
                "html_url": "https://github.com/example/agentkit",
                "description": "Multi-agent framework",
                "stargazers_count": 3000,
                "forks_count": 150,
                "created_at": "2026-03-01T00:00:00Z",
                "pushed_at": "2026-04-08T00:00:00Z",
                "topics": ["ai", "agents", "llm"],
                "language": "Python",
            }
        ]
    }


def test_github_collector_returns_raw_items():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_search_response()

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake_token", topics=["ai"])
        items = collector.collect()
        assert len(items) >= 1
        assert items[0].source == "github"
        assert "stargazers_count" in items[0].metrics


def test_github_collector_saves_to_file(tmp_data_dir):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_search_response()

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake_token", topics=["ai"])
        items = collector.run(tmp_data_dir)
        saved = tmp_data_dir / "raw" / "github.json"
        assert saved.exists()
        data = json.loads(saved.read_text())
        assert len(data) == len(items)
