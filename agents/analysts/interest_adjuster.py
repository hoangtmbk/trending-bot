from __future__ import annotations
import json
import logging
from agents.base import BaseAgent, AgentContext, AgentResult

logger = logging.getLogger(__name__)

INTEREST_ADJUSTER_PROMPT = """Review this user's recent actions and current interest profile.

Current interests (topic: weight):
{interests_json}

Recent actions (last 7 days):
{actions_json}

Based on the user's behavior, suggest adjustments to their interest profile.
Each adjustment should be small (max ±0.3 per topic per week).

Return JSON:
```json
{{
  "adjustments": [
    {{"topic": "topic_name", "delta": 0.2, "reason": "User bookmarked 3 items in this area"}},
    {{"topic": "topic_name", "delta": -0.1, "reason": "User dismissed multiple items"}}
  ]
}}
```

Only suggest adjustments when the evidence is clear. Prefer no change over uncertain changes.
"""


class InterestAdjuster(BaseAgent):
    name = "interest_adjuster"
    schedule = "0 5 * * 1"  # Weekly Monday 5 AM (after topic tracker)

    def execute(self, ctx: AgentContext) -> AgentResult:
        from datetime import datetime, timedelta, timezone
        from memory.interests import get_interest_profile, set_interest

        profile = get_interest_profile(ctx.db)
        if not profile:
            return AgentResult(success=True, message="No interest profile to adjust")

        # Get recent actions
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        with ctx.db.connect() as conn:
            actions = [dict(r) for r in conn.execute(
                "SELECT ua.*, i.title, i.source FROM user_actions ua "
                "JOIN items i ON ua.item_id = i.id "
                "WHERE ua.created_at >= ? ORDER BY ua.created_at DESC",
                (since,),
            ).fetchall()]

        if not actions:
            return AgentResult(success=True, message="No recent actions to learn from")

        actions_summary = [{"action": a["action"], "title": a["title"], "source": a["source"]}
                          for a in actions[:50]]

        prompt = INTEREST_ADJUSTER_PROMPT.replace("{interests_json}", json.dumps(profile, indent=2))
        prompt = prompt.replace("{actions_json}", json.dumps(actions_summary, indent=2))

        try:
            from claude_cli import call_claude_json
            result = call_claude_json(prompt)
        except Exception as e:
            logger.error(f"Interest adjuster LLM call failed: {e}")
            return AgentResult(success=False, message=str(e))

        adjustments_applied = 0
        for adj in result.get("adjustments", []):
            topic = adj.get("topic", "")
            delta = adj.get("delta", 0)

            # Cap delta at +/-0.3
            delta = max(-0.3, min(0.3, delta))
            if delta == 0 or not topic:
                continue

            current = profile.get(topic, 1.0)
            new_weight = max(0.0, min(3.0, current + delta))
            set_interest(ctx.db, topic, new_weight, source="inferred")
            adjustments_applied += 1
            logger.info(f"Adjusted '{topic}': {current:.1f} -> {new_weight:.1f} ({delta:+.1f})")

        return AgentResult(
            success=True,
            message=f"Applied {adjustments_applied} interest adjustments",
            data={"adjustments_count": adjustments_applied},
        )
