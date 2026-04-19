"""Tests for the generic RSSCollector — powers blog, newsletter, Lobsters scouts."""
from unittest.mock import patch, MagicMock

from collectors.rss import RSSCollector


def _fake_entry(title="A post", link="https://example.com/post", summary="summary",
                author="Alice", published_parsed=(2026, 4, 19, 10, 0, 0, 0, 0, 0),
                tags=None):
    e = {
        "title": title,
        "link": link,
        "summary": summary,
        "author": author,
        "published_parsed": published_parsed,
    }
    if tags is not None:
        e["tags"] = tags
    return e


def _fake_parsed(entries, bozo=False, bozo_exception=""):
    parsed = MagicMock()
    parsed.entries = entries
    parsed.bozo = bozo
    parsed.bozo_exception = bozo_exception
    return parsed


def test_parses_entries_into_raw_items():
    entries = [
        _fake_entry(title="First", link="https://blog.example/one"),
        _fake_entry(title="Second", link="https://blog.example/two"),
    ]
    with patch("collectors.rss.feedparser.parse",
               return_value=_fake_parsed(entries)):
        items = RSSCollector(feed_url="https://blog.example/rss",
                             source_name="blog_example").collect()
    assert len(items) == 2
    assert items[0].source == "blog_example"
    assert items[0].url == "https://blog.example/one"
    assert items[0].title == "First"
    assert items[0].metrics["feed_url"] == "https://blog.example/rss"
    assert items[0].metrics["author"] == "Alice"


def test_skips_entries_missing_url_or_title():
    entries = [
        _fake_entry(title="", link="https://blog.example/one"),
        _fake_entry(title="OK", link=""),
        _fake_entry(title="Good", link="https://blog.example/ok"),
    ]
    with patch("collectors.rss.feedparser.parse",
               return_value=_fake_parsed(entries)):
        items = RSSCollector(feed_url="https://blog.example/rss",
                             source_name="x").collect()
    assert len(items) == 1
    assert items[0].title == "Good"


def test_truncates_description():
    long = "x" * 1000
    entries = [_fake_entry(summary=long)]
    with patch("collectors.rss.feedparser.parse",
               return_value=_fake_parsed(entries)):
        items = RSSCollector(feed_url="u", source_name="s").collect()
    assert len(items[0].description) == 500


def test_max_items_caps_output():
    entries = [_fake_entry(title=f"T{i}", link=f"u{i}") for i in range(100)]
    with patch("collectors.rss.feedparser.parse",
               return_value=_fake_parsed(entries)):
        items = RSSCollector(feed_url="u", source_name="s", max_items=10).collect()
    assert len(items) == 10


def test_bozo_feed_with_no_entries_returns_empty():
    with patch("collectors.rss.feedparser.parse",
               return_value=_fake_parsed([], bozo=True, bozo_exception="bad xml")):
        items = RSSCollector(feed_url="u", source_name="s").collect()
    assert items == []


def test_bozo_feed_with_entries_still_returns_them():
    """Many real feeds are technically invalid but parse fine (e.g. newsletters
    with invalid HTML in content). Don't drop usable data."""
    entries = [_fake_entry()]
    with patch("collectors.rss.feedparser.parse",
               return_value=_fake_parsed(entries, bozo=True, bozo_exception="tolerable")):
        items = RSSCollector(feed_url="u", source_name="s").collect()
    assert len(items) == 1


def test_network_error_returns_empty():
    with patch("collectors.rss.feedparser.parse",
               side_effect=Exception("DNS failure")):
        items = RSSCollector(feed_url="u", source_name="s").collect()
    assert items == []


def test_tags_extracted():
    entries = [_fake_entry(tags=[{"term": "ai"}, {"term": "research"}])]
    with patch("collectors.rss.feedparser.parse",
               return_value=_fake_parsed(entries)):
        items = RSSCollector(feed_url="u", source_name="s").collect()
    assert items[0].metrics["tags"] == ["ai", "research"]
