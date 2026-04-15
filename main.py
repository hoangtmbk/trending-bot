#!/usr/bin/env python3
"""TrendBot — unified entry point.

Starts the orchestrator (scheduler + task dispatcher), web dashboard,
and optionally the Telegram bot.  Use --run-now to trigger an immediate
collection → score → filter cycle on first launch.

Usage:
    python main.py                  # start orchestrator + web
    python main.py --run-now        # also run all scouts immediately
    python main.py --port 9090      # custom web port
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import threading
import time
from pathlib import Path

from config import load_config, get_env
from db.database import Database
from db.queries import enqueue_task
from orchestrator.app import Application

# Agents
from agents.scouts.github_scout import GitHubScout
from agents.scouts.reddit_scout import RedditScout
from agents.scouts.arxiv_scout import ArxivScout
from agents.scouts.huggingface_scout import HuggingFaceScout
from agents.scouts.hackernews_scout import HackerNewsScout
from agents.scouts.twitter_scout import TwitterScout
from agents.analysts.scorer import TrendScorer
from agents.analysts.filter import RelevanceFilter
from agents.analysts.connector import DotConnector
from agents.analysts.interest_adjuster import InterestAdjuster
from agents.researchers.deep_diver import DeepDiver
from agents.researchers.topic_tracker import TopicTracker
from agents.researchers.competitor_watch import CompetitorWatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("trendbot")


def _register_all_agents(app: Application) -> None:
    agents = [
        GitHubScout(),
        RedditScout(),
        ArxivScout(),
        HuggingFaceScout(),
        HackerNewsScout(),
        TwitterScout(),
        TrendScorer(),
        RelevanceFilter(),
        DotConnector(),
        InterestAdjuster(),
        DeepDiver(),
        TopicTracker(),
        CompetitorWatcher(),
    ]
    for agent in agents:
        app.register_agent(agent)
        logger.info(f"  ✓ {agent.name} ({agent.schedule})")


def _wire_events(app: Application) -> None:
    """Chain agents via events so collection triggers scoring triggers filtering."""
    # Keep a simple debounce — don't re-enqueue scorer if one is already pending
    def _on_items_updated(data: dict) -> None:
        from db.queries import get_pending_tasks
        pending = get_pending_tasks(app.db, agent_type="scorer")
        if not pending:
            enqueue_task(app.db, agent_type="scorer", payload={}, priority=5)
            logger.info("Event: items_updated → enqueued scorer")

    def _on_scores_updated(data: dict) -> None:
        from db.queries import get_pending_tasks
        pending = get_pending_tasks(app.db, agent_type="filter")
        if not pending:
            enqueue_task(app.db, agent_type="filter", payload={}, priority=4)
            logger.info("Event: scores_updated → enqueued filter")

    app.on_event("items_updated", _on_items_updated)
    app.on_event("scores_updated", _on_scores_updated)


def _start_web(db: Database, config: dict, port: int) -> threading.Thread:
    """Start FastAPI web dashboard in a daemon thread."""
    from interfaces.web.app import create_app
    import uvicorn

    fastapi_app = create_app(db, config)

    def _run():
        uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="warning")

    t = threading.Thread(target=_run, daemon=True, name="web-server")
    t.start()
    logger.info(f"Web dashboard running at http://localhost:{port}")
    return t


async def _run_telegram_polling(tg_app) -> None:
    """Run telegram polling without signal handlers (safe for non-main threads)."""
    async with tg_app:
        await tg_app.start()
        await tg_app.updater.start_polling()
        # Block until the thread is interrupted
        stop_event = asyncio.Event()
        await stop_event.wait()


def _start_telegram(db: Database, config: dict) -> threading.Thread | None:
    """Start Telegram bot in a daemon thread (if configured)."""
    delivery_cfg = config.get("delivery", {}).get("telegram", {})
    if not delivery_cfg.get("enabled", False):
        logger.info("Telegram bot disabled in config")
        return None

    try:
        bot_token = get_env("TELEGRAM_BOT_TOKEN")
    except EnvironmentError:
        logger.warning("TELEGRAM_BOT_TOKEN not set — skipping Telegram bot")
        return None

    from interfaces.telegram.bot import create_bot

    tg_app = create_bot(bot_token, db, config)

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_telegram_polling(tg_app))

    t = threading.Thread(target=_run, daemon=True, name="telegram-bot")
    t.start()
    logger.info("Telegram bot started")
    return t


def _run_now(app: Application) -> None:
    """Immediately trigger all enabled scouts, then scorer + filter."""
    from agents.base import AgentContext

    scouts = ["github_scout", "reddit_scout", "arxiv_scout",
              "huggingface_scout", "hackernews_scout", "twitter_scout"]

    logger.info("── Running initial collection cycle ──")
    for name in scouts:
        if name in app.scheduler.agents:
            logger.info(f"Running {name}...")
            app.scheduler.run_agent(name)

    # Scorer and filter are on-demand — enqueue them in sequence
    enqueue_task(app.db, agent_type="scorer", payload={}, priority=10)
    enqueue_task(app.db, agent_type="filter", payload={}, priority=9)
    logger.info("Enqueued scorer + filter tasks")

    # Let the dispatcher process those tasks
    time.sleep(1)
    app.dispatcher.process_all()
    logger.info("── Initial cycle complete ──")


def main() -> None:
    parser = argparse.ArgumentParser(description="TrendBot — personal AI trends assistant")
    parser.add_argument("--run-now", action="store_true",
                        help="Immediately run all scouts + scoring (first run)")
    parser.add_argument("--port", type=int, default=None,
                        help="Web dashboard port (default: from config or 8080)")
    parser.add_argument("--no-web", action="store_true",
                        help="Skip starting the web dashboard")
    parser.add_argument("--no-telegram", action="store_true",
                        help="Skip starting the Telegram bot")
    args = parser.parse_args()

    config = load_config()

    # Database
    db_path = config.get("orchestrator", {}).get("db_path", "trendbot.db")
    db = Database(db_path)
    db.initialize()
    logger.info(f"Database: {db_path}")

    # Orchestrator
    app = Application(db, config)
    logger.info("Registering agents:")
    _register_all_agents(app)
    _wire_events(app)

    # Web dashboard
    if not args.no_web:
        port = args.port or config.get("delivery", {}).get("dashboard", {}).get("port", 8080)
        _start_web(db, config, port)

    # Telegram bot
    if not args.no_telegram:
        _start_telegram(db, config)

    # Immediate collection
    if args.run_now:
        _run_now(app)

    # Start orchestrator (scheduler + dispatcher loop) — blocks until signal
    logger.info("TrendBot is live. Press Ctrl+C to stop.")
    app.run_forever()


if __name__ == "__main__":
    main()
