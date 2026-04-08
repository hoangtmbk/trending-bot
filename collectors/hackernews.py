from __future__ import annotations
import logging
import requests
from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)

AI_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "llm", "gpt", "claude", "gemini", "transformer", "neural network",
    "diffusion", "rag", "agent", "langchain", "hugging face", "openai",
    "anthropic", "fine-tuning", "embedding", "vector database",
    "computer vision", "nlp", "reinforcement learning",
]


class HackerNewsCollector(BaseCollector):
    source_name = "hackernews"
    BASE_URL = "https://hn.algolia.com/api/v1"

    def collect(self) -> list[RawItem]:
        items = []
        for query in ["AI", "LLM", "machine learning"]:
            url = f"{self.BASE_URL}/search_by_date"
            params = {
                "query": query,
                "tags": "story",
                "numericFilters": "points>10",
                "hitsPerPage": 50,
            }
            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                for hit in data.get("hits", []):
                    if not self._is_ai_relevant(hit):
                        continue
                    item = RawItem(
                        title=hit.get("title", ""),
                        url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
                        source=self.source_name,
                        description="",
                        metrics={
                            "points": hit.get("points", 0),
                            "num_comments": hit.get("num_comments", 0),
                            "objectID": hit.get("objectID", ""),
                        },
                        timestamp=hit.get("created_at", ""),
                    )
                    items.append(item)
            except requests.RequestException as e:
                logger.error(f"HN API error for query '{query}': {e}")

        seen = set()
        unique = []
        for item in items:
            oid = item.metrics.get("objectID", item.url)
            if oid not in seen:
                seen.add(oid)
                unique.append(item)

        logger.info(f"HN collector found {len(unique)} items")
        return unique

    def _is_ai_relevant(self, hit: dict) -> bool:
        title = (hit.get("title") or "").lower()
        return any(kw in title for kw in AI_KEYWORDS)
