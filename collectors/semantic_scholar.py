from __future__ import annotations
import logging
import time
from typing import Iterable

import requests

logger = logging.getLogger(__name__)

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
BATCH_SIZE = 100
FIELDS = "externalIds,citationCount,influentialCitationCount"


def fetch_citations(arxiv_ids: Iterable[str]) -> dict[str, dict[str, int]]:
    """Batch-lookup citation counts from Semantic Scholar.

    Returns {arxiv_id → {"citation_count": int, "influential_citations": int}}.
    Papers not (yet) indexed in S2 are omitted. Unauthenticated tier allows
    ~100 req / 5min; on 429 the request sleeps once and retries.

    Why: the old per-paper GET /paper/ARXIV:{id} pattern fired 100 requests
    per collection and tripped rate limits; citationCount came back null for
    papers S2 hasn't indexed yet. That null was then stored as-is, which the
    scorer then treated as 0 — every arxiv paper scored identically.
    """
    ids_list = list(arxiv_ids)
    if not ids_list:
        return {}

    out: dict[str, dict[str, int]] = {}
    for i in range(0, len(ids_list), BATCH_SIZE):
        chunk = ids_list[i : i + BATCH_SIZE]
        payload = {"ids": [f"ARXIV:{aid}" for aid in chunk]}
        try:
            resp = requests.post(
                S2_BATCH_URL,
                params={"fields": FIELDS},
                json=payload,
                timeout=15,
            )
            if resp.status_code == 429:
                logger.info("Semantic Scholar rate-limited, sleeping 5s")
                time.sleep(5)
                resp = requests.post(
                    S2_BATCH_URL,
                    params={"fields": FIELDS},
                    json=payload,
                    timeout=15,
                )
            if resp.status_code != 200:
                logger.warning(f"Semantic Scholar batch returned {resp.status_code}")
                continue
            for rec in resp.json():
                if not rec:
                    continue
                ext = rec.get("externalIds") or {}
                # S2 returns "ArXiv" (mixed case) in externalIds.
                arxiv_id = ext.get("ArXiv") or ext.get("ARXIV")
                if not arxiv_id:
                    continue
                out[arxiv_id] = {
                    "citation_count": rec.get("citationCount") or 0,
                    "influential_citations": rec.get("influentialCitationCount") or 0,
                }
        except Exception as e:
            logger.warning(f"Semantic Scholar batch lookup failed: {e}")
    return out
