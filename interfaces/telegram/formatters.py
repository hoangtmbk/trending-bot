from __future__ import annotations
import json


SOURCE_ICONS = {
    "github": "\u2b50", "reddit": "\ud83d\udcac", "arxiv": "\ud83d\udcc4",
    "huggingface": "\ud83e\udd17", "twitter": "\ud835\udd4f", "hackernews": "\ud83d\udd36",
}


def format_item(item: dict, include_actions: bool = True) -> str:
    """Format a single item for Telegram display."""
    source = item.get("source", "unknown")
    icon = SOURCE_ICONS.get(source, "\u2022")
    title = item.get("title", "Untitled")[:100]
    url = item.get("url", "")
    score = item.get("normalized_score", 0)
    times_seen = item.get("times_seen", 1)

    lines = [f"{icon} <b>{_escape_html(title)}</b>"]
    if url:
        lines.append(f"\ud83d\udd17 {url}")
    lines.append(f"\ud83d\udcca Score: {score:.0f} | Seen: {times_seen}x | Source: {source}")

    return "\n".join(lines)


def format_digest(items: list[dict], title: str = "Trending") -> str:
    """Format a list of items as a digest message."""
    if not items:
        return "No trending items found."

    lines = [f"\ud83d\udd25 <b>{_escape_html(title)}</b>", f"{len(items)} items", ""]
    for i, item in enumerate(items[:15], 1):
        source = item.get("source", "unknown")
        icon = SOURCE_ICONS.get(source, "\u2022")
        item_title = item.get("title", "Untitled")[:80]
        score = item.get("normalized_score", 0)
        lines.append(f"{i}. {icon} {_escape_html(item_title)} ({score:.0f})")

    return "\n".join(lines)


def format_deep_dive(analysis: dict) -> str:
    """Format an analysis report for Telegram."""
    content = json.loads(analysis["content"]) if isinstance(analysis["content"], str) else analysis["content"]

    lines = [
        f"\ud83d\udd2c <b>Deep Dive</b>",
        "",
        f"<b>What:</b> {_escape_html(str(content.get('what_it_is', 'N/A'))[:300])}",
        "",
        f"<b>Why trending:</b> {_escape_html(str(content.get('why_trending', 'N/A'))[:300])}",
        "",
        f"<b>Pain point:</b> {_escape_html(str(content.get('pain_point', 'N/A'))[:300])}",
        "",
        f"<b>Opportunity:</b> {_escape_html(str(content.get('app_idea', 'N/A'))[:300])}",
    ]

    competitors = content.get("competitors", [])
    if competitors:
        lines.append(f"\n<b>Competitors:</b> {_escape_html(', '.join(str(c) for c in competitors[:5]))}")

    return "\n".join(lines)


def format_topics(topics: list[dict]) -> str:
    """Format topic list for Telegram."""
    if not topics:
        return "No active topics."

    lines = ["\ud83d\udccb <b>Your Topics</b>", ""]
    for t in topics:
        weight = t.get("weight", 1.0)
        indicator = "\ud83d\udd34" if weight >= 2.0 else "\ud83d\udfe1" if weight >= 1.0 else "\u26aa"
        lines.append(f"{indicator} {_escape_html(t['name'])} (weight: {weight:.1f})")

    return "\n".join(lines)


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
