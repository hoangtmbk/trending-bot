from __future__ import annotations
import logging
from collections import defaultdict
from pathlib import Path
from models import ScoredItem, AnalysisReport

logger = logging.getLogger(__name__)

SOURCE_BADGES = {
    "github": "⭐", "reddit": "💬", "arxiv": "📄",
    "huggingface": "🤗", "twitter": "𝕏", "hackernews": "🔶",
}


def build_digest(
    items: list[ScoredItem],
    reports: list[AnalysisReport],
    data_dir: Path,
    date_str: str,
) -> Path:
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_slugs = {r.slug for r in reports}

    by_category: dict[str, list[ScoredItem]] = defaultdict(list)
    for item in items:
        cat = item.category or "other"
        by_category[cat].append(item)

    lines = [
        f"# AI Trending Daily — {date_str}",
        "",
        f"**{len(items)} items** across {len(set(s for i in items for s in i.sources))} sources"
        f" · **{len(reports)} deep dives**",
        "",
        "---",
        "",
    ]

    for category, cat_items in sorted(by_category.items(), key=lambda x: -max(i.interest_score for i in x[1])):
        lines.append(f"## {category.title()}")
        lines.append("")
        for item in sorted(cat_items, key=lambda x: -x.interest_score):
            badges = " ".join(SOURCE_BADGES.get(s, "") for s in item.sources)
            lines.append(
                f"- **[{item.title}]({item.url})** "
                f"(score: {item.interest_score}/10) {badges}"
            )
            if item.llm_summary:
                lines.append(f"  {item.llm_summary}")
            lines.append("")
        lines.append("")

    digest_path = reports_dir / "digest.md"
    digest_path.write_text("\n".join(lines))
    logger.info(f"Digest written to {digest_path}")
    return digest_path
