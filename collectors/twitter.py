from __future__ import annotations
import logging
from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)


class TwitterCollector(BaseCollector):
    source_name = "twitter"

    def __init__(self, fallback_to_rss: bool = True):
        self.fallback_to_rss = fallback_to_rss

    def collect(self) -> list[RawItem]:
        try:
            return self._scrape_tweets()
        except Exception as e:
            logger.error(f"Twitter scraping failed: {e}")
            if self.fallback_to_rss:
                logger.info("Falling back to RSS aggregators")
                return self._collect_from_rss()
            return []

    def _scrape_tweets(self) -> list[RawItem]:
        """Scrape AI-related tweets using playwright.

        Stub — Twitter/X scraping is the most fragile collector and is
        designed to be gracefully skippable per the spec.
        """
        logger.warning("Twitter scraping not yet implemented, returning empty list")
        return []

    def _collect_from_rss(self) -> list[RawItem]:
        """Fallback: collect from RSS aggregators that track AI Twitter."""
        logger.warning("RSS fallback not yet implemented")
        return []
