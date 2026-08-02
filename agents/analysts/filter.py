from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta, timezone
from agents.base import BaseAgent, AgentContext, AgentResult
from db.queries import get_unfiltered_items, enqueue_task

logger = logging.getLogger(__name__)

# Candidate window, matching the scorer's own 48h bound
# (`agents/analysts/scorer.py`). Beyond it `normalized_score` is frozen rather
# than decayed, so ranking a wider pool by it would be meaningless.
FILTER_WINDOW_HOURS = 48


class RelevanceFilter(BaseAgent):
    name = "filter"
    schedule = "on_demand"  # triggered by scorer

    def execute(self, ctx: AgentContext) -> AgentResult:
        scoring_cfg = ctx.config.get("scoring", {})
        top_count = scoring_cfg.get("filter_pool_size", 30)
        deep_dive_cap = scoring_cfg.get("deep_dive_count", 5)

        # Recent items that have never been filtered. Each item gets exactly one
        # verdict for its lifetime — the filter judges content, which does not
        # change, so re-running it only burns ~100s Claude CLI calls. See
        # `get_unfiltered_items` for why both bounds matter.
        since = (datetime.now(timezone.utc)
                 - timedelta(hours=FILTER_WINDOW_HOURS)).isoformat()
        items = get_unfiltered_items(ctx.db, since=since, limit=top_count)

        if not items:
            # The steady state once the backlog drains, not an anomaly.
            return AgentResult(success=True, message="No items to filter")

        try:
            results = self._run_llm_filter(items)
        except Exception as e:
            # Deliberately no fallback verdict. Filtering is once-per-item, so a
            # fabricated verdict would be permanent; the scorer re-enqueues this
            # agent after every scout, so a transient failure self-heals.
            logger.error(f"LLM filter failed, leaving {len(items)} items unfiltered: {e}")
            return AgentResult(success=False, message=f"LLM filter failed: {e}")

        # Store analysis results and assign topics
        analyzed = 0
        deep_dive_candidates: list[tuple[int, dict]] = []  # (item_id, eval_item)
        for eval_item in results:
            idx = eval_item.get("index", -1)
            if idx < 0 or idx >= len(items):
                continue

            db_item = items[idx]
            passed = (eval_item.get("novel", False)
                      and eval_item.get("ai_relevant", False))

            with ctx.db.connect() as conn:
                # Written for rejected items too. "Not novel" is a verdict, and
                # selection skips any item that has one — without this row the
                # item returns to the pool on the next run and is re-sent to the
                # LLM for the rest of the window. Readers are unaffected:
                # get_items_with_filter gates on novel AND ai_relevant, and the
                # digest gates on status='tracking', which stays 'new' below.
                conn.execute(
                    "INSERT INTO item_analysis (item_id, analysis_type, created_at, content, prompt_version) "
                    "VALUES (?, 'filter', datetime('now'), ?, 'v1')",
                    (db_item["id"], json.dumps(eval_item)),
                )

                if passed:
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
                    conn.execute(
                        "UPDATE items SET status='tracking' WHERE id=? AND status='new'",
                        (db_item["id"],),
                    )
                conn.commit()

            if not passed:
                continue
            analyzed += 1

            if eval_item.get("deep_dive"):
                deep_dive_candidates.append((db_item["id"], eval_item))

        enqueued = self._enqueue_deep_dives(ctx, deep_dive_candidates, deep_dive_cap)

        ctx.emit("analysis_complete", {"analyzed_count": analyzed,
                                       "deep_dive_enqueued": enqueued})
        return AgentResult(success=True,
                           message=f"Filtered {analyzed} items, enqueued {enqueued} deep dives",
                           data={"analyzed_count": analyzed, "deep_dive_enqueued": enqueued})

    def _enqueue_deep_dives(
        self, ctx: AgentContext, candidates: list[tuple[int, dict]], cap: int
    ) -> int:
        """Enqueue deep_diver tasks for top candidates, respecting cap and skipping
        items that already have a deep dive analysis or a pending/running task."""
        if not candidates or cap <= 0:
            return 0

        ranked = sorted(candidates,
                        key=lambda c: c[1].get("interest_score", 0),
                        reverse=True)

        enqueued = 0
        with ctx.db.connect() as conn:
            for item_id, _ in ranked:
                if enqueued >= cap:
                    break
                existing_analysis = conn.execute(
                    "SELECT 1 FROM item_analysis "
                    "WHERE item_id=? AND analysis_type='deep_dive' LIMIT 1",
                    (item_id,),
                ).fetchone()
                if existing_analysis:
                    continue
                # Skip if a deep_diver task for this item is already pending or running.
                pending_task = conn.execute(
                    "SELECT 1 FROM task_queue "
                    "WHERE agent_type='deep_diver' AND status IN ('pending','running') "
                    "AND payload LIKE ? LIMIT 1",
                    (f'%"item_id": {item_id}%',),
                ).fetchone()
                if pending_task:
                    continue
                enqueue_task(ctx.db, agent_type="deep_diver",
                             payload={"item_id": item_id}, priority=3)
                enqueued += 1
        return enqueued

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
