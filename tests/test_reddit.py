import json
from unittest.mock import patch, MagicMock
from collectors.reddit import RedditCollector
from models import RawItem


def _mock_submission():
    sub = MagicMock()
    sub.title = "GPT-5 leaked benchmarks discussion"
    sub.url = "https://reddit.com/r/MachineLearning/comments/abc123"
    sub.permalink = "/r/MachineLearning/comments/abc123/gpt5_leaked/"
    sub.selftext = "Interesting results showing..."
    sub.score = 500
    sub.upvote_ratio = 0.95
    sub.num_comments = 200
    sub.total_awards_received = 3
    sub.created_utc = 1744070400.0
    sub.num_crossposts = 2
    return sub


def test_reddit_collector_returns_raw_items():
    mock_sub = _mock_submission()
    mock_subreddit = MagicMock()
    mock_subreddit.hot.return_value = [mock_sub]
    mock_reddit = MagicMock()
    mock_reddit.subreddit.return_value = mock_subreddit

    with patch("collectors.reddit.praw.Reddit", return_value=mock_reddit):
        collector = RedditCollector(
            client_id="fake", client_secret="fake",
            user_agent="test", subreddits=["MachineLearning"],
        )
        items = collector.collect()
        assert len(items) >= 1
        assert items[0].source == "reddit"
        assert "score" in items[0].metrics


def test_reddit_collector_saves_to_file(tmp_data_dir):
    mock_sub = _mock_submission()
    mock_subreddit = MagicMock()
    mock_subreddit.hot.return_value = [mock_sub]
    mock_reddit = MagicMock()
    mock_reddit.subreddit.return_value = mock_subreddit

    with patch("collectors.reddit.praw.Reddit", return_value=mock_reddit):
        collector = RedditCollector(
            client_id="fake", client_secret="fake",
            user_agent="test", subreddits=["MachineLearning"],
        )
        collector.run(tmp_data_dir)
        assert (tmp_data_dir / "raw" / "reddit.json").exists()
