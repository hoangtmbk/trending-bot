from __future__ import annotations
import argparse
import json
import logging
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from config import load_config, get_env
from models import RawItem, ScoredItem
from collectors.hackernews import HackerNewsCollector
from collectors.github import GitHubCollector
from collectors.reddit import RedditCollector, RedditPublicCollector
from collectors.arxiv import ArxivCollector
from collectors.huggingface import HuggingFaceCollector
from collectors.twitter import TwitterCollector
from scoring.momentum import compute_momentum_score, compute_final_score, normalize_by_source
from scoring.dedup import deduplicate
from scoring.llm_filter import run_llm_filter
from analysis.deep_dive import run_deep_dives
from reporting.digest import build_digest
from reporting.summary import build_summary
from reporting.dashboard import build_dashboard
from delivery.telegram import format_telegram_message, send_telegram_message, send_error_notification

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def select_diverse_top(items: list[ScoredItem], count: int = 30) -> list[ScoredItem]:
    """Select top items with round-robin source interleaving for diversity."""
    by_source: dict[str, list[ScoredItem]] = defaultdict(list)
    for item in items:
        primary_source = item.sources[0]
        by_source[primary_source].append(item)

    for src in by_source:
        by_source[src].sort(key=lambda x: x.final_score, reverse=True)

    selected: list[ScoredItem] = []
    pointers: dict[str, int] = {src: 0 for src in by_source}

    while len(selected) < count:
        added_this_round = False
        for src in sorted(by_source.keys()):
            if pointers[src] < len(by_source[src]):
                selected.append(by_source[src][pointers[src]])
                pointers[src] += 1
                added_this_round = True
                if len(selected) >= count:
                    break
        if not added_this_round:
            break

    return selected


class Pipeline:
    def __init__(self, config: dict | None = None, data_root: Path | None = None,
                 date_str: str | None = None):
        self.config = config or load_config()
        self.date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        data_root = data_root or Path("data")
        self.data_dir = data_root / self.date_str
        self.data_dir.mkdir(parents=True, exist_ok=True)

        log_path = self.data_dir / "pipeline.log"
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(file_handler)

    def stage_collect(self) -> list[RawItem]:
        logger.info("=== Stage 1: Collect ===")
        sources = self.config.get("sources", {})
        collectors = []

        if sources.get("hackernews", {}).get("enabled"):
            collectors.append(HackerNewsCollector())

        if sources.get("github", {}).get("enabled"):
            try:
                token = get_env("GITHUB_TOKEN")
                gh_cfg = sources["github"]
                collectors.append(GitHubCollector(
                    token=token,
                    topics=gh_cfg.get("topics"),
                    min_stars_new=gh_cfg.get("min_stars_new_repo", 20),
                    min_stars_established=gh_cfg.get("min_stars_established", 500),
                ))
            except EnvironmentError as e:
                logger.warning(f"Skipping GitHub: {e}")

        if sources.get("reddit", {}).get("enabled"):
            try:
                collectors.append(RedditCollector(
                    client_id=get_env("REDDIT_CLIENT_ID"),
                    client_secret=get_env("REDDIT_CLIENT_SECRET"),
                    user_agent=os.environ.get("REDDIT_USER_AGENT", "trending-bot/1.0"),
                    subreddits=sources["reddit"].get("subreddits"),
                ))
            except EnvironmentError:
                logger.warning("Reddit API credentials not found, using public JSON API fallback")
                collectors.append(RedditPublicCollector(
                    user_agent=os.environ.get("REDDIT_USER_AGENT", "trending-bot/1.0"),
                    subreddits=sources["reddit"].get("subreddits"),
                ))

        if sources.get("arxiv", {}).get("enabled"):
            collectors.append(ArxivCollector(categories=sources["arxiv"].get("categories")))

        if sources.get("huggingface", {}).get("enabled"):
            collectors.append(HuggingFaceCollector())

        if sources.get("twitter", {}).get("enabled"):
            fallback = sources["twitter"].get("fallback_to_rss", True)
            collectors.append(TwitterCollector(fallback_to_rss=fallback))

        all_items: list[RawItem] = []
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(c.run, self.data_dir): c for c in collectors}
            for future in as_completed(futures):
                collector = futures[future]
                try:
                    items = future.result()
                    all_items.extend(items)
                    logger.info(f"{collector.source_name}: {len(items)} items")
                except Exception as e:
                    logger.error(f"{collector.source_name} failed: {e}")

        logger.info(f"Total collected: {len(all_items)} items")
        return all_items

    def stage_score(self, raw_items: list[RawItem]) -> tuple[list[ScoredItem], list[ScoredItem]]:
        logger.info("=== Stage 2: Score & Rank ===")
        scoring_cfg = self.config["scoring"]

        # 1. Compute raw momentum per RawItem
        raw_scores: dict[str, float] = {}
        for item in raw_items:
            score = compute_momentum_score(item)
            if item.url not in raw_scores or score > raw_scores[item.url]:
                raw_scores[item.url] = score

        # 2. Normalize within each source (percentile rank)
        normalized = normalize_by_source(raw_items, raw_scores)

        # 3. Deduplicate
        groups = deduplicate(raw_items)

        # 4. Build ScoredItems with normalized scores
        scored_items = []
        for group in groups:
            best_norm = max(normalized.get(item.url, 0) for item in group)
            best_raw = max(raw_scores.get(item.url, 0) for item in group)
            sources = list({item.source for item in group})
            age_hours = 24.0
            final = compute_final_score(
                momentum_score=best_norm,
                age_hours=age_hours,
                freshness_half_life=scoring_cfg["freshness_half_life_hours"],
                num_sources=len(sources),
                boost_config=scoring_cfg["cross_platform_boost"],
            )
            scored_items.append(ScoredItem(
                raw_items=group,
                momentum_score=best_raw,
                normalized_score=best_norm,
                final_score=final,
                sources=sources,
                category="",
                llm_summary="",
                interest_score=0,
            ))

        min_score = scoring_cfg["min_momentum_score"]
        scored_items = [s for s in scored_items if s.momentum_score >= min_score]

        # 5. Diverse top-30 selection (round-robin across sources)
        top_items = select_diverse_top(scored_items, count=30)
        digest, deep_dives = run_llm_filter(
            top_items,
            digest_size=scoring_cfg["digest_size"],
            deep_dive_count=scoring_cfg["deep_dive_count"],
        )

        scored_dir = self.data_dir / "scored"
        scored_dir.mkdir(parents=True, exist_ok=True)
        ranked_path = scored_dir / "ranked.json"
        ranked_path.write_text(json.dumps([s.to_dict() for s in digest], indent=2))

        logger.info(f"Digest: {len(digest)} items, Deep dives: {len(deep_dives)}")
        return digest, deep_dives

    def stage_analyze(self, deep_dive_items: list[ScoredItem]):
        logger.info("=== Stage 3: Deep Dive ===")
        if not deep_dive_items:
            logger.info("No items flagged for deep dive")
            return []
        return run_deep_dives(deep_dive_items, self.data_dir)

    def stage_report(self, digest, reports):
        logger.info("=== Stage 4: Report ===")
        build_digest(digest, reports, self.data_dir, self.date_str)
        build_summary(digest, reports, self.data_dir, self.date_str)
        delivery_cfg = self.config.get("delivery", {})
        if delivery_cfg.get("dashboard", {}).get("enabled"):
            build_dashboard(digest, reports, self.data_dir, self.date_str)

    def stage_deliver(self, digest, reports):
        logger.info("=== Stage 5: Deliver ===")
        delivery_cfg = self.config.get("delivery", {})
        if delivery_cfg.get("telegram", {}).get("enabled"):
            try:
                bot_token = get_env("TELEGRAM_BOT_TOKEN")
                chat_id = get_env("TELEGRAM_CHAT_ID")
                dashboard_url = ""
                if delivery_cfg.get("dashboard", {}).get("enabled"):
                    port = delivery_cfg["dashboard"].get("port", 8080)
                    dashboard_url = f"http://localhost:{port}"
                msg = format_telegram_message(digest, reports, self.date_str, dashboard_url)
                send_telegram_message(msg, bot_token, chat_id)
            except Exception as e:
                logger.error(f"Telegram delivery failed: {e}")

    def run(self, stage: str | None = None):
        try:
            if stage == "collect" or stage is None:
                raw_items = self.stage_collect()
                if stage == "collect":
                    return

            if stage == "score" or stage is None:
                if stage == "score":
                    raw_items = self._load_raw_items()
                digest, deep_dives = self.stage_score(raw_items)
                if stage == "score":
                    return

            if stage == "analyze" or stage is None:
                if stage == "analyze":
                    deep_dives = self._load_deep_dive_items()
                reports = self.stage_analyze(deep_dives)
                if stage == "analyze":
                    return

            if stage == "report" or stage is None:
                if stage == "report":
                    digest = self._load_digest()
                    reports = self._load_reports()
                self.stage_report(digest, reports)
                if stage == "report":
                    return

            if stage == "deliver" or stage is None:
                if stage == "deliver":
                    digest = self._load_digest()
                    reports = self._load_reports()
                self.stage_deliver(digest, reports)

            logger.info("Pipeline completed successfully")

        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            self._notify_error(str(e))
            raise

    def _load_raw_items(self) -> list[RawItem]:
        raw_dir = self.data_dir / "raw"
        items = []
        for f in raw_dir.glob("*.json"):
            data = json.loads(f.read_text())
            items.extend(RawItem.from_dict(d) for d in data)
        return items

    def _load_deep_dive_items(self) -> list[ScoredItem]:
        ranked_path = self.data_dir / "scored" / "ranked.json"
        if ranked_path.exists():
            data = json.loads(ranked_path.read_text())
            count = self.config["scoring"]["deep_dive_count"]
            items = []
            for d in data[:count]:
                raw_items = [RawItem.from_dict(r) for r in d.get("raw_items", [])]
                items.append(ScoredItem(
                    raw_items=raw_items, momentum_score=d["momentum_score"],
                    final_score=d["final_score"], sources=d["sources"],
                    category=d.get("category", ""), llm_summary=d.get("llm_summary", ""),
                    interest_score=d.get("interest_score", 0),
                ))
            return items
        return []

    def _load_digest(self) -> list[ScoredItem]:
        return self._load_deep_dive_items()

    def _load_reports(self):
        from models import AnalysisReport
        reports = []
        analysis_dir = self.data_dir / "analysis"
        if analysis_dir.exists():
            for f in analysis_dir.glob("*.json"):
                data = json.loads(f.read_text())
                reports.append(AnalysisReport(**data))
        return reports

    def _notify_error(self, error_msg: str):
        delivery_cfg = self.config.get("delivery", {})
        if delivery_cfg.get("telegram", {}).get("enabled"):
            try:
                bot_token = get_env("TELEGRAM_BOT_TOKEN")
                chat_id = get_env("TELEGRAM_CHAT_ID")
                send_error_notification(error_msg, bot_token, chat_id)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="AI Trending Bot")
    parser.add_argument("--stage", choices=["collect", "score", "analyze", "report", "deliver"],
                        help="Run a single stage")
    parser.add_argument("--date", help="Date to process (YYYY-MM-DD)")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    args = parser.parse_args()

    config = load_config(args.config)
    pipeline = Pipeline(config=config, date_str=args.date)
    pipeline.run(stage=args.stage)


if __name__ == "__main__":
    main()
