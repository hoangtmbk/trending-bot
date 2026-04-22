"""Markdown export for dashboard items.

Pure formatter — no DB access, no HTTP. The web routes pass in dicts
already loaded from the DB and we return strings.
"""
from __future__ import annotations

import re

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


from datetime import datetime, timezone
from typing import Any


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
    """Return the most recent filter analysis content dict (already JSON-parsed)."""
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

    `heading_offset` shifts every heading down by N levels (used by bulk export
    so the per-item H1 becomes H2 under the document's top-level H1).
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
        lines.append(f"{h2} Analysis — {atype}")
        for key, value in content.items():
            rendered = _stringify_value(value)
            if rendered == "":
                continue
            lines.append(f"{_format_field_label(key)}: {rendered}")
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
