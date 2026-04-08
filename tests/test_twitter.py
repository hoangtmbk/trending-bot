from unittest.mock import patch
from collectors.twitter import TwitterCollector
from models import RawItem


def test_twitter_collector_returns_raw_items():
    mock_items = [
        RawItem(
            title="@karpathy: New breakthrough in test-time compute scaling",
            url="https://x.com/karpathy/status/123456",
            source="twitter",
            description="Thread about scaling inference...",
            metrics={"likes": 5000, "retweets": 1200, "quotes": 300, "replies": 150},
            timestamp="2026-04-08T00:00:00Z",
        )
    ]
    with patch.object(TwitterCollector, "_scrape_tweets", return_value=mock_items):
        collector = TwitterCollector(fallback_to_rss=True)
        items = collector.collect()
        assert len(items) >= 1
        assert items[0].source == "twitter"


def test_twitter_collector_falls_back_to_empty_on_error():
    with patch.object(TwitterCollector, "_scrape_tweets", side_effect=Exception("Scraping failed")):
        collector = TwitterCollector(fallback_to_rss=True)
        items = collector.collect()
        assert isinstance(items, list)
