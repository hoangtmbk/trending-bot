"""Tests for collectors/hf_papers.py (HuggingFace Daily Papers)."""
from unittest.mock import patch, MagicMock

from collectors.hf_papers import HuggingFacePapersCollector


def _resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status}")
    return r


def test_parses_papers_to_raw_items():
    payload = [
        {
            "paper": {
                "id": "2604.12345",
                "title": "Scaling Laws for Attention",
                "summary": "We study …",
                "upvotes": 42,
            },
            "publishedAt": "2026-04-19T00:00:00Z",
        }
    ]
    with patch("collectors.hf_papers.requests.get", return_value=_resp(payload)):
        items = HuggingFacePapersCollector().collect()
    assert len(items) == 1
    assert items[0].source == "hf_papers"
    assert items[0].url == "https://arxiv.org/abs/2604.12345"
    assert items[0].title == "Scaling Laws for Attention"
    assert items[0].metrics["arxiv_id"] == "2604.12345"
    assert items[0].metrics["upvotes"] == 42


def test_skips_rows_missing_id_or_title():
    payload = [
        {"paper": {"title": "no id"}},
        {"paper": {"id": "2604.1"}},  # no title
        {"paper": {"id": "2604.2", "title": "ok", "upvotes": 1}},
    ]
    with patch("collectors.hf_papers.requests.get", return_value=_resp(payload)):
        items = HuggingFacePapersCollector().collect()
    assert len(items) == 1
    assert items[0].metrics["arxiv_id"] == "2604.2"


def test_network_failure_returns_empty():
    with patch("collectors.hf_papers.requests.get",
               side_effect=Exception("timeout")):
        assert HuggingFacePapersCollector().collect() == []


def test_http_error_returns_empty():
    with patch("collectors.hf_papers.requests.get",
               return_value=_resp([], status=500)):
        assert HuggingFacePapersCollector().collect() == []
