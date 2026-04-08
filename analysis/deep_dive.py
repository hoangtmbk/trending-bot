from __future__ import annotations
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from models import ScoredItem, AnalysisReport
from analysis.gatherer import gather_source_material
from claude_cli import call_claude_json

logger = logging.getLogger(__name__)


def _slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:60]


def run_deep_dive(item: ScoredItem) -> AnalysisReport:
    material = gather_source_material(item)

    source_material_text = []
    for key, value in material.items():
        if value and key not in ("title", "url", "description"):
            source_material_text.append(f"### {key.upper()}\n{value}")
    source_str = "\n\n".join(source_material_text) if source_material_text else "No additional material available."

    prompt_template = (Path(__file__).parent.parent / "prompts" / "deep_dive.md").read_text()
    prompt = prompt_template.replace("{title}", item.title)
    prompt = prompt.replace("{url}", item.url)
    prompt = prompt.replace("{llm_summary}", item.llm_summary)
    prompt = prompt.replace("{source_material}", source_str)

    result = call_claude_json(prompt)

    return AnalysisReport(
        slug=_slugify(item.title),
        title=item.title,
        what_it_is=result.get("what_it_is", ""),
        why_trending=result.get("why_trending", ""),
        pain_point=result.get("pain_point", ""),
        gap_analysis=result.get("gap_analysis", ""),
        competitors=result.get("competitors", []),
        app_idea=result.get("app_idea", ""),
        feasibility=result.get("feasibility", {}),
    )


def run_deep_dives(items: list[ScoredItem], data_dir: Path) -> list[AnalysisReport]:
    analysis_dir = data_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    reports = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_item = {executor.submit(run_deep_dive, item): item for item in items}
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                report = future.result()
                reports.append(report)
                md_path = analysis_dir / f"{report.slug}.md"
                md_path.write_text(report.to_markdown())
                json_path = analysis_dir / f"{report.slug}.json"
                json_path.write_text(json.dumps(report.to_dict(), indent=2))
                logger.info(f"Deep dive completed: {report.title}")
            except Exception as e:
                logger.error(f"Deep dive failed for {item.title}: {e}")

    return reports
