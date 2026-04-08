from __future__ import annotations
import logging
import re
import shutil
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from models import ScoredItem, AnalysisReport

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:60]


def build_dashboard(
    items: list[ScoredItem],
    reports: list[AnalysisReport],
    data_dir: Path,
    date_str: str,
) -> Path:
    dashboard_dir = data_dir / "reports" / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    assets_src = TEMPLATES_DIR / "assets"
    assets_dst = dashboard_dir / "assets"
    if assets_src.exists():
        if assets_dst.exists():
            shutil.rmtree(assets_dst)
        shutil.copytree(assets_src, assets_dst)

    deep_dive_slugs = {r.slug for r in reports}

    items_data = []
    for item in items:
        items_data.append({
            "title": item.title,
            "url": item.url,
            "slug": _slugify(item.title),
            "llm_summary": item.llm_summary,
            "interest_score": item.interest_score,
            "sources": item.sources,
            "category": item.category,
        })

    index_tmpl = env.get_template("index.html")
    index_html = index_tmpl.render(
        date=date_str,
        items=items_data,
        deep_dive_slugs=deep_dive_slugs,
    )
    index_path = dashboard_dir / "index.html"
    index_path.write_text(index_html)

    item_tmpl = env.get_template("item.html")
    report_map = {r.slug: r for r in reports}
    for item_data in items_data:
        slug = item_data["slug"]
        if slug in report_map:
            report = report_map[slug]
            item_html = item_tmpl.render(
                date=date_str,
                url=item_data["url"],
                report={
                    "title": report.title,
                    "what_it_is": report.what_it_is,
                    "why_trending": report.why_trending,
                    "pain_point": report.pain_point,
                    "gap_analysis": report.gap_analysis,
                    "competitors": report.competitors,
                    "app_idea": report.app_idea,
                    "feasibility": report.feasibility,
                },
            )
            (dashboard_dir / f"{slug}.html").write_text(item_html)

    logger.info(f"Dashboard built at {dashboard_dir}")
    return dashboard_dir
