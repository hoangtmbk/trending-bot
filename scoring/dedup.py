from __future__ import annotations
import logging
from urllib.parse import urlparse
from thefuzz import fuzz
from models import RawItem

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 75


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")
    path = parsed.path.rstrip("/")
    return f"{host}{path}".lower()


def _titles_match(a: str, b: str) -> bool:
    return fuzz.token_sort_ratio(a.lower(), b.lower()) >= FUZZY_THRESHOLD


def deduplicate(items: list[RawItem]) -> list[list[RawItem]]:
    groups: list[list[RawItem]] = []

    for item in items:
        merged = False
        item_url = _normalize_url(item.url)

        for group in groups:
            for existing in group:
                existing_url = _normalize_url(existing.url)
                if item_url == existing_url or _titles_match(item.title, existing.title):
                    group.append(item)
                    merged = True
                    break
            if merged:
                break

        if not merged:
            groups.append([item])

    logger.info(f"Dedup: {len(items)} items -> {len(groups)} groups")
    return groups
