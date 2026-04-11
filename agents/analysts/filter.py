from __future__ import annotations
import json
import logging
from agents.base import BaseAgent, AgentContext, AgentResult
from db.queries import get_items

logger = logging.getLogger(__name__)


class RelevanceFilter(BaseAgent):
    name = "filter"
    schedule = "on_demand"  # triggered by scorer

    def execute(self, ctx: AgentContext) -> AgentResult:
        scoring_cfg = ctx.config.get("scoring", {})
        digest_size = scoring_cfg.get("digest_size", 15)
        top_count = scoring_cfg.get("filter_pool_size", 30)

        # Get top items by normalized_score
        items = get_items(ctx.db, limit=top_count, order_by="normalized_score DESC")

        if not items:
            return AgentResult(success=True, message="No items to filter")

        try:
            results = self._run_llm_filter(items)
        except Exception as e:
            logger.error(f"LLM filter failed: {e}")
            # Fallback: keep top items as-is
            results = [{"index": i, "novel": True, "ai_relevant": True,
                        "category": "unknown", "interest_score": 5,
                        "summary": item["title"], "deep_dive": i < 5}
                       for i, item in enumerate(items[:digest_size])]

        # Store analysis results and assign topics
        analyzed = 0
        for eval_item in results:
            idx = eval_item.get("index", -1)
            if idx < 0 or idx >= len(items):
                continue

            if not eval_item.get("novel", False) or not eval_item.get("ai_relevant", False):
                continue

            db_item = items[idx]
            # Store filter analysis
            with ctx.db.connect() as conn:
                conn.execute(
                    "INSERT INTO item_analysis (item_id, analysis_type, created_at, content, prompt_version) "
                    "VALUES (?, 'filter', datetime('now'), ?, 'v1')",
                    (db_item["id"], json.dumps(eval_item)),
                )

                # Create/find topic and assign
                category = eval_item.get("category", "unknown")
                conn.execute(
                    "INSERT OR IGNORE INTO topics (name, created_at) VALUES (?, datetime('now'))",
                    (category,),
                )
                topic = conn.execute("SELECT id FROM topics WHERE name=?", (category,)).fetchone()
                if topic:
                    conn.execute(
                        "INSERT OR REPLACE INTO item_topics (item_id, topic_id, confidence) VALUES (?, ?, ?)",
                        (db_item["id"], topic["id"], eval_item.get("interest_score", 5) / 10.0),
                    )
                conn.commit()
            analyzed += 1

        ctx.emit("analysis_complete", {"analyzed_count": analyzed})
        return AgentResult(success=True, message=f"Filtered {analyzed} items",
                           data={"analyzed_count": analyzed})

    def _run_llm_filter(self, items: list[dict]) -> list[dict]:
        from claude_cli import call_claude_json
        from pathlib import Path

        items_for_prompt = []
        for i, item in enumerate(items):
            metrics = json.loads(item["raw_metrics"]) if item["raw_metrics"] else {}
            items_for_prompt.append({
                "index": i,
                "title": item["title"],
                "url": item["url"],
                "description": item.get("description", ""),
                "source": item["source"],
                "momentum_score": item.get("momentum_score", 0),
            })

        prompt_path = Path(__file__).parent.parent.parent / "prompts" / "filter.md"
        prompt = prompt_path.read_text().replace("{items_json}", json.dumps(items_for_prompt, indent=2))
        result = call_claude_json(prompt)
        return result.get("items", [])
