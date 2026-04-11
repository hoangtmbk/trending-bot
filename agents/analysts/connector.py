from __future__ import annotations
import json
import logging
from agents.base import BaseAgent, AgentContext, AgentResult
from db.queries import get_items

logger = logging.getLogger(__name__)

DOT_CONNECTOR_PROMPT = """Analyze these items and identify relationships between them.
For each pair that has a meaningful relationship, return it in this format:

```json
{
  "connections": [
    {
      "item_a_index": 0,
      "item_b_index": 3,
      "relationship": "competes_with",
      "description": "Both are RAG frameworks targeting enterprise use"
    }
  ]
}
```

Relationship types: competes_with, builds_on, same_topic, evolves_from

Only report strong, clear relationships. Quality over quantity.

Items:
{items_json}
"""


class DotConnector(BaseAgent):
    name = "dot_connector"
    schedule = "0 3 * * *"  # daily at 3 AM

    def execute(self, ctx: AgentContext) -> AgentResult:
        from datetime import datetime, timedelta, timezone

        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        items = get_items(ctx.db, since=since, limit=50, order_by="normalized_score DESC")

        if len(items) < 2:
            return AgentResult(success=True, message="Not enough items for dot connecting")

        items_for_prompt = []
        for i, item in enumerate(items):
            items_for_prompt.append({
                "index": i,
                "title": item["title"],
                "url": item["url"],
                "source": item["source"],
                "description": item.get("description", "")[:200],
            })

        try:
            from claude_cli import call_claude_json
            prompt = DOT_CONNECTOR_PROMPT.replace("{items_json}", json.dumps(items_for_prompt, indent=2))
            result = call_claude_json(prompt)
        except Exception as e:
            logger.error(f"Dot connector LLM call failed: {e}")
            return AgentResult(success=False, message=str(e))

        connections_added = 0
        for conn_data in result.get("connections", []):
            idx_a = conn_data.get("item_a_index", -1)
            idx_b = conn_data.get("item_b_index", -1)
            if idx_a < 0 or idx_b < 0 or idx_a >= len(items) or idx_b >= len(items):
                continue

            relationship = conn_data.get("relationship", "same_topic")
            valid_relationships = {"competes_with", "builds_on", "same_topic", "evolves_from"}
            if relationship not in valid_relationships:
                relationship = "same_topic"

            with ctx.db.connect() as db_conn:
                db_conn.execute(
                    "INSERT INTO item_connections (item_a_id, item_b_id, relationship, description, created_at) "
                    "VALUES (?, ?, ?, ?, datetime('now'))",
                    (items[idx_a]["id"], items[idx_b]["id"], relationship,
                     conn_data.get("description", "")),
                )
                db_conn.commit()
            connections_added += 1

        return AgentResult(success=True,
                           message=f"Found {connections_added} connections",
                           data={"connections_count": connections_added})
