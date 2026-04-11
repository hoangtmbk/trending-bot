from __future__ import annotations
import json
import logging
from agents.base import BaseAgent, AgentContext, AgentResult

logger = logging.getLogger(__name__)

TOPIC_REPORT_PROMPT = """You are tracking the topic "{topic_name}" in the AI/ML landscape.

Here are the items related to this topic from the past {days} days:
{items_json}

Write a trajectory report:
1. Is this topic accelerating, plateauing, or declining?
2. Key developments this period
3. What to watch for next

Return JSON:
```json
{{
  "trajectory": "accelerating|plateauing|declining|emerging",
  "summary": "2-3 sentence overview",
  "key_developments": ["development 1", "development 2"],
  "watch_for": "What to look for next"
}}
```
"""


class TopicTracker(BaseAgent):
    name = "topic_tracker"
    schedule = "0 4 * * 1"  # Weekly Monday 4 AM

    def execute(self, ctx: AgentContext) -> AgentResult:
        from datetime import datetime, timedelta, timezone

        # Get all active tracked topics (user interests with weight > 0)
        with ctx.db.connect() as conn:
            tracked = conn.execute(
                "SELECT t.id, t.name FROM topics t "
                "JOIN user_interests ui ON t.id = ui.topic_id "
                "WHERE ui.weight > 0 AND t.is_active = 1"
            ).fetchall()

        if not tracked:
            return AgentResult(success=True, message="No tracked topics")

        days = ctx.payload.get("days", 7)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        reports_created = 0

        for topic_row in tracked:
            topic_id = topic_row["id"]
            topic_name = topic_row["name"]

            # Get items for this topic
            with ctx.db.connect() as conn:
                items = conn.execute(
                    "SELECT i.* FROM items i "
                    "JOIN item_topics it ON i.id = it.item_id "
                    "WHERE it.topic_id = ? AND i.last_seen >= ? "
                    "ORDER BY i.normalized_score DESC LIMIT 20",
                    (topic_id, since),
                ).fetchall()

            if not items:
                continue

            items_data = [{"title": dict(i)["title"], "url": dict(i)["url"],
                          "source": dict(i)["source"], "score": dict(i).get("normalized_score", 0)}
                         for i in items]

            prompt = TOPIC_REPORT_PROMPT.replace("{topic_name}", topic_name)
            prompt = prompt.replace("{days}", str(days))
            prompt = prompt.replace("{items_json}", json.dumps(items_data, indent=2))

            try:
                from claude_cli import call_claude_json
                result = call_claude_json(prompt)
            except Exception as e:
                logger.error(f"Topic tracker failed for {topic_name}: {e}")
                continue

            # Store as item_analysis on the first item (representative)
            with ctx.db.connect() as conn:
                conn.execute(
                    "INSERT INTO item_analysis (item_id, analysis_type, created_at, content, prompt_version) "
                    "VALUES (?, 'topic_report', datetime('now'), ?, 'v1')",
                    (dict(items[0])["id"], json.dumps({"topic": topic_name, **result})),
                )
                conn.commit()
            reports_created += 1

        return AgentResult(
            success=True,
            message=f"Created {reports_created} topic reports",
            data={"reports_count": reports_created},
        )
