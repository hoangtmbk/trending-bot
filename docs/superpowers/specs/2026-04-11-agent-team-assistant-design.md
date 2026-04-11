# TrendBot Agent Team Architecture — Design Spec

**Date**: 2026-04-11
**Status**: Approved
**Scope**: Refactor trending-bot from a batch cron pipeline into a personal AI assistant built as a team of specialized agents.

---

## 1. Vision

Transform the current nightly scan-and-deliver pipeline into a **personal intelligence platform** — a team of AI agents that continuously monitors, tracks, researches, and filters the AI/ML landscape on your behalf.

**From**: A daily newsletter you read passively.
**To**: A professional assistant team that works around the clock, learns your interests, answers your questions, and connects the dots across days and sources.

### Key Shifts

| Today | Target |
|-------|--------|
| Batch cron (once daily at 2 AM) | Continuous — scouts every 4-12h, analysts reactive, researchers on-demand |
| Flat files, no memory across runs | SQLite knowledge base with full history |
| Telegram push-only | Bidirectional — commands, questions, inline feedback |
| Static HTML dashboard | Live FastAPI web app with search, timelines, graphs |
| Scores by momentum only | Personal relevance scoring that learns from your behavior |
| Items exist in isolation | Knowledge graph connecting related items across sources and days |
| Fixed scope (6 sources, AI only) | Expandable — custom scouts, user-defined topics |

---

## 2. Core Architecture

Single Python application running three long-lived processes:

```
┌──────────────────────────────────────────────────────────┐
│                     python run.py                         │
├──────────────┬───────────────────┬───────────────────────┤
│ Orchestrator │   Telegram Bot    │    Web Server          │
│ (APScheduler │   (python-        │    (FastAPI +          │
│  + Events    │    telegram-bot   │     Uvicorn)           │
│  + Dispatch) │    polling)       │                        │
├──────────────┴───────────────────┴───────────────────────┤
│                    Shared SQLite DB                        │
└──────────────────────────────────────────────────────────┘
```

Runs on local machine as a systemd service (or tmux/screen). Claude CLI (subscription) for all LLM calls.

### Project Structure

```
trending-bot/
├── run.py                    # Entry point — starts orchestrator + web + telegram
├── config.yaml               # All configuration
├── models.py                 # Data models (evolved from today)
├── claude_cli.py             # Claude CLI wrapper (kept, enhanced)
├── db/
│   ├── schema.sql            # SQLite schema
│   ├── database.py           # Connection pool, migrations
│   └── queries.py            # Named query functions
├── agents/
│   ├── base.py               # BaseAgent with schedule, run(), logging
│   ├── scouts/               # One per source (refactored from collectors/)
│   │   ├── github.py
│   │   ├── reddit.py
│   │   ├── arxiv.py
│   │   ├── huggingface.py
│   │   ├── hackernews.py
│   │   └── twitter.py
│   ├── analysts/
│   │   ├── scorer.py         # Momentum + normalization + dedup
│   │   ├── filter.py         # LLM relevance filter
│   │   ├── relevance.py      # Personal interest scoring
│   │   └── connector.py      # Cross-item/cross-day dot-connecting
│   └── researchers/
│       ├── deep_diver.py     # On-demand deep analysis
│       ├── topic_tracker.py  # Multi-day topic evolution
│       └── competitor_watch.py
├── orchestrator/
│   ├── scheduler.py          # APScheduler — manages agent run schedules
│   ├── dispatcher.py         # Task queue — dispatches agent work
│   └── events.py             # Event bus — agents communicate via events
├── interfaces/
│   ├── telegram/
│   │   ├── bot.py            # python-telegram-bot with handlers
│   │   ├── commands.py       # /trending, /deepdive, /track, /ask, etc.
│   │   └── formatters.py     # Message formatting
│   └── web/
│       ├── app.py            # FastAPI application
│       ├── routes/           # API endpoints + page routes
│       ├── templates/        # Jinja2 (evolved from today)
│       └── static/
├── memory/
│   ├── knowledge.py          # High-level memory operations
│   ├── interests.py          # User interest profile management
│   └── connections.py        # Relationship tracking between items
├── prompts/                  # All Claude prompt templates (expanded)
├── data/                     # Flat file archive (kept for reports/exports)
└── tests/
```

---

## 3. Data Model (SQLite)

### items — Every item ever discovered

```sql
CREATE TABLE items (
    id              INTEGER PRIMARY KEY,
    url             TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    source          TEXT NOT NULL,
    source_id       TEXT,
    first_seen      DATETIME NOT NULL,
    last_seen       DATETIME NOT NULL,
    times_seen      INTEGER DEFAULT 1,
    raw_metrics     JSON,
    momentum_score  REAL,
    normalized_score REAL,
    status          TEXT DEFAULT 'new'  -- new, tracking, archived, dismissed
);
CREATE INDEX idx_items_source ON items(source);
CREATE INDEX idx_items_status ON items(status);
CREATE INDEX idx_items_last_seen ON items(last_seen);
CREATE INDEX idx_items_normalized_score ON items(normalized_score);
```

### item_scores — Score time series

```sql
CREATE TABLE item_scores (
    id              INTEGER PRIMARY KEY,
    item_id         INTEGER REFERENCES items(id),
    recorded_at     DATETIME NOT NULL,
    momentum_score  REAL,
    normalized_score REAL,
    raw_metrics     JSON
);
CREATE INDEX idx_item_scores_item_id ON item_scores(item_id);
CREATE INDEX idx_item_scores_recorded_at ON item_scores(recorded_at);
```

### item_analysis — All LLM-generated analysis

```sql
CREATE TABLE item_analysis (
    id              INTEGER PRIMARY KEY,
    item_id         INTEGER REFERENCES items(id),
    analysis_type   TEXT NOT NULL,   -- filter, deep_dive, connection
    created_at      DATETIME NOT NULL,
    content         JSON NOT NULL,
    prompt_version  TEXT
);
CREATE INDEX idx_item_analysis_item_id ON item_analysis(item_id);
CREATE INDEX idx_item_analysis_type ON item_analysis(analysis_type);
```

### topics — System and user-defined topics

```sql
CREATE TABLE topics (
    id              INTEGER PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,
    description     TEXT,
    source          TEXT DEFAULT 'system',  -- system, user, llm-inferred
    created_at      DATETIME NOT NULL,
    is_active       BOOLEAN DEFAULT 1
);
```

### item_topics — Items belong to topics

```sql
CREATE TABLE item_topics (
    item_id         INTEGER REFERENCES items(id),
    topic_id        INTEGER REFERENCES topics(id),
    confidence      REAL DEFAULT 1.0,
    PRIMARY KEY (item_id, topic_id)
);
```

### user_interests — Personal interest profile

```sql
CREATE TABLE user_interests (
    id              INTEGER PRIMARY KEY,
    topic_id        INTEGER REFERENCES topics(id),
    weight          REAL DEFAULT 1.0,   -- 0.0=muted, 1.0=normal, 2.0=high
    source          TEXT DEFAULT 'explicit',  -- explicit, inferred
    updated_at      DATETIME NOT NULL
);
```

### item_connections — Knowledge graph edges

```sql
CREATE TABLE item_connections (
    id              INTEGER PRIMARY KEY,
    item_a_id       INTEGER REFERENCES items(id),
    item_b_id       INTEGER REFERENCES items(id),
    relationship    TEXT NOT NULL,  -- competes_with, builds_on, same_topic, evolves_from
    description     TEXT,
    created_at      DATETIME NOT NULL
);
CREATE INDEX idx_connections_a ON item_connections(item_a_id);
CREATE INDEX idx_connections_b ON item_connections(item_b_id);
```

### digests — Delivery history

```sql
CREATE TABLE digests (
    id              INTEGER PRIMARY KEY,
    digest_type     TEXT NOT NULL,  -- daily, weekly, on_demand, alert
    created_at      DATETIME NOT NULL,
    content_md      TEXT,
    content_html    TEXT,
    item_ids        JSON
);
```

### user_actions — Feedback loop

```sql
CREATE TABLE user_actions (
    id              INTEGER PRIMARY KEY,
    item_id         INTEGER REFERENCES items(id),
    action          TEXT NOT NULL,  -- bookmarked, dismissed, deep_dive_requested, feedback
    payload         JSON,
    created_at      DATETIME NOT NULL
);
CREATE INDEX idx_user_actions_item_id ON user_actions(item_id);
```

### task_queue — Async agent work

```sql
CREATE TABLE task_queue (
    id              INTEGER PRIMARY KEY,
    agent_type      TEXT NOT NULL,
    payload         JSON NOT NULL,
    status          TEXT DEFAULT 'pending',  -- pending, running, completed, failed
    priority        INTEGER DEFAULT 0,
    created_at      DATETIME NOT NULL,
    started_at      DATETIME,
    completed_at    DATETIME,
    result          JSON,
    error           TEXT
);
CREATE INDEX idx_task_queue_status ON task_queue(status);
```

### Design Decisions

- **`items` is append-and-update**: `first_seen`/`last_seen`/`times_seen` give multi-day tracking. Scouts upsert by URL — existing items get updated, not duplicated.
- **`item_scores` is a time series**: Enables "gained 2,000 stars in 3 days" and sparkline charts.
- **`item_analysis` stores all LLM outputs**: Keyed by type, so one item can have filter + deep_dive + connection analyses.
- **`user_interests` + `item_topics`**: Personal relevance = dot product of item topic weights and user interest weights.
- **`user_actions`**: Closes the feedback loop. Actions feed back into interest weights over time.
- **`task_queue`**: Simple in-process queue. User says "deep dive this" → task created → dispatcher runs it → notification when done.

---

## 4. Agent System

### BaseAgent

```python
class BaseAgent:
    name: str
    schedule: str          # cron expression or "on_demand"
    timeout: int           # max seconds per run
    
    def run(context) -> AgentResult
    def on_event(event) -> None
```

### Scout Agents (Data Collection)

Refactored from current `collectors/`. Same API/parsing logic, but write to SQLite and update existing items.

| Agent | Schedule | Changes from Today |
|-------|----------|--------------------|
| GitHub Scout | Every 4h | Upserts by URL. Snapshots star counts to `item_scores`. |
| Reddit Scout | Every 4h | Upserts. Snapshots upvotes/comments. |
| arXiv Scout | Every 12h | Papers change slowly. Snapshots citation counts. |
| HuggingFace Scout | Every 6h | Snapshots downloads/likes. |
| HN Scout | Every 4h | Snapshots points/comments. |
| Twitter Scout | Every 4h | Needs actual implementation (currently dead stubs). |
| Custom Scout | Configurable | New: user adds RSS feeds, repos, keywords. |

**Event emitted**: `items_updated(source, count, new_count)`

### Analyst Agents (Thinking)

Run reactively — triggered by scout events.

**Trend Scorer**: Reuses current momentum formulas. Now uses actual `first_seen`/`last_seen` timestamps instead of hardcoded 24h. Writes to `item_scores`.

**Relevance Filter**: LLM filter (like today) enhanced with user interest context in prompt. Assigns topics to items. Computes personal relevance score.

**Dot Connector**: Daily. Queries items from last 7 days, asks Claude to identify relationships (competes_with, builds_on, same_topic, evolves_from). Writes to `item_connections`.

**Event emitted**: `analysis_complete(digest_items, alerts)`

### Researcher Agents (Deep Work)

Run on-demand (user request or analyst flag).

**Deep Diver**: Same as today's deep dive. Triggered by user command or analyst flag. Stores to `item_analysis`. Can handle follow-up questions.

**Topic Tracker**: Tracks topics over time. Weekly reports on trajectory (accelerating, plateauing, fragmenting). Stores to `item_analysis(type='topic_report')`.

**Competitor Watcher**: When user bookmarks an item, watches its competitors. Weekly comparative reports.

### Agent Communication

In-process event bus (Python asyncio). No external message broker.

```
Scout finishes → items_updated
  → Scorer runs → scores_updated
    → Filter runs → analysis_complete
      → High priority? → Telegram alert
      → Digest time? → Digest delivery

User: /deepdive {url} → task_queue entry
  → Dispatcher → Deep Diver runs
    → research_complete → Telegram reply
```

---

## 5. Interfaces

### Telegram Bot (Bidirectional)

`python-telegram-bot` with polling. Primary mobile interface.

**Commands:**

| Command | Action |
|---------|--------|
| `/trending` | Today's top items by personal relevance |
| `/trending <topic>` | Filtered to a topic |
| `/deepdive <url or #id>` | Queue deep dive, notify when ready |
| `/track <topic>` | Start tracking a topic |
| `/untrack <topic>` | Stop tracking |
| `/topics` | List active topics with item counts |
| `/ask <question>` | Free-form Q&A using knowledge base as context |
| `/weekly` | On-demand weekly summary |
| `/status` | System health |
| `/settings` | Adjust preferences |

**Inline keyboards on items:**
```
Bookmark | Deep Dive | Not Relevant | Track Topic
```

Actions write to `user_actions`, feed back into interest weights.

**Proactive alerts:**
- Breaking items (high score + matches high-weight interest) → immediate push
- Daily digest (configurable time, default 8:00 AM)
- Weekly summary (Monday morning)
- Research complete notifications
- Topic update notifications

**Quiet hours**: Configurable, only critical alerts break through.

**Conversation via `/ask`**: Assembles relevant items + analyses from DB into Claude CLI prompt context. Claude answers using your knowledge base, not just training data.

### Web Dashboard (FastAPI + HTMX)

Live application replacing static HTML.

**Pages:**

- **/** — Dashboard: today's top items, sparkline score charts, filter/sort/search
- **/item/{id}** — Detail: analysis, score history, related items, actions, notes
- **/topics** — Topic explorer: item counts, trend direction, timeline, weight management
- **/connections** — Network graph of item relationships, filterable
- **/digests** — Archive of all past digests, searchable
- **/settings** — Interests, schedules, sources, alerts, custom scouts

**API endpoints** (shared by Telegram and Web):

```
GET  /api/items?topic=&source=&since=&limit=
GET  /api/items/{id}
GET  /api/items/{id}/analysis
POST /api/items/{id}/action
POST /api/research/deepdive
GET  /api/topics
POST /api/topics
GET  /api/topics/{id}/timeline
GET  /api/connections?item_id=
GET  /api/digests
POST /api/ask
```

Both interfaces are thin clients over the same API. Future interfaces (CLI, mobile, browser extension) plug in the same way.

---

## 6. Memory & Learning System

### Layer 1 — Item Memory (automatic)

Every item lives in SQLite permanently. Enables:
- Multi-day trending detection (`times_seen`, `first_seen`/`last_seen`)
- Metric trajectory ("stars grew from 200 to 3,400 this week") via `item_scores`
- Cross-run deduplication (URL exists in DB = update, not create)
- Historical recall ("you saw this last Tuesday") via `digests` + `item_ids`

### Layer 2 — Interest Profile (explicit + inferred)

Weighted topic map evolving from two sources:

**Explicit signals:**
- `/track` → weight 2.0
- Bookmark → topic boost +0.2
- Dismiss → topic decay -0.1
- Direct weight adjustment in `/settings`

**Inferred signals (weekly, Claude-driven):**
- Claude reviews last 7 days of `user_actions`
- Suggests interest adjustments based on behavior patterns
- Capped at ±0.3 per week to prevent runaway drift
- Stored with `source='inferred'`, user can see and override

### Layer 3 — Knowledge Graph (LLM-built)

Dot Connector builds relationship map over time via `item_connections`:
- `evolves_from`, `builds_on`, `competes_with`, `same_topic`
- Accumulates over weeks/months
- Subgraph context injected into `/ask` answers and deep dives

### Personal Relevance Scoring

```
final_score = momentum_score
            * freshness_decay
            * cross_platform_boost
            * personal_relevance

personal_relevance = max(topic_weights for item's topics)
                   * recency_bonus
                   * engagement_bonus
```

Items in muted topics (weight=0) still collected and stored, just ranked at bottom. Nothing is lost.

### Feedback Loop

```
User interacts (bookmark/dismiss/ask/track)
  → user_actions table
  → Weekly: Interest Adjuster reviews actions
  → user_interests weights updated (conservatively)
  → Next run: Relevance Filter uses updated weights
  → Better-ranked items
  → User interacts → cycle continues
```

---

## 7. Code Reuse Map

| Current Code | Fate | Notes |
|---|---|---|
| `collectors/*.py` | **Keep ~80%** | Refactor into `agents/scouts/`. Core API/parsing stays. Remove file I/O, add DB writes. |
| `scoring/momentum.py` | **Keep 90%** | Velocity formulas and normalization are solid. Fix hardcoded `age_hours=24`. |
| `scoring/dedup.py` | **Keep, enhance** | Add cross-run dedup via DB lookup. |
| `scoring/llm_filter.py` | **Keep 70%** | Add user interest context to prompt. Add topic assignment. |
| `analysis/gatherer.py` | **Keep 90%** | Source material fetching reused by Deep Diver. |
| `analysis/deep_dive.py` | **Keep 80%** | Stores to DB instead of flat files. Triggerable on-demand. |
| `reporting/digest.py` | **Rewrite** | Queries DB, not flat files. New structure with topic grouping and trend indicators. |
| `reporting/summary.py` | **Keep 70%** | Richer context from DB (multi-day trends, connections). |
| `reporting/dashboard.py` | **Replace** | Static generator → FastAPI app. |
| `delivery/telegram.py` | **Rewrite** | One-way sender → full bot with handlers and commands. |
| `models.py` | **Evolve** | Add DB-backed models, API response models. |
| `claude_cli.py` | **Keep, enhance** | Add context assembly (interests, knowledge graph). |
| `config.yaml` | **Expand** | Add agent schedules, alert thresholds, quiet hours, web config. |
| `prompts/*.md` | **Keep + expand** | 3 existing prompts evolve. Add ~5 new prompts. |
| `run.py` | **Rewrite** | Pipeline → app entry point (scheduler + bot + web). |
| `data/` | **Keep as archive** | Historical files remain. New data goes to SQLite. |
| `tests/` | **Keep + expand** | Adapt existing, add tests for DB, agents, API, Telegram. |

**Overall reuse: ~60% of current codebase logic preserved.**

---

## 8. Migration Phases

Each phase produces a working system. Safe to stop at any phase.

### Phase 1 — Foundation
SQLite schema + DB layer + BaseAgent + orchestrator skeleton.
No user-visible change. Current pipeline continues working.

### Phase 2 — Scout Migration
Move collectors into agent framework. Scouts write to DB. Run on staggered schedules.
Current flat-file pipeline kept in parallel during transition.

### Phase 3 — Analyst Migration
Scorer, filter, dedup work from DB. Cross-day memory comes alive.
Daily digest now generated from DB queries.

### Phase 4 — Telegram Bot
Bidirectional. Commands, inline actions, alerts.
First time it *feels* like an assistant.

### Phase 5 — Researchers
Deep diver on-demand, topic tracker, competitor watcher.
The "team" grows to full capability.

### Phase 6 — Web Dashboard
FastAPI app replaces static HTML. Search, timelines, connection graphs.

### Phase 7 — Learning System
Interest profile, feedback loop, inferred adjustments.
The assistant becomes personal.

---

## 9. Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| LLM | Claude CLI (subscription) |
| Database | SQLite (via `sqlite3` stdlib, consider `aiosqlite` for async) |
| Scheduler | APScheduler 3.x |
| Event bus | In-process (Python asyncio or simple pub/sub) |
| Telegram | `python-telegram-bot` v20+ (async) |
| Web framework | FastAPI + Uvicorn |
| Web interactivity | HTMX (no JS framework) |
| Templates | Jinja2 |
| Graph visualization | D3.js or vis.js (for connections page) |
| Testing | pytest |
| Process management | systemd or tmux/screen |

---

## 10. New Prompt Templates Needed

| Prompt | Used By | Input | Output |
|--------|---------|-------|--------|
| `prompts/filter.md` (enhanced) | Relevance Filter | Items + user interests | Scored/categorized items with topics |
| `prompts/deep_dive.md` (enhanced) | Deep Diver | Item + source material + related items | Structured analysis JSON |
| `prompts/summary.md` (enhanced) | Digest/Weekly | Items + multi-day trends + connections | Markdown summary |
| `prompts/dot_connector.md` (new) | Dot Connector | Recent items batch | Relationship pairs with explanations |
| `prompts/topic_report.md` (new) | Topic Tracker | Topic + items over 7 days | Trajectory analysis |
| `prompts/interest_adjuster.md` (new) | Learning System | User actions + current weights | Weight adjustment suggestions |
| `prompts/ask.md` (new) | /ask command | Question + relevant items/analyses | Free-form answer |
| `prompts/competitor_report.md` (new) | Competitor Watcher | Item + competitors + changes | Comparative report |
