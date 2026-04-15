# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Always-on personal AI-trends assistant. A single `main.py` process runs
an APScheduler-driven orchestrator, a FastAPI dashboard, and a
bidirectional Telegram bot; agents (scouts/analysts/researchers) fire
on their own cron schedules and persist to `trendbot.db`. Canonical
runtime is a Docker container on `lab-cam-Precision-3630-Tower`
(192.168.1.10). The older `run.py` batch pipeline is retained for
reference but is no longer scheduled.

## Commands

```bash
# Local dev (laptop)
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in API keys
python main.py         # orchestrator + dashboard + telegram
python main.py --no-telegram --run-now   # dry-run a collection cycle

# Tests
pytest tests/
pytest tests/test_web.py -v           # single file
pytest tests/test_web.py::TestApiHealth -v   # single class

# Production deploy (lab-cam, 192.168.1.10)
ssh 192.168.1.10
cd ~/workspace/trending-bot && git pull
cd deploy && docker compose build && docker compose up -d
docker compose logs -f trending-bot --tail 50

# Legacy (not scheduled, kept for reproducing old reports)
python run.py --stage collect
python run.py --date 2026-04-08
```

## Architecture

**Two parallel architectures live in this repo.** `main.py` (the canonical
always-on orchestrator) and `run.py` (the legacy 5-stage batch pipeline)
share the same collectors, scoring, and `claude_cli.py` module but have
different data stores — `main.py` uses SQLite (`trendbot.db`), `run.py`
uses date-partitioned JSON under `data/YYYY-MM-DD/`. New work should
target `main.py` and its agent model. `run.py` is documented below for
reference.

**5-stage sequential pipeline**, each stage reads from disk and writes output for the next:

```
COLLECT → SCORE & RANK → DEEP DIVE → REPORT → DELIVER
```

All data is date-partitioned under `data/YYYY-MM-DD/` with subdirectories: `raw/`, `scored/`, `analysis/`, `reports/`.

### Entry point: `run.py`
`Pipeline` class orchestrates all stages. Supports running individual stages via `--stage` flag, re-loading intermediate data from disk.

### Stage 1 — Collect (`collectors/`)
6 collectors run in parallel via `ThreadPoolExecutor(max_workers=6)`. Each extends `BaseCollector` from `collectors/base.py`. Individual collector failures are logged but don't stop the pipeline. Reddit has a fallback: `RedditCollector` (PRAW OAuth) falls back to `RedditPublicCollector` (public JSON API). Twitter uses Playwright headless browser with RSS fallback.

### Stage 2 — Score & Rank (`scoring/`)
- `momentum.py`: Per-source velocity formulas (star velocity, upvote rate, citation count, etc.) + normalization to 0-100 percentile rank per source + final score with freshness decay and cross-platform boost
- `dedup.py`: Merges cross-platform duplicates via exact URL matching and fuzzy title matching (thefuzz, threshold 75%)
- `llm_filter.py`: Sends top ~30 items to Claude CLI in one batch call for quality filtering, categorization, and deep-dive flagging
- `run.py:select_diverse_top()`: Round-robin source interleaving before LLM filter

### Stage 3 — Deep Dive (`analysis/`)
- `gatherer.py`: Fetches README/abstract/thread content + competitor search
- `deep_dive.py`: Orchestrates Claude CLI analysis per item (3-5 in parallel). Produces structured JSON + markdown per item.

### Stage 4 — Report (`reporting/`)
- `digest.py`: Markdown digest grouped by category
- `summary.py`: Claude CLI executive summary (with plain-text fallback)
- `dashboard.py`: Static HTML via Jinja2 templates from `templates/`

### Stage 5 — Deliver (`delivery/`)
- `telegram.py`: Formatted message via Telegram Bot API. Also used for error notifications.
- `server.py`: Simple HTTP server for the dashboard

### Key shared modules
- `models.py`: `RawItem`, `ScoredItem`, `AnalysisReport` dataclasses. `ScoredItem.raw_items` holds the deduplicated group of `RawItem`s.
- `config.py`: Loads `config.yaml` + `.env`. `get_env()` raises on missing required vars.
- `claude_cli.py`: Wraps `claude -p` CLI. `call_claude()` returns string, `call_claude_json()` parses JSON (strips markdown fences). Requires `claude` command in PATH.
- `prompts/`: Markdown templates for the 3 LLM touchpoints (filter, deep_dive, summary).

## Configuration

- `config.yaml`: Source toggles, scoring parameters (boost multipliers, freshness half-life, digest/deep-dive counts), delivery settings
- `.env`: API keys — `GITHUB_TOKEN`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

## Scoring formula

```
final_score = normalized_momentum * exp(-age_hours / half_life) * cross_platform_boost
```

Cross-platform boost: 2 sources = 1.5x, 3 = 2.5x, 4+ = 4.0x (configurable in `config.yaml`).

## Conventions

- Commits follow conventional style: `feat:`, `fix:`, `chore:`, `docs:`
- Python 3.11+, no linter or formatter configured
- Tests use pytest with fixtures in `tests/conftest.py`
- Claude CLI is the only LLM interface (no direct API calls) — used at exactly 3 points: LLM filter, deep dive analysis, executive summary
