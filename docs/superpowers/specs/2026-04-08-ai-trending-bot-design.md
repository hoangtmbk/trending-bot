# AI Trending Bot — Design Spec

## Overview

A nightly bot that scans multiple platforms for rising AI-related projects, papers, and discussions, then uses Claude CLI to filter, analyze, and generate actionable reports with deep-dive analysis and solution proposals.

**Runs at:** 2:00 AM daily via cron
**Output:** Markdown files + static web dashboard + Telegram summary
**AI layer:** Claude CLI (linked to user's subscription)

## Architecture

Pipeline architecture with 5 sequential stages. Each stage reads from the previous stage's output (JSON/markdown files on disk). All data is date-partitioned under `data/YYYY-MM-DD/`.

```
COLLECT → SCORE & RANK → DEEP DIVE → REPORT → DELIVER
```

### Why Pipeline

- Simple to build, debug, and extend
- Each stage independently testable and re-runnable
- Claude CLI used surgically (3 touchpoints), keeping token costs predictable
- Files on disk = full auditability and historical data

## Stage 1: Data Collection

Six data sources, all collectors run in parallel:

### GitHub
- **API:** GitHub REST API (personal access token for rate limits)
- **What:** Trending repos + search for AI-related repos by topic tags
- **Signals:** Star velocity (24h/7d), fork count growth, project age, topic tags
- **AI topic filter:** Tags including ai, llm, machine-learning, deep-learning, neural-network, transformer, gpt, langchain, agents, rag, computer-vision, nlp, reinforcement-learning

### Reddit
- **API:** Reddit OAuth API (free tier)
- **Subreddits:** r/MachineLearning, r/LocalLLaMA, r/artificial, r/ChatGPT, r/singularity, r/StableDiffusion
- **Signals:** Upvote ratio + velocity, comment count, award count, cross-post frequency

### arXiv + Semantic Scholar
- **API:** arXiv API (free) + Semantic Scholar API (free)
- **Categories:** cs.AI, cs.CL, cs.CV, cs.LG, cs.MA, stat.ML
- **Signals:** Citation velocity (via Semantic Scholar), social media mentions, author h-index, institutional affiliation

### HuggingFace
- **API:** HuggingFace Hub API (free)
- **What:** Trending models, datasets, spaces + daily papers
- **Signals:** Download count velocity, like count growth, daily papers upvotes, space demo popularity

### X / Twitter
- **Method:** Scraping (API pricing prohibitive)
- **Strategy:** Monitor curated list of AI influencers + trending AI hashtags via headless browser
- **Signals:** Retweet/like velocity, quote tweet ratio, thread engagement, influencer amplification
- **Fallback:** RSS aggregators if scraping breaks
- **Note:** Most fragile source — designed to be gracefully skippable

### Hacker News
- **API:** HN Algolia API (free, no auth)
- **What:** Top/new stories filtered for AI topics
- **Signals:** Point velocity, comment count, front page duration

### Collector Interface

All collectors implement a base interface:
- `collect() -> list[RawItem]` — fetch and return raw items
- Each `RawItem` contains: title, url, source, description, raw metrics, timestamp
- Output: `data/YYYY-MM-DD/raw/{source}.json`

## Stage 2: Scoring & Ranking

Three-step process:

### 2a. Momentum Scoring

Per-source velocity formulas:
- GitHub: `stars_24h / max(total_stars, 100)`
- Reddit: `upvotes / hours_since_post`
- arXiv: `citations_7d + social_mentions`
- HuggingFace: `downloads_24h / max(total_downloads, 100)`
- X: `(retweets + quotes) / hours`
- HN: `points / hours_since_post`

Final score formula:
```
final_score = momentum_score × freshness_decay × cross_platform_boost
```

- **Freshness decay:** `exp(-age_hours / 48)` — items older than 2 days decay significantly
- **Cross-platform boost:** 2 sources = 1.5×, 3 sources = 2.5×, 4+ sources = 4.0×

### 2b. Cross-Source Deduplication

URL matching + fuzzy title matching to merge items appearing on multiple platforms. Merged items accumulate signals from all sources.

### 2c. Claude CLI Quality Filter

Top ~30 items by momentum score are passed to Claude CLI in a single batch call. Claude evaluates each item for:
- **Novelty:** Is it genuinely new? (not a minor fork, wrapper, or tutorial)
- **AI relevance:** Filter false positives from keyword matching
- **Category:** tool, model, paper, framework, dataset, technique, product
- **Interest score:** 1-10 based on potential impact
- **One-line summary:** What it is and why it matters

Output: ranked list of 10-15 items for the digest, top 3-5 flagged for deep dive.

Claude CLI invocation: `claude -p "<prompt with items JSON>" --output-format json`

Output: `data/YYYY-MM-DD/scored/ranked.json`

## Stage 3: Deep Dive Analysis

Each item flagged for deep dive gets its own Claude CLI session (3-5 items, run in parallel).

### Research Phase

Two-step process per item:

**Step A — Python gathers source material:**
1. Fetch the repo README / paper abstract / thread content via API
2. Fetch top comments from Reddit/HN discussions (if the item appeared there)
3. Search GitHub/web for similar projects (competitor discovery)

**Step B — Claude CLI analyzes the gathered material:**
All fetched content is passed to Claude CLI as prompt context. Claude then:
1. Analyzes the project/paper's core approach and key code/methodology
2. Identifies the pain point and why it matters
3. Evaluates competitors found in Step A
4. Identifies gaps and proposes a concrete solution

### Deep Dive Report Structure (per item)

Each report is saved as `data/YYYY-MM-DD/analysis/{item-slug}.md` with:

- **What it is** — clear explanation of the project/paper/tool
- **Why it's trending** — what triggered community interest
- **Pain point** — the underlying problem it addresses
- **Gap analysis** — what's missing, what could be better, unmet needs
- **Competitors** — existing solutions and how they compare
- **App/solution idea** — a concrete product or tool proposal addressing the identified gaps
- **Feasibility** — estimated effort (days/weeks), market viability, competition level

Claude CLI invocation: `claude -p "<prompt with item context>" --output-format json`

## Stage 4: Report Generation

### Daily Digest (digest.md)
Markdown file listing all 10-15 items with:
- Title, source badges, score
- One-line summary
- Link to deep dive (if available)
- Grouped by category (tools, papers, discussions, models)

### Executive Summary (summary.md)
Claude CLI generates a brief narrative summary:
- Top themes of the day
- Most promising opportunities
- Notable patterns or emerging trends

### Static Dashboard (dashboard/)
Jinja-templated HTML generated from the daily data:
- Left panel: scored digest with source badges and interest scores
- Right panel: deep dive viewer (click any deep-dive item to read the analysis)
- Date navigation (browse previous days)
- Client-side search across items and deep dives
- No framework — vanilla HTML/CSS/JS

## Stage 5: Delivery

### Telegram
- Bot sends a formatted summary message via Telegram Bot API
- Contains: date, item count, top pick with opportunity highlight, one-liner per source category, link to dashboard
- Also sends error notifications if any pipeline stage fails

### Markdown Files
- All files already written to `data/YYYY-MM-DD/` during previous stages
- These serve as the permanent archive

### Dashboard
- Generated HTML copied/served from a persistent location
- Simple Python HTTP server (`python -m http.server 8080`) or nginx for serving
- Auto-updates each night when new report is generated

## Project Structure

```
trending-bot/
├── run.py                         # Main entry — orchestrates the pipeline
├── config.yaml                    # Sources, thresholds, schedule config
├── requirements.txt
├── .env                           # Secrets (API keys, tokens)
│
├── collectors/                    # Stage 1
│   ├── __init__.py
│   ├── base.py                    # Base collector interface
│   ├── github.py
│   ├── reddit.py
│   ├── arxiv.py
│   ├── huggingface.py
│   ├── twitter.py
│   └── hackernews.py
│
├── scoring/                       # Stage 2
│   ├── __init__.py
│   ├── momentum.py                # Momentum score calculation
│   ├── dedup.py                   # Cross-source deduplication
│   └── llm_filter.py              # Claude CLI quality filter
│
├── analysis/                      # Stage 3
│   ├── __init__.py
│   └── deep_dive.py               # Claude CLI deep dive orchestrator
│
├── reporting/                     # Stage 4
│   ├── __init__.py
│   ├── digest.py                  # Markdown digest builder
│   ├── dashboard.py               # Static HTML dashboard generator
│   └── summary.py                 # Claude CLI executive summary
│
├── delivery/                      # Stage 5
│   ├── __init__.py
│   ├── telegram.py                # Telegram bot sender
│   └── server.py                  # Simple HTTP server for dashboard
│
├── prompts/                       # Claude CLI prompt templates
│   ├── filter.md                  # Scoring/filter prompt
│   ├── deep_dive.md               # Deep dive analysis prompt
│   └── summary.md                 # Executive summary prompt
│
├── templates/                     # Dashboard HTML/Jinja templates
│   ├── index.html
│   ├── item.html
│   └── assets/
│
├── data/                          # Output (date-partitioned, gitignored)
│   └── YYYY-MM-DD/
│       ├── raw/*.json
│       ├── scored/ranked.json
│       ├── analysis/*.md
│       ├── reports/
│       │   ├── digest.md
│       │   ├── summary.md
│       │   └── dashboard/
│       └── pipeline.log
│
└── tests/
    ├── test_collectors.py
    ├── test_scoring.py
    └── test_dedup.py
```

## Configuration (config.yaml)

```yaml
schedule:
  cron: "0 2 * * *"

scoring:
  digest_size: 15
  deep_dive_count: 5
  min_momentum_score: 0.3
  freshness_half_life_hours: 48
  cross_platform_boost:
    2: 1.5
    3: 2.5
    4: 4.0

sources:
  github:
    enabled: true
    topics:
      - ai
      - llm
      - machine-learning
      - deep-learning
      - transformer
      - agents
      - computer-vision
      - nlp
      - rag
  reddit:
    enabled: true
    subreddits:
      - MachineLearning
      - LocalLLaMA
      - artificial
      - ChatGPT
      - singularity
      - StableDiffusion
  arxiv:
    enabled: true
    categories:
      - cs.AI
      - cs.CL
      - cs.CV
      - cs.LG
      - cs.MA
      - stat.ML
  huggingface:
    enabled: true
  twitter:
    enabled: true
    fallback_to_rss: true
  hackernews:
    enabled: true

delivery:
  telegram:
    enabled: true
  dashboard:
    enabled: true
    port: 8080
```

## Error Handling

- **Collector failure:** Individual collector failures do not stop the pipeline. The failed source is logged and a Telegram notification is sent. Pipeline continues with available sources.
- **Claude CLI failure:** Retry once. If still fails, skip the LLM filter step and use raw momentum scores only. Deep dives that fail are skipped with a note in the report.
- **Logging:** Full pipeline log saved to `data/YYYY-MM-DD/pipeline.log`. Errors also sent via Telegram.
- **Idempotent stages:** Each stage can be re-run independently: `python run.py --stage score --date 2026-04-08`

## Runtime Estimates

| Stage | Duration | Notes |
|-------|----------|-------|
| Collect | ~2-3 min | All 6 collectors in parallel |
| Score & Rank | ~2-3 min | Includes Claude CLI filter call |
| Deep Dive | ~5-10 min | 3-5 items in parallel via Claude CLI |
| Report | ~1-2 min | Includes Claude CLI summary call |
| Deliver | ~10 sec | Telegram API call + file copy |
| **Total** | **~10-18 min** | |

## Dependencies

- Python 3.11+
- Claude CLI (installed, linked to subscription)
- Libraries: requests, praw (Reddit), arxiv, huggingface_hub, beautifulsoup4, playwright (Twitter scraping), python-telegram-bot, jinja2, pyyaml, python-dotenv
- External: Telegram bot (via BotFather), GitHub personal access token, Reddit API app credentials

## Adaptive Behavior

- **Digest size adapts** to daily volume: quiet days produce fewer items (no padding with noise), busy days (e.g., major model release) expand up to the configured max
- **Deep dive count adapts** based on Claude CLI's quality assessment: if only 2 items score above the deep-dive threshold, only 2 get analyzed
- **Source weights are equal by default** but can be tuned in config if one source proves more reliable than others over time
