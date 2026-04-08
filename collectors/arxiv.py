from __future__ import annotations
import logging
import arxiv
import requests
from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)

S2_API = "https://api.semanticscholar.org/graph/v1/paper"


class ArxivCollector(BaseCollector):
    source_name = "arxiv"

    def __init__(self, categories: list[str] | None = None):
        self.categories = categories or ["cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.MA", "stat.ML"]

    def collect(self) -> list[RawItem]:
        items = []
        query = " OR ".join(f"cat:{cat}" for cat in self.categories)
        search = arxiv.Search(
            query=query,
            max_results=100,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        client = arxiv.Client()

        try:
            for result in client.results(search):
                arxiv_id = result.entry_id.split("/abs/")[-1]
                citation_data = self._get_citations(arxiv_id)
                item = RawItem(
                    title=result.title,
                    url=result.entry_id,
                    source=self.source_name,
                    description=result.summary[:500],
                    metrics={
                        "arxiv_id": arxiv_id,
                        "citation_count": citation_data.get("citationCount", 0),
                        "influential_citations": citation_data.get("influentialCitationCount", 0),
                        "categories": result.categories,
                        "pdf_url": result.pdf_url,
                    },
                    timestamp=result.published.isoformat(),
                )
                items.append(item)
        except Exception as e:
            logger.error(f"arXiv API error: {e}")

        logger.info(f"arXiv collector found {len(items)} papers")
        return items

    def _get_citations(self, arxiv_id: str) -> dict:
        try:
            url = f"{S2_API}/ARXIV:{arxiv_id}"
            params = {"fields": "citationCount,influentialCitationCount"}
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"Semantic Scholar lookup failed for {arxiv_id}: {e}")
        return {"citationCount": 0, "influentialCitationCount": 0}
