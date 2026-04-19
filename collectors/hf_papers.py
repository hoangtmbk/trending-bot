from __future__ import annotations
import logging
from datetime import datetime, timezone

import requests

from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)

HF_DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"


class HuggingFacePapersCollector(BaseCollector):
    """HuggingFace Daily Papers — curated daily AI paper list with community upvotes.

    Each entry is already an arXiv paper, so items land with url pointing to
    arxiv (enabling dedup with the arxiv scout) and `arxiv_id` in metrics.
    """
    source_name = "hf_papers"

    def collect(self) -> list[RawItem]:
        try:
            resp = requests.get(HF_DAILY_PAPERS_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"HF Daily Papers fetch failed: {e}")
            return []

        items: list[RawItem] = []
        for row in data:
            paper = row.get("paper") or {}
            arxiv_id = paper.get("id")
            title = paper.get("title")
            if not arxiv_id or not title:
                continue

            published = row.get("publishedAt") or paper.get("publishedAt")
            try:
                ts = datetime.fromisoformat(published.replace("Z", "+00:00")).isoformat() \
                    if published else datetime.now(timezone.utc).isoformat()
            except (ValueError, AttributeError):
                ts = datetime.now(timezone.utc).isoformat()

            items.append(RawItem(
                title=title,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                source=self.source_name,
                description=(paper.get("summary") or "")[:500],
                metrics={
                    "arxiv_id": arxiv_id,
                    "upvotes": paper.get("upvotes", 0),
                    "hf_published_at": published or "",
                },
                timestamp=ts,
            ))

        logger.info(f"HF Daily Papers: {len(items)} items")
        return items
