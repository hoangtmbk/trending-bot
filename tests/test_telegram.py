from unittest.mock import patch, MagicMock
from models import RawItem, ScoredItem, AnalysisReport
from delivery.telegram import format_telegram_message, send_telegram_message


def _scored(title, score, category, sources, summary):
    raw = RawItem(title=title, url=f"http://example.com/{title}", source=sources[0],
                  description="", metrics={}, timestamp="2026-04-08T00:00:00Z")
    return ScoredItem(raw_items=[raw], momentum_score=score, final_score=score,
                      sources=sources, category=category, llm_summary=summary,
                      interest_score=int(score * 10))


def test_format_telegram_message():
    items = [
        _scored("AgentKit", 0.9, "tool", ["github", "reddit"], "Agent framework"),
        _scored("ScalingPaper", 0.7, "paper", ["arxiv"], "Scaling paper"),
    ]
    reports = [AnalysisReport(
        slug="agentkit", title="AgentKit", what_it_is="framework",
        why_trending="viral", pain_point="complexity", gap_analysis="gaps",
        competitors=[], app_idea="Visual builder", feasibility={},
    )]
    msg = format_telegram_message(items, reports, "2026-04-08")
    assert "2026-04-08" in msg
    assert "AgentKit" in msg
    assert "Visual builder" in msg


def test_send_telegram_message():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True}
    with patch("delivery.telegram.requests.post", return_value=mock_resp) as mock_post:
        send_telegram_message("Test message", bot_token="fake", chat_id="123")
        mock_post.assert_called_once()
