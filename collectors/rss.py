from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any

import feedparser

from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)


def _to_iso(entry_time: Any) -> str:
    """feedparser's time_struct → ISO string. Fall back to 'now' if unparseable."""
    if entry_time and hasattr(entry_time, "tm_year"):
        try:
            return datetime(*entry_time[:6], tzinfo=timezone.utc).isoformat()
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc).isoformat()


class RSSCollector(BaseCollector):
    """Generic RSS/Atom collector — one instance per feed URL.

    Why shared: blog scouts, newsletter scouts, Lobsters, and HF Daily Papers
    (when available as RSS) all speak the same protocol. Keeping one collector
    means new sources are a config entry, not a new Python file.
    """

    def __init__(self, *, feed_url: str, source_name: str, max_items: int = 50):
        self.feed_url = feed_url
        self.source_name = source_name
        self.max_items = max_items

    def collect(self) -> list[RawItem]:
        try:
            parsed = feedparser.parse(self.feed_url)
        except Exception as e:
            logger.error(f"RSS fetch failed for {self.feed_url}: {e}")
            return []

        if parsed.bozo and not parsed.entries:
            logger.warning(f"RSS feed malformed at {self.feed_url}: {parsed.bozo_exception}")
            return []

        items: list[RawItem] = []
        for entry in parsed.entries[: self.max_items]:
            url = entry.get("link") or entry.get("id")
            title = entry.get("title")
            if not url or not title:
                continue

            description = (entry.get("summary") or entry.get("description") or "")[:500]
            ts = _to_iso(entry.get("published_parsed") or entry.get("updated_parsed"))

            items.append(RawItem(
                title=title,
                url=url,
                source=self.source_name,
                description=description,
                metrics={
                    "feed_url": self.feed_url,
                    "author": entry.get("author", ""),
                    "tags": [t.get("term", "") for t in entry.get("tags", [])] if entry.get("tags") else [],
                },
                timestamp=ts,
            ))

        logger.info(f"RSS {self.source_name}: {len(items)} items from {self.feed_url}")
        return items
