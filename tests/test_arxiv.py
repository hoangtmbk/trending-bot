from unittest.mock import patch, MagicMock
from collectors.arxiv import ArxivCollector


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


def test_arxiv_collector_returns_raw_items():
    mock_result = _mock_arxiv_result()
    mock_client = MagicMock()
    mock_client.results.return_value = [mock_result]

    with patch("collectors.arxiv.arxiv.Client", return_value=mock_client), \
         patch("collectors.arxiv.arxiv.Search"), \
         patch("collectors.arxiv.fetch_citations") as mock_fetch:
        mock_fetch.return_value = {
            "2604.12345v1": {"citation_count": 15, "influential_citations": 3},
        }

        collector = ArxivCollector(categories=["cs.AI"])
        items = collector.collect()
        assert len(items) == 1
        assert items[0].source == "arxiv"
        assert items[0].metrics["citation_count"] == 15
        assert items[0].metrics["influential_citations"] == 3


def test_arxiv_collector_zero_citations_when_s2_missing_paper():
    """Papers S2 hasn't indexed yet return no row; collector defaults to 0."""
    mock_result = _mock_arxiv_result()
    mock_client = MagicMock()
    mock_client.results.return_value = [mock_result]

    with patch("collectors.arxiv.arxiv.Client", return_value=mock_client), \
         patch("collectors.arxiv.arxiv.Search"), \
         patch("collectors.arxiv.fetch_citations", return_value={}):
        items = ArxivCollector(categories=["cs.AI"]).collect()
        assert items[0].metrics["citation_count"] == 0
        assert items[0].metrics["influential_citations"] == 0


def test_arxiv_collector_single_batch_call_for_all_papers():
    """Regression: prior per-paper HTTP calls tripped S2 rate limits."""
    results = [_mock_arxiv_result() for _ in range(5)]
    for i, r in enumerate(results):
        r.entry_id = f"http://arxiv.org/abs/2604.{i:05d}v1"
    mock_client = MagicMock()
    mock_client.results.return_value = results

    with patch("collectors.arxiv.arxiv.Client", return_value=mock_client), \
         patch("collectors.arxiv.arxiv.Search"), \
         patch("collectors.arxiv.fetch_citations") as mock_fetch:
        mock_fetch.return_value = {}
        ArxivCollector(categories=["cs.AI"]).collect()
        assert mock_fetch.call_count == 1
        # Called with all 5 ids at once.
        args, _ = mock_fetch.call_args
        assert len(list(args[0])) == 5
