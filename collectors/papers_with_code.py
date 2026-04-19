from __future__ import annotations
import logging
from datetime import datetime, timezone

import requests

from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)

PWC_LATEST_URL = "https://paperswithcode.com/api/v1/papers/"


class PapersWithCodeCollector(BaseCollector):
    """Papers With Code — AI papers with linked code implementations.

    The `latest=true` filter returns recent papers, sorted by recency.
    Each paper carries a github_stars count from its top implementation.
    """
    source_name = "papers_with_code"

    def collect(self) -> list[RawItem]:
        try:
            resp = requests.get(
                PWC_LATEST_URL,
                params={"items_per_page": 50},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Papers With Code fetch failed: {e}")
            return []

        results = data.get("results", []) if isinstance(data, dict) else data
        items: list[RawItem] = []
        for row in results:
            arxiv_id = row.get("arxiv_id") or ""
            pwc_id = row.get("id")
            title = row.get("title")
            if not title or not (arxiv_id or pwc_id):
                continue

            url = (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id
                   else f"https://paperswithcode.com/paper/{pwc_id}")
            published = row.get("published") or ""
            try:
                ts = datetime.fromisoformat(published.replace("Z", "+00:00")).isoformat() \
                    if published else datetime.now(timezone.utc).isoformat()
            except (ValueError, AttributeError):
                ts = datetime.now(timezone.utc).isoformat()

            items.append(RawItem(
                title=title,
                url=url,
                source=self.source_name,
                description=(row.get("abstract") or "")[:500],
                metrics={
                    "arxiv_id": arxiv_id,
                    "pwc_id": pwc_id,
                    "github_stars": row.get("github_stars", 0) or 0,
                    "methods": row.get("methods", [])[:5] if row.get("methods") else [],
                },
                timestamp=ts,
            ))

        logger.info(f"Papers With Code: {len(items)} items")
        return items
