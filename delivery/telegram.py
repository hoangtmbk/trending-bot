from __future__ import annotations
import logging
import requests
from models import ScoredItem, AnalysisReport

logger = logging.getLogger(__name__)

SOURCE_ICONS = {
    "github": "⭐", "reddit": "💬", "arxiv": "📄",
    "huggingface": "🤗", "twitter": "𝕏", "hackernews": "🔶",
}


def format_telegram_message(
    items: list[ScoredItem],
    reports: list[AnalysisReport],
    date_str: str,
    dashboard_url: str = "",
) -> str:
    lines = [f"🔥 AI Trending — {date_str}", f"{len(items)} items · {len(reports)} deep dives", ""]

    if reports:
        top = reports[0]
        lines.append(f"📌 Top pick: {top.title}")
        lines.append(f"💡 Opportunity: {top.app_idea[:100]}")
        lines.append("")

    by_source: dict[str, list[str]] = {}
    for item in items[:10]:
        for src in item.sources:
            by_source.setdefault(src, []).append(item.title)

    for source, titles in sorted(by_source.items()):
        icon = SOURCE_ICONS.get(source, "•")
        title_list = ", ".join(titles[:3])
        if len(titles) > 3:
            title_list += f" +{len(titles) - 3}"
        lines.append(f"{icon} {source.title()}: {title_list}")

    if dashboard_url:
        lines.append(f"\n📊 Dashboard → {dashboard_url}")

    return "\n".join(lines)


def send_telegram_message(text: str, bot_token: str, chat_id: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        logger.info("Telegram message sent successfully")
    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram message: {e}")
        raise


def send_error_notification(error_msg: str, bot_token: str, chat_id: str) -> None:
    text = f"⚠️ AI Trending Bot Error\n\n{error_msg}"
    try:
        send_telegram_message(text, bot_token, chat_id)
    except Exception:
        logger.error("Failed to send error notification via Telegram")
