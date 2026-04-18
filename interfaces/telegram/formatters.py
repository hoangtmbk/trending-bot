from __future__ import annotations
import json


SOURCE_ICONS = {
    "github": "\u2b50", "reddit": "\U0001F4AC", "arxiv": "\U0001F4C4",
    "huggingface": "\U0001F917", "twitter": "\U0001D54F", "hackernews": "\U0001F536",
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
        lines.append(f"\U0001F517 {url}")
    lines.append(f"\U0001F4CA Score: {score:.0f} | Seen: {times_seen}x | Source: {source}")

    return "\n".join(lines)


def format_digest(
    items: list[dict],
    title: str = "Trending",
    summaries: dict[int, str] | None = None,
) -> str:
    """Format a list of items as a digest message.

    Each item renders as a clickable title on line 1 and a source/score footer
    on line 2; the raw URL is also exposed so it can be copied for verification.
    If a summary is available for an item (via the filter analysis), it is
    appended on a third italic line.
    """
    if not items:
        return "No trending items found."

    summaries = summaries or {}

    lines = [f"\U0001F525 <b>{_escape_html(title)}</b>", f"{len(items)} items", ""]
    for i, item in enumerate(items[:15], 1):
        source = item.get("source", "unknown")
        icon = SOURCE_ICONS.get(source, "\u2022")
        item_title = item.get("title", "Untitled")[:80]
        url = item.get("url", "")
        score = item.get("normalized_score", 0)
        if url:
            safe_url = _escape_html(url)
            lines.append(f"{i}. {icon} <a href=\"{safe_url}\">{_escape_html(item_title)}</a>")
            lines.append(f"   <i>{source}</i> \u00b7 score {score:.0f} \u00b7 {safe_url}")
        else:
            lines.append(f"{i}. {icon} {_escape_html(item_title)}")
            lines.append(f"   <i>{source}</i> \u00b7 score {score:.0f}")

        summary = summaries.get(item.get("id"))
        if summary:
            truncated = _truncate(summary, 140)
            lines.append(f"   \U0001F4A1 <i>{_escape_html(truncated)}</i>")

    return "\n".join(lines)


def _truncate(text: str, limit: int) -> str:
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\u2026"


def format_deep_dive(analysis: dict) -> str:
    """Format an analysis report for Telegram."""
    content = json.loads(analysis["content"]) if isinstance(analysis["content"], str) else analysis["content"]

    lines = [
        f"\U0001F52C <b>Deep Dive</b>",
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


def format_deep_dives_followup(
    items: list[dict],
    deep_dives: dict[int, dict],
) -> str | None:
    """Compact combined message for items that have a deep_dive analysis.

    `items` is the enumerated digest list (same order). `#N` in each block
    matches the 1-based position in the digest so the user can cross-reference.
    Returns None when no item in the digest has a renderable deep-dive.
    """
    blocks: list[str] = []
    for i, item in enumerate(items[:15], 1):
        dd = deep_dives.get(item.get("id"))
        if not dd:
            continue
        block = _format_deep_dive_block(i, item, dd)
        if block:
            blocks.append(block)

    if not blocks:
        return None

    header = [
        "\U0001F52C <b>Deep Dives</b>",
        f"<i>{len(blocks)} of {len(items)} items have detailed analysis.</i>",
        "",
    ]
    return "\n".join(header + blocks)


def _format_deep_dive_block(index: int, item: dict, dd: dict) -> str | None:
    title = _escape_html(str(item.get("title", "Untitled"))[:80])
    source = item.get("source", "unknown")
    score = item.get("normalized_score", 0)

    field_lines: list[tuple[str, str]] = []
    for label, key in (
        ("What", "what_it_is"),
        ("Why trending", "why_trending"),
        ("Pain", "pain_point"),
        ("Idea", "app_idea"),
    ):
        value = _clean_field(dd.get(key))
        if value:
            field_lines.append((label, _truncate(value, 200)))

    competitors = [str(c).strip() for c in (dd.get("competitors") or []) if str(c).strip()]
    competitors = competitors[:5]

    if not field_lines and not competitors:
        return None

    lines = [
        f"\U0001F52C <b>#{index} \u00b7 {title}</b> "
        f"<i>({source} \u00b7 score {score:.0f})</i>"
    ]
    for label, value in field_lines:
        lines.append(f"<b>{label}:</b> {_escape_html(value)}")
    if competitors:
        lines.append(
            f"<b>Competitors:</b> {_escape_html(', '.join(competitors))}"
        )
    lines.append("")
    return "\n".join(lines)


def _clean_field(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "n/a", "none", "null"}:
        return ""
    return text


def format_topics(topics: list[dict]) -> str:
    """Format topic list for Telegram."""
    if not topics:
        return "No active topics."

    lines = ["\U0001F4CB <b>Your Topics</b>", ""]
    for t in topics:
        weight = t.get("weight", 1.0)
        indicator = "\U0001F534" if weight >= 2.0 else "\U0001F7E1" if weight >= 1.0 else "\u26aa"
        lines.append(f"{indicator} {_escape_html(t['name'])} (weight: {weight:.1f})")

    return "\n".join(lines)


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
