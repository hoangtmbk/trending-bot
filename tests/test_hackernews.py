import json
from unittest.mock import patch, MagicMock
from collectors.hackernews import HackerNewsCollector
from models import RawItem


def _mock_search_response():
    return {
        "hits": [
            {
                "objectID": "12345",
                "title": "New AI Agent Framework Released",
                "url": "https://github.com/example/agent-framework",
                "points": 350,
                "num_comments": 120,
                "created_at_i": 1744070400,
                "created_at": "2026-04-08T00:00:00Z",
                "_tags": ["story"],
            },
            {
                "objectID": "12346",
                "title": "Cooking Recipe Manager",
                "url": "https://example.com/cooking",
                "points": 200,
                "num_comments": 50,
                "created_at_i": 1744070400,
                "created_at": "2026-04-08T00:00:00Z",
                "_tags": ["story"],
            },
        ]
    }


def test_hackernews_collector_returns_raw_items():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_search_response()

    with patch("collectors.hackernews.requests.get", return_value=mock_resp):
        collector = HackerNewsCollector()
        items = collector.collect()
        assert len(items) >= 1
        assert all(isinstance(i, RawItem) for i in items)
        assert items[0].source == "hackernews"


def test_hackernews_collector_includes_metrics():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_search_response()

    with patch("collectors.hackernews.requests.get", return_value=mock_resp):
        collector = HackerNewsCollector()
        items = collector.collect()
        assert "points" in items[0].metrics
        assert "num_comments" in items[0].metrics


def test_hackernews_collector_saves_to_file(tmp_data_dir):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_search_response()

    with patch("collectors.hackernews.requests.get", return_value=mock_resp):
        collector = HackerNewsCollector()
        items = collector.run(tmp_data_dir)
        saved_file = tmp_data_dir / "raw" / "hackernews.json"
        assert saved_file.exists()
        data = json.loads(saved_file.read_text())
        assert len(data) == len(items)
