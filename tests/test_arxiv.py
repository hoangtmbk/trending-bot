from unittest.mock import patch, MagicMock
from collectors.arxiv import ArxivCollector
from models import RawItem


def _mock_arxiv_result():
    result = MagicMock()
    result.title = "Scaling Test-Time Compute for Better Reasoning"
    result.entry_id = "http://arxiv.org/abs/2604.12345v1"
    result.summary = "We show that scaling compute at test time..."
    result.published.isoformat.return_value = "2026-04-07T00:00:00Z"
    result.authors = [MagicMock()]
    result.categories = ["cs.AI", "cs.CL"]
    result.pdf_url = "http://arxiv.org/pdf/2604.12345v1"
    return result


def _mock_semantic_scholar_response():
    return {"citationCount": 15, "influentialCitationCount": 3}


def test_arxiv_collector_returns_raw_items():
    mock_result = _mock_arxiv_result()
    mock_client = MagicMock()
    mock_client.results.return_value = [mock_result]

    with patch("collectors.arxiv.arxiv.Client", return_value=mock_client), \
         patch("collectors.arxiv.arxiv.Search"), \
         patch("collectors.arxiv.requests.get") as mock_get:
        mock_s2_resp = MagicMock()
        mock_s2_resp.status_code = 200
        mock_s2_resp.json.return_value = _mock_semantic_scholar_response()
        mock_get.return_value = mock_s2_resp

        collector = ArxivCollector(categories=["cs.AI"])
        items = collector.collect()
        assert len(items) >= 1
        assert items[0].source == "arxiv"
        assert "citation_count" in items[0].metrics


def test_arxiv_collector_handles_s2_failure():
    mock_result = _mock_arxiv_result()
    mock_client = MagicMock()
    mock_client.results.return_value = [mock_result]

    with patch("collectors.arxiv.arxiv.Client", return_value=mock_client), \
         patch("collectors.arxiv.arxiv.Search"), \
         patch("collectors.arxiv.requests.get") as mock_get:
        mock_get.side_effect = Exception("S2 down")

        collector = ArxivCollector(categories=["cs.AI"])
        items = collector.collect()
        assert len(items) >= 1
        assert items[0].metrics["citation_count"] == 0
