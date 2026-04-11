from __future__ import annotations
import json
import logging
from agents.base import BaseAgent, AgentContext, AgentResult
from db.queries import get_item_by_id

logger = logging.getLogger(__name__)


class CompetitorWatcher(BaseAgent):
    name = "competitor_watcher"
    schedule = "on_demand"

    def execute(self, ctx: AgentContext) -> AgentResult:
        # Get bookmarked items that have deep dive analyses with competitors
        with ctx.db.connect() as conn:
            bookmarked = conn.execute(
                "SELECT DISTINCT ua.item_id FROM user_actions ua "
                "WHERE ua.action = 'bookmarked'"
            ).fetchall()

        if not bookmarked:
            return AgentResult(success=True, message="No bookmarked items to watch")

        watched = 0
        for row in bookmarked:
            item_id = row["item_id"]
            item = get_item_by_id(ctx.db, item_id)
            if not item:
                continue

            # Get deep dive with competitors
            with ctx.db.connect() as conn:
                analysis = conn.execute(
                    "SELECT content FROM item_analysis WHERE item_id=? AND analysis_type='deep_dive'",
                    (item_id,),
                ).fetchone()

            if not analysis:
                continue

            content = json.loads(analysis["content"])
            competitors = content.get("competitors", [])
            if not competitors:
                continue

            # Check if competitors appear in our DB
            competitor_items = []
            for comp in competitors:
                with ctx.db.connect() as conn:
                    matches = conn.execute(
                        "SELECT id, title, url, normalized_score FROM items WHERE title LIKE ?",
                        (f"%{comp}%",),
                    ).fetchall()
                    competitor_items.extend([dict(m) for m in matches])

            if competitor_items:
                # Store a connection for each competitor found
                with ctx.db.connect() as conn:
                    for comp_item in competitor_items:
                        if comp_item["id"] != item_id:
                            # Check for existing connection to avoid duplicates
                            existing = conn.execute(
                                "SELECT id FROM item_connections "
                                "WHERE item_a_id=? AND item_b_id=? AND relationship='competes_with'",
                                (item_id, comp_item["id"]),
                            ).fetchone()
                            if not existing:
                                conn.execute(
                                    "INSERT INTO item_connections "
                                    "(item_a_id, item_b_id, relationship, description, created_at) "
                                    "VALUES (?, ?, 'competes_with', ?, datetime('now'))",
                                    (item_id, comp_item["id"],
                                     f"Competitor of {item['title']}"),
                                )
                    conn.commit()
                watched += 1

        return AgentResult(
            success=True,
            message=f"Watched competitors for {watched} items",
            data={"watched_count": watched},
        )
