from __future__ import annotations
import logging
from pathlib import Path
from models import ScoredItem, AnalysisReport
from claude_cli import call_claude

logger = logging.getLogger(__name__)


def build_summary(
    items: list[ScoredItem],
    reports: list[AnalysisReport],
    data_dir: Path,
    date_str: str,
) -> Path:
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary_path = reports_dir / "summary.md"

    try:
        summary_text = _generate_via_claude(items, reports, date_str)
    except Exception as e:
        logger.error(f"Summary generation failed, using fallback: {e}")
        summary_text = _fallback_summary(items, reports, date_str)

    summary_path.write_text(summary_text)
    logger.info(f"Summary written to {summary_path}")
    return summary_path


def _generate_via_claude(
    items: list[ScoredItem],
    reports: list[AnalysisReport],
    date_str: str,
) -> str:
    items_summary = "\n".join(
        f"- {item.title} ({item.category}, score {item.interest_score}/10): {item.llm_summary}"
        for item in items
    )
    deep_dive_highlights = "\n".join(
        f"- **{r.title}**: {r.pain_point[:100]}... -> {r.app_idea[:100]}"
        for r in reports
    ) if reports else "No deep dives today."

    prompt_template = (Path(__file__).parent.parent / "prompts" / "summary.md").read_text()
    prompt = prompt_template.replace("{date}", date_str)
    prompt = prompt.replace("{items_summary}", items_summary)
    prompt = prompt.replace("{deep_dive_highlights}", deep_dive_highlights)

    return call_claude(prompt)


def _fallback_summary(
    items: list[ScoredItem],
    reports: list[AnalysisReport],
    date_str: str,
) -> str:
    lines = [f"# AI Trending Summary — {date_str}", "", f"Found {len(items)} trending items.", ""]
    for item in items[:5]:
        lines.append(f"- **{item.title}** (score: {item.interest_score}/10): {item.llm_summary}")
    if reports:
        lines.append("")
        lines.append("## Deep Dive Highlights")
        for r in reports:
            lines.append(f"- **{r.title}**: {r.app_idea}")
    return "\n".join(lines)
