from __future__ import annotations
import json
import logging
from pathlib import Path
from models import ScoredItem
from claude_cli import call_claude_json

logger = logging.getLogger(__name__)


def run_llm_filter(
    items: list[ScoredItem],
    digest_size: int = 15,
    deep_dive_count: int = 5,
) -> tuple[list[ScoredItem], list[ScoredItem]]:
    try:
        return _run_filter(items, digest_size, deep_dive_count)
    except Exception as e:
        logger.error(f"LLM filter failed, falling back to score-based ranking: {e}")
        return _fallback(items, digest_size, deep_dive_count)


def _run_filter(
    items: list[ScoredItem],
    digest_size: int,
    deep_dive_count: int,
) -> tuple[list[ScoredItem], list[ScoredItem]]:
    items_for_prompt = []
    for i, item in enumerate(items):
        items_for_prompt.append({
            "index": i,
            "title": item.title,
            "url": item.url,
            "description": item.description,
            "sources": item.sources,
            "momentum_score": item.momentum_score,
        })

    prompt_template = (Path(__file__).parent.parent / "prompts" / "filter.md").read_text()
    prompt = prompt_template.replace("{items_json}", json.dumps(items_for_prompt, indent=2))

    result = call_claude_json(prompt)

    digest = []
    deep_dives = []

    for eval_item in result.get("items", []):
        idx = eval_item["index"]
        if idx >= len(items):
            continue

        scored = items[idx]
        if not eval_item.get("novel", False) or not eval_item.get("ai_relevant", False):
            continue

        scored.category = eval_item.get("category", "")
        scored.interest_score = eval_item.get("interest_score", 0)
        scored.llm_summary = eval_item.get("summary", "")
        digest.append(scored)

        if eval_item.get("deep_dive", False):
            deep_dives.append(scored)

    digest.sort(key=lambda x: x.interest_score, reverse=True)
    digest = digest[:digest_size]
    deep_dives = deep_dives[:deep_dive_count]

    return digest, deep_dives


def _fallback(
    items: list[ScoredItem],
    digest_size: int,
    deep_dive_count: int,
) -> tuple[list[ScoredItem], list[ScoredItem]]:
    sorted_items = sorted(items, key=lambda x: x.final_score, reverse=True)
    digest = sorted_items[:digest_size]
    deep_dives = sorted_items[:deep_dive_count]
    for item in digest:
        item.interest_score = -1
        item.llm_summary = "[LLM filter unavailable — ranked by raw momentum]"
    return digest, deep_dives
