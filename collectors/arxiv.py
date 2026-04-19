from __future__ import annotations
import logging
import arxiv
from collectors.base import BaseCollector
from collectors.semantic_scholar import fetch_citations
from models import RawItem

logger = logging.getLogger(__name__)


class ArxivCollector(BaseCollector):
    source_name = "arxiv"

    def __init__(self, categories: list[str] | None = None):
        self.categories = categories or ["cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.MA", "stat.ML"]

    def collect(self) -> list[RawItem]:
        items: list[RawItem] = []
        query = " OR ".join(f"cat:{cat}" for cat in self.categories)
        search = arxiv.Search(
            query=query,
            max_results=100,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        client = arxiv.Client()

        try:
            results = list(client.results(search))
        except Exception as e:
            logger.error(f"arXiv API error: {e}")
            return []

        # One batched Semantic Scholar lookup for all papers in this run —
        # cuts 100 sequential HTTP calls down to one.
        arxiv_ids = [r.entry_id.split("/abs/")[-1] for r in results]
        citations = fetch_citations(arxiv_ids)

        for result, arxiv_id in zip(results, arxiv_ids):
            cit = citations.get(arxiv_id, {})
            items.append(RawItem(
                title=result.title,
                url=result.entry_id,
                source=self.source_name,
                description=result.summary[:500],
                metrics={
                    "arxiv_id": arxiv_id,
                    "citation_count": cit.get("citation_count", 0),
                    "influential_citations": cit.get("influential_citations", 0),
                    "categories": result.categories,
                    "pdf_url": result.pdf_url,
                },
                timestamp=result.published.isoformat(),
            ))

        logger.info(f"arXiv collector found {len(items)} papers, "
                    f"{sum(1 for i in items if i.metrics['citation_count'] > 0)} with citations")
        return items
