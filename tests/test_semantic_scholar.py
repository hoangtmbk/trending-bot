"""Tests for collectors.semantic_scholar.fetch_citations — the batch
citation lookup that replaces the old per-paper GET."""
from unittest.mock import patch, MagicMock

from collectors.semantic_scholar import fetch_citations


def _resp(status=200, payload=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload or []
    return r


def test_batch_maps_arxiv_id_to_citation_counts():
    payload = [
        {
            "externalIds": {"ArXiv": "2604.00001"},
            "citationCount": 42,
            "influentialCitationCount": 5,
        },
        {
            "externalIds": {"ArXiv": "2604.00002"},
            "citationCount": 0,
            "influentialCitationCount": 0,
        },
    ]
    with patch("collectors.semantic_scholar.requests.post",
               return_value=_resp(200, payload)) as mock_post:
        result = fetch_citations(["2604.00001", "2604.00002"])
    assert mock_post.call_count == 1
    assert result["2604.00001"]["citation_count"] == 42
    assert result["2604.00001"]["influential_citations"] == 5
    assert result["2604.00002"]["citation_count"] == 0


def test_empty_input_no_request():
    with patch("collectors.semantic_scholar.requests.post") as mock_post:
        assert fetch_citations([]) == {}
        mock_post.assert_not_called()


def test_null_counts_coerced_to_zero():
    """S2 returns null (not 0) for papers it hasn't scored yet. Old code stored
    that null, which then poisoned every downstream comparison."""
    payload = [
        {"externalIds": {"ArXiv": "2604.00009"},
         "citationCount": None, "influentialCitationCount": None},
    ]
    with patch("collectors.semantic_scholar.requests.post",
               return_value=_resp(200, payload)):
        result = fetch_citations(["2604.00009"])
    assert result["2604.00009"] == {"citation_count": 0, "influential_citations": 0}


def test_omits_papers_not_in_s2():
    """S2 returns null entries for IDs it doesn't know. Those should not appear
    in the result dict — caller defaults to 0 via .get()."""
    payload = [
        {"externalIds": {"ArXiv": "2604.00001"},
         "citationCount": 1, "influentialCitationCount": 0},
        None,  # unknown paper
    ]
    with patch("collectors.semantic_scholar.requests.post",
               return_value=_resp(200, payload)):
        result = fetch_citations(["2604.00001", "2604.unknown"])
    assert "2604.00001" in result
    assert "2604.unknown" not in result


def test_non_200_skips_chunk_without_raising():
    with patch("collectors.semantic_scholar.requests.post",
               return_value=_resp(500, [])):
        result = fetch_citations(["2604.00001"])
    assert result == {}


def test_429_retries_once():
    """Rate-limited: sleep and retry once."""
    call = {"n": 0}

    def side_effect(*a, **kw):
        call["n"] += 1
        if call["n"] == 1:
            return _resp(429, [])
        return _resp(200, [{
            "externalIds": {"ArXiv": "2604.00001"},
            "citationCount": 7, "influentialCitationCount": 2,
        }])

    with patch("collectors.semantic_scholar.requests.post", side_effect=side_effect), \
         patch("collectors.semantic_scholar.time.sleep"):
        result = fetch_citations(["2604.00001"])
    assert call["n"] == 2
    assert result["2604.00001"]["citation_count"] == 7


def test_request_exception_returns_partial():
    """Network error on a batch is logged and skipped — other batches still land."""
    with patch("collectors.semantic_scholar.requests.post",
               side_effect=Exception("boom")):
        result = fetch_citations(["2604.00001"])
    assert result == {}
