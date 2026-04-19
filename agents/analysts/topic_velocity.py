from __future__ import annotations
import logging

from agents.base import BaseAgent, AgentContext, AgentResult

logger = logging.getLogger(__name__)


class TopicVelocityAgent(BaseAgent):
    """Runs periodically to snapshot per-topic item counts in rolling windows.

    Writes rows to `topic_velocity` for later queries ("what's rising this
    week?"). The digest and dashboard can read these to surface themes
    that are accelerating, not just items that happen to be hot.
    """
    name = "topic_velocity"
    schedule = "0 */4 * * *"

    def execute(self, ctx: AgentContext) -> AgentResult:
        from scoring.velocity import compute_topic_velocities, record_velocities

        velocities = compute_topic_velocities(ctx.db, window_hours=24)
        if not velocities:
            return AgentResult(success=True, message="No topics with items to measure")

        written = record_velocities(ctx.db, velocities, window_hours=24)
        rising = [v for v in velocities if v["velocity_ratio"] >= 2.0]
        return AgentResult(
            success=True,
            message=f"Recorded {written} topic velocities ({len(rising)} rising ≥2×)",
            data={"count": written, "rising_count": len(rising)},
        )
