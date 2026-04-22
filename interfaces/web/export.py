"""Markdown export for dashboard items.

Pure formatter — no DB access, no HTTP. The web routes pass in dicts
already loaded from the DB and we return strings.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 50) -> str:
    """Lowercase, collapse non-alphanumerics into single dashes, trim, truncate.

    Used for export filenames. Non-ASCII chars are treated as non-alphanumeric
    (no transliteration). Empty input returns empty string — callers should
    fall back to an id-based filename.
    """
    s = _NON_ALNUM.sub("-", text.lower()).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s


def _stringify_value(value: Any) -> str:
    """Render an analysis-content value for inline display."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        # Pretty-print as inline sub-bullets so nested dicts stay readable.
        parts = [f"{k}: {_stringify_value(v)}" for k, v in value.items()]
        return "; ".join(parts)
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _format_field_label(key: str) -> str:
    """snake_case → Title Case for analysis content keys."""
    return key.replace("_", " ").title()


def _extract_filter_content(analyses: list[dict]) -> dict | None:
    """Return the first filter analysis content dict in the list, or None.

    Callers should pass `analyses` ordered newest-first if they want the most
    recent filter analysis (this matches how the route layer queries it).
    """
    for a in analyses:
        if a.get("analysis_type") == "filter":
            return a.get("content") or {}
    return None


def _format_iso_date(iso: str | None, length: int = 10) -> str:
    """Trim an ISO timestamp to YYYY-MM-DD (length=10) or YYYY-MM-DDTHH:MM (length=16)."""
    if not iso:
        return ""
    return iso[:length]


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def render_item_markdown(
    item: dict,
    analyses: list[dict],
    scores: list[dict],
    heading_offset: int = 0,
) -> str:
    """Render one item as markdown.

    `heading_offset` shifts every heading down by N levels. The bulk exporter
    passes `heading_offset=2` so the per-item H1 becomes H3 under the document
    H1 (export header) and category H2.
    """
    h1 = "#" * (1 + heading_offset)
    h2 = "#" * (2 + heading_offset)

    filter_content = _extract_filter_content(analyses) or {}
    interest_score = filter_content.get("interest_score")
    summary = filter_content.get("summary")
    category = filter_content.get("category")

    lines: list[str] = []

    # Heading
    lines.append(f"{h1} {item['title']}")
    lines.append("")

    # Metadata block
    meta_parts = [f"**Source:** {item['source']}"]
    if interest_score is not None:
        meta_parts.append(f"**Score:** {interest_score}/10")
    if item.get("normalized_score") is not None:
        meta_parts.append(f"**Rank:** {int(item['normalized_score'])}")
    lines.append(" · ".join(meta_parts))

    seen_parts = []
    if item.get("first_seen"):
        seen_parts.append(f"**First seen:** {_format_iso_date(item['first_seen'])}")
    if item.get("times_seen") is not None:
        seen_parts.append(f"**Times seen:** {item['times_seen']}")
    if seen_parts:
        lines.append(" · ".join(seen_parts))

    if item.get("url"):
        lines.append(f"**URL:** {item['url']}")
    if category:
        lines.append(f"**Category:** {category}")
    lines.append("")

    # Summary (from filter analysis)
    if summary:
        lines.append(f"{h2} Summary")
        lines.append(summary)
        lines.append("")

    # Description (raw item field)
    if item.get("description"):
        lines.append(f"{h2} Description")
        lines.append(item["description"])
        lines.append("")

    # Other analyses (skip filter — already consumed above)
    for a in analyses:
        if a.get("analysis_type") == "filter":
            continue
        atype = a.get("analysis_type", "analysis")
        content = a.get("content") or {}
        content_lines = []
        for key, value in content.items():
            rendered = _stringify_value(value)
            if rendered == "":
                continue
            content_lines.append(f"{_format_field_label(key)}: {rendered}")
        if not content_lines:
            continue
        lines.append(f"{h2} Analysis — {atype}")
        lines.extend(content_lines)
        lines.append("")

    # Score history
    if scores:
        lines.append(f"{h2} Score history")
        for s in scores:
            ts = _format_iso_date(s.get("recorded_at"), length=16)
            mom = s.get("momentum_score") or 0.0
            norm = s.get("normalized_score") or 0.0
            lines.append(f"- {ts} — momentum {mom:.2f} · normalized {int(norm)}")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Exported from TrendBot on {_now_utc_str()}*")
    lines.append("")

    return "\n".join(lines)


def render_bulk_markdown(
    items_with_data: list[tuple[dict, list[dict], list[dict]]],
) -> str:
    """Render multiple items as one combined markdown document.

    Items are grouped by category (from each item's filter analysis, falling
    back to "other"). Categories are sorted by max interest_score in the group;
    items within a category are sorted by interest_score desc.

    Per-item rendering uses heading_offset=2 so the document has a single H1
    (the export header), categories are H2, and per-item titles are H3.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not items_with_data:
        return (
            f"# TrendBot export — {today}\n"
            f"\n"
            f"**0 items**, exported on {_now_utc_str()}\n"
            f"\n"
            f"(no items)\n"
        )

    # Bucket items by category, tracking each item's interest_score for sorting.
    by_category: dict[str, list[tuple[int, tuple[dict, list[dict], list[dict]]]]] = defaultdict(list)
    sources: set[str] = set()

    for triple in items_with_data:
        item, analyses, _ = triple
        filter_content = _extract_filter_content(analyses) or {}
        category = filter_content.get("category") or "other"
        score = filter_content.get("interest_score") or 0
        by_category[category].append((score, triple))
        if item.get("source"):
            sources.add(item["source"])

    # Sort categories by max score within group (desc).
    cat_max = {cat: max(s for s, _ in items) for cat, items in by_category.items()}
    sorted_categories = sorted(by_category.keys(), key=lambda c: -cat_max[c])

    lines: list[str] = []
    lines.append(f"# TrendBot export — {today}")
    lines.append("")
    lines.append(
        f"**{len(items_with_data)} items** across {len(sources)} sources, "
        f"exported on {_now_utc_str()}"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    for category in sorted_categories:
        lines.append(f"## {category}")
        lines.append("")
        # Items sorted by score desc within the bucket.
        for _, (item, analyses, scores) in sorted(
            by_category[category], key=lambda pair: -pair[0]
        ):
            # heading_offset=2 → per-item H1 becomes H3, H2 becomes H4.
            lines.append(render_item_markdown(item, analyses, scores, heading_offset=2))

    return "\n".join(lines)
