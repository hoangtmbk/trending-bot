from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from agents.base import BaseAgent, AgentContext, AgentResult
from db.queries import get_item_by_id

logger = logging.getLogger(__name__)


def _slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:60]


class DeepDiver(BaseAgent):
    name = "deep_diver"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        item_id = ctx.payload.get("item_id")
        if not item_id:
            return AgentResult(success=False, message="No item_id in payload")

        item = get_item_by_id(ctx.db, item_id)
        if not item:
            return AgentResult(success=False, message=f"Item {item_id} not found")

        # Check if deep dive already exists
        with ctx.db.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM item_analysis WHERE item_id=? AND analysis_type='deep_dive'",
                (item_id,),
            ).fetchone()
        if existing:
            return AgentResult(success=True, message=f"Deep dive already exists for {item['title']}")

        # Gather source material
        source_material = self._gather_material(item)

        # Build prompt
        prompt_path = Path(__file__).parent.parent.parent / "prompts" / "deep_dive.md"
        prompt = prompt_path.read_text()

        # Get LLM summary from filter analysis if available
        llm_summary = ""
        with ctx.db.connect() as conn:
            filter_analysis = conn.execute(
                "SELECT content FROM item_analysis WHERE item_id=? AND analysis_type='filter'",
                (item_id,),
            ).fetchone()
            if filter_analysis:
                content = json.loads(filter_analysis["content"])
                llm_summary = content.get("summary", "")

        prompt = prompt.replace("{title}", item["title"])
        prompt = prompt.replace("{url}", item["url"])
        prompt = prompt.replace("{llm_summary}", llm_summary or item.get("description", ""))
        prompt = prompt.replace("{source_material}", source_material)

        try:
            from claude_cli import call_claude_json
            # Enable WebSearch + WebFetch so the analyst can look up competitor
            # projects, recent benchmarks, and author track record instead of
            # only seeing the scraped README/metadata.
            result = call_claude_json(
                prompt,
                allowed_tools=["WebSearch", "WebFetch"],
                # Deep dives are the long pole: 162s at p50, 296s at p99 of the
                # runs that *finished*. The old shared 300s cap sat inside that
                # distribution rather than beyond it, so it truncated the tail —
                # 194 of 218 historical failures were this timeout firing at
                # exactly 300s, discarding ~300s of work each time. The cap is
                # raised here only; other call sites keep the 300s default.
                timeout=600,
            )
        except Exception as e:
            return AgentResult(success=False, message=f"Claude CLI failed: {e}")

        # Store in DB
        with ctx.db.connect() as conn:
            conn.execute(
                "INSERT INTO item_analysis (item_id, analysis_type, created_at, content, prompt_version) "
                "VALUES (?, 'deep_dive', datetime('now'), ?, 'v1')",
                (item_id, json.dumps(result)),
            )
            conn.commit()

        ctx.emit("research_complete", {
            "item_id": item_id,
            "title": item["title"],
            "type": "deep_dive",
        })

        return AgentResult(
            success=True,
            message=f"Deep dive completed: {item['title']}",
            data={"item_id": item_id, "slug": _slugify(item["title"])},
        )

    def _gather_material(self, item: dict) -> str:
        """Gather source material based on item URL. Simplified version of gatherer.py for DB items."""
        import requests
        from urllib.parse import urlparse

        materials = []
        url = item["url"]
        parsed = urlparse(url)

        try:
            if "github.com" in parsed.netloc:
                parts = parsed.path.strip("/").split("/")
                if len(parts) >= 2:
                    owner, repo = parts[0], parts[1]
                    for branch in ["main", "master"]:
                        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
                        resp = requests.get(raw_url, timeout=15)
                        if resp.status_code == 200:
                            materials.append(f"### README\n{resp.text[:5000]}")
                            break

            elif "huggingface.co" in parsed.netloc:
                model_id = parsed.path.strip("/")
                api_url = f"https://huggingface.co/{model_id}/raw/main/README.md"
                resp = requests.get(api_url, timeout=15)
                if resp.status_code == 200:
                    materials.append(f"### README\n{resp.text[:5000]}")

            elif "reddit.com" in parsed.netloc:
                json_url = url.rstrip("/") + ".json"
                resp = requests.get(json_url, headers={"User-Agent": "trending-bot/1.0"}, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    if len(data) > 1:
                        comments = data[1].get("data", {}).get("children", [])[:10]
                        lines = [c.get("data", {}).get("body", "")[:300] for c in comments if c.get("data", {}).get("body")]
                        materials.append(f"### COMMENTS\n{'---'.join(lines)}")

        except Exception as e:
            logger.warning(f"Failed to gather material for {url}: {e}")

        return "\n\n".join(materials) if materials else "No additional material available."
