# Trending-Bot Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three parallel tracks of improvement — (A) fix existing quality/perf regressions so the dashboard surfaces useful items; (B) expand source coverage with high-signal feeds; (C) deepen analysis with topic-aware scoring, org priors, velocity, and a web-search deep-dive.

**Architecture:** All work happens inside the existing `main.py`/agent/SQLite architecture. A new `collectors/rss.py` base handles every new RSS-based source. A `scoring/prior.py` holds org/author priors. Topic weighting hooks into the existing `scoring/momentum.py::compute_final_score`. Dashboard joins `items ⨝ item_analysis` so filter verdicts drive display. Deep-dive uses Claude CLI `--allowedTools WebSearch,WebFetch`.

**Tech Stack:** Python 3.11+, SQLite (schema additions only, no drops), feedparser (new dep), existing APScheduler/FastAPI/Claude CLI stack. pytest.

**Reference:** Review in session `main` April 19 — log analysis and dashboard screenshot identified nine concrete issues.

**Decisions baked in (from review):**
- Reddit stays on public API (no PRAW creds in prod).
- Semantic Scholar unauthenticated tier (100 req / 5 min).
- Migrate live DB `/app/trendbot.db` → mounted volume on deploy.
- Twitter stub deleted (not implemented via Nitter).
- Default blogs: Anthropic, OpenAI, DeepMind, Mistral, Qwen, Meta AI, HuggingFace, Cohere.
- Default newsletters: Import AI, Interconnects, TLDR AI, The Rundown AI.
- TDD applied to logic (debounce, dedup wiring, priors, topic weighting, velocity). Pure plumbing (RSS config, dashboard query tweak) ships without new tests.

---

## File Structure

### Plan A — Quality & Performance

**Modified:**
- `interfaces/web/app.py` — dashboard home and `/api/items` JOIN `item_analysis` and gate on filter verdict.
- `agents/analysts/scorer.py` — batch upserts with one connection + `executemany`; accept coalesced-event count in payload.
- `orchestrator/dispatcher.py` (or wherever `on("items_updated")` lives) — debounce scorer enqueues within a 60s window.
- `scoring/momentum.py` — call `scoring.dedup.merge_duplicates` to produce merged groups before normalization so `num_sources` is real.
- `collectors/arxiv.py` — populate `citation_count` via Semantic Scholar batch lookup.
- `deploy/docker-compose.yml` (or equivalent) — fix DB mount: `/app/trendbot.db` → volume, with on-boot migration if the file is 0 bytes.
- `collectors/twitter.py` — delete.
- `agents/scouts/twitter_scout.py` — delete.
- `config.yaml` — remove `sources.twitter`, remove `orchestrator.agents.twitter_scout`.
- `main.py` — stop registering twitter scout.

**Created:**
- `tests/test_scorer_debounce.py`
- `tests/test_scorer_batch.py`
- `tests/test_dedup_integration.py`
- `scripts/migrate_db_to_volume.py` — one-shot copy from `/app/trendbot.db` → mounted path inside container.

### Plan B — Source expansion

**Created:**
- `collectors/rss.py` — generic `RSSCollector(feed_url, source_name, parser)` base. One file powers blogs + newsletters + HF papers + papers-with-code + Lobsters.
- `collectors/semantic_scholar.py` — reused by arXiv collector *and* as a new batch citation enricher.
- `collectors/github_releases.py` — watches a configured list of repos for release events.
- `agents/scouts/blog_scout.py` — enumerates configured blog feeds.
- `agents/scouts/newsletter_scout.py` — enumerates configured newsletters.
- `agents/scouts/hf_papers_scout.py` — HF Daily Papers via their public JSON.
- `agents/scouts/lobsters_scout.py` — `https://lobste.rs/t/ai.rss`.
- `agents/scouts/papers_with_code_scout.py` — trending endpoint or RSS.
- `agents/scouts/github_releases_scout.py` — the new collector.

**Modified:**
- `config.yaml` — new `sources.blogs.feeds`, `sources.newsletters.feeds`, `sources.hf_papers`, `sources.lobsters`, `sources.papers_with_code`, `sources.github_releases.repos`. New `orchestrator.agents.*_scout` schedules.
- `scoring/momentum.py` — per-source momentum branches for `blog`/`newsletter`/`hf_papers`/`lobsters`/`github_release`.
- `interfaces/web/templates/index.html` — badge colors for new sources.

### Plan C — Analysis depth

**Created:**
- `scoring/prior.py` — `org_prior(url_or_author: str) -> float` returning a multiplier. Config-driven list of trusted orgs.
- `scoring/velocity.py` — topic-velocity computed from `item_topics` + `items.first_seen` over a sliding window.
- `agents/analysts/topic_velocity.py` — agent that runs after filter, materializes a `topic_velocity` row.
- `prompts/deep_dive.md` — rewritten to instruct web-search tool use.
- `claude_cli.py` — `call_claude` gains an `allowed_tools: list[str] | None` passthrough → `--allowedTools WebSearch,WebFetch`.
- `agents/researchers/deep_diver.py` — passes `allowed_tools=["WebSearch","WebFetch"]` when calling Claude.
- `db/schema.sql` — new `topic_velocity` table (id, topic_id, window_hours, item_count, recorded_at). Migration applied on boot.

**Modified:**
- `scoring/momentum.py::compute_final_score` — accepts `topic_weight: float = 1.0` and `org_prior: float = 1.0`; multiplies in.
- `agents/analysts/scorer.py` — looks up each item's dominant topic weight from `user_interests` and org prior from URL; passes to `compute_final_score`.
- `agents/notifiers/digest_pusher.py` — reads `user_interests` and ranks digest picks by topic affinity as a tie-break.
- `interfaces/web/app.py` — `/api/items/{id}/action` with `action=bookmarked` now bumps the matching topic's `user_interests.weight` by +0.1 (capped at 5.0); `action=dismissed` decays by -0.05 (floor 0.1).

**Test files:**
- `tests/test_prior.py`
- `tests/test_velocity.py`
- `tests/test_scorer_topic_weight.py`
- `tests/test_feedback_loop.py`
- `tests/test_rss_collector.py`
- `tests/test_semantic_scholar.py`

---

# Plan A — Quality & Performance

## Task A1: Filter-aware dashboard

**Files:**
- Modify: `interfaces/web/app.py:34-46, 180-186` (API + home)
- Modify: `interfaces/web/templates/index.html` — show `llm_summary` + `interest_score`

**Why:** `items` ordered by `normalized_score DESC` dumps low-signal Reddit noise ("lol", "7 years ago") into the top slots because filter verdicts live in `item_analysis` but are never joined. Screenshot confirms nine items tied at 100 with most being Reddit chatter.

- [ ] Write failing test in `tests/test_web.py` asserting `/api/items` excludes items whose latest `filter` analysis has `ai_relevant=false` or `novel=false`, and includes `summary`/`interest_score` fields.
- [ ] Extend `get_items` or add `get_items_with_latest_filter(db, min_interest=4)` in `db/queries.py` that LEFT JOINs latest `item_analysis` row of type `filter` per item (via subquery `MAX(created_at)`).
- [ ] Update `/api/items` and `page_home` to use the new query; expose `summary`, `interest_score`, `category`.
- [ ] Update `interfaces/web/templates/index.html` to render `summary` under title and replace numeric score with `interest_score/10`. Keep normalized_score as a small meta.
- [ ] Screenshot the new dashboard before commit; confirm "lol" / "7 years ago" are gone.
- [ ] `git add` + commit: `feat(dashboard): surface filter verdicts, hide low-signal items`.

## Task A2: Debounce scorer event-driven runs

**Files:**
- Modify: `orchestrator/dispatcher.py` (event→task handler for `items_updated`)
- Create: `tests/test_scorer_debounce.py`

**Why:** Five scouts fire within ~60s each cron, each emits `items_updated`, each enqueues a scorer. Scorer runs 3-5× back-to-back per cycle, each time rescoring 1,200 items (400–1,200s).

- [ ] Add a `DebounceTimer` class (threading.Timer-based, or a time-check in memory) in `orchestrator/dispatcher.py`. Single pending-scorer flag with 60s window.
- [ ] Replace direct `enqueue_task("scorer")` on `items_updated` with `schedule_scorer_soon()` which no-ops if a scorer task is already pending.
- [ ] Tests: two rapid events enqueue exactly one task.
- [ ] Commit: `perf(scorer): debounce items_updated events into single run per window`.

## Task A3: Batch scorer upserts

**Files:**
- Modify: `agents/analysts/scorer.py:82-92`
- Modify: `db/queries.py` — add `bulk_update_scores(db, rows: list[tuple])`
- Create: `tests/test_scorer_batch.py`

**Why:** Scorer opens a new SQLite connection + commits per item × 1,200 items = minutes of fsync.

- [ ] Add `bulk_update_scores(db, [(url, momentum, normalized), ...])` using single connection, `executemany("UPDATE items SET momentum_score=?, normalized_score=? WHERE url=?")`, single commit.
- [ ] Rewrite scorer inner loop to build a list and call `bulk_update_scores` once.
- [ ] Test asserts N updates → 1 commit (monkeypatch connection to count commits).
- [ ] Benchmark before/after on prod DB snapshot; expect <10s for 1,300 items.
- [ ] Commit: `perf(scorer): batch score updates, single commit`.

## Task A4: Wire dedup into scoring path

**Files:**
- Modify: `scoring/momentum.py` — import and call `scoring.dedup.merge_duplicates`
- Modify: `agents/analysts/scorer.py` — after RawItem list built, merge then score
- Create: `tests/test_dedup_integration.py`

**Why:** `cross_platform_boost` in `config.yaml` never triggers; `times_seen` is same-URL re-observations. Legacy `scoring/dedup.py` has the fuzzy-title merger but isn't wired into `main.py` path.

- [ ] Test: two RawItems with near-identical title but different URLs (`github`, `hackernews`) → dedup merges to one group with `num_sources=2`, scored with 1.5× boost.
- [ ] In scorer, call `merged = merge_duplicates(raw_items)` (exists in legacy dedup module). Each merged group → one canonical url. Compute boost from `len(group.sources)`.
- [ ] Persist a new `item_groups` table? No — keep it ephemeral. Pass `num_sources` to `compute_final_score` from the group.
- [ ] Commit: `feat(scorer): honor cross-platform boost via fuzzy dedup`.

## Task A5: arXiv citation enrichment

**Files:**
- Modify: `collectors/arxiv.py` — after fetching papers, batch-lookup Semantic Scholar.
- Create: `collectors/semantic_scholar.py` — `get_citations(arxiv_ids: list[str]) -> dict[str, dict]` batching in groups of 100.
- Create: `tests/test_semantic_scholar.py` — HTTP mocked.

**Why:** `compute_momentum_score` for arxiv uses `citations + influential*2`; both are always 0 → all arXiv papers score identically.

- [ ] Write failing test: mock HTTP `POST /graph/v1/paper/batch` with fake response → collector returns dict.
- [ ] Implement `semantic_scholar.get_citations`. Graceful if rate-limited (429 → sleep + one retry, else skip).
- [ ] In arxiv collector, after parsing, batch-lookup and fill `raw.metrics["citation_count"]` and `raw.metrics["influential_citations"]`.
- [ ] Commit: `feat(arxiv): enrich with Semantic Scholar citation counts`.

## Task A6: DB persistence fix + one-shot migration

**Files:**
- Modify: `deploy/docker-compose.yml` (or `deploy/Dockerfile` + compose) — mount `./data:/app/data`, point `TRENDBOT_DB=/app/data/trendbot.db` env.
- Modify: `config.py` — honor `TRENDBOT_DB` env over `config.yaml` `orchestrator.db_path`.
- Create: `scripts/migrate_db_to_volume.py` — copy `/app/trendbot.db` → `/app/data/trendbot.db` if mount file is empty and source exists.
- Modify: `main.py` — invoke migration on boot before `Database` is opened.

**Why:** `docker compose down -v` or image rebuild wipes 1,329 items + 20 deep dives.

- [ ] Write migration script: skip if target nonempty; else copy + log.
- [ ] Update compose to mount a volume; set env; ensure entrypoint has write perms.
- [ ] Manual verification path: `ssh 192.168.1.10`, ensure `/app/data/trendbot.db` nonzero after next restart.
- [ ] Commit: `fix(deploy): persist SQLite to mounted volume, migrate on boot`.

## Task A7: Delete Twitter stub

**Files:**
- Delete: `collectors/twitter.py`, `agents/scouts/twitter_scout.py`
- Modify: `config.yaml` — remove `sources.twitter`, remove `orchestrator.agents.twitter_scout`
- Modify: `main.py` — drop the import/registration.
- Modify: any test referencing it.

- [ ] `git rm` + config cleanup.
- [ ] Run full pytest; fix any import errors.
- [ ] Commit: `chore(sources): remove unimplemented Twitter scout`.

---

# Plan B — Source expansion

## Task B1: Generic RSSCollector base

**Files:**
- Create: `collectors/rss.py`
- Create: `tests/test_rss_collector.py`
- Modify: `requirements.txt` — add `feedparser`.

- [ ] Test: feed a sample RSS XML (local fixture) → collector returns list of `RawItem` with title, url, description, published timestamp.
- [ ] Implement: fetch feed, parse with `feedparser`, map entries to RawItem. Include `metrics={"published_ts": ..., "source_type": "rss"}` and `source` from constructor.
- [ ] Commit: `feat(collectors): generic RSS collector`.

## Task B2: Blog scout + config

**Files:**
- Create: `agents/scouts/blog_scout.py`
- Modify: `config.yaml` — `sources.blogs.feeds` list of `{name, url}`; `orchestrator.agents.blog_scout.schedule: "0 */6 * * *"`.

Default feeds (stable URLs, verify):
- Anthropic: `https://www.anthropic.com/news/rss.xml` (or blog index)
- OpenAI: `https://openai.com/blog/rss.xml`
- Google DeepMind: `https://deepmind.google/blog/rss.xml`
- Mistral: `https://mistral.ai/news/rss.xml`
- Qwen: Alibaba Cloud AI blog
- Meta AI: `https://ai.meta.com/blog/rss/`
- HuggingFace: `https://huggingface.co/blog/feed.xml`
- Cohere: `https://cohere.com/blog/rss.xml`

- [ ] For each feed URL, verify it returns 200 with valid feed (curl in dev). Replace any 404s with the org's latest-posts page through an RSS generator like Feedity if needed.
- [ ] Implement scout: iterates `sources.blogs.feeds`, calls `RSSCollector(url, source_name="blog_"+slug)`, upserts items.
- [ ] Momentum for `blog` source: `age_decay(hours_since_published)` only — no numeric signal. Treat freshness as the dominant factor.
- [ ] Register in `main.py` and add to `agents/scouts/__init__.py`.
- [ ] Commit: `feat(sources): lab blog scout`.

## Task B3: Newsletter scout

**Files:**
- Create: `agents/scouts/newsletter_scout.py`
- Modify: `config.yaml`

Feeds:
- Import AI: `https://jack-clark.net/feed/`
- Interconnects: `https://www.interconnects.ai/feed`
- TLDR AI: `https://tldr.tech/api/rss/ai`
- The Rundown AI: newsletter RSS URL

- [ ] Same pattern as B2. Separate source tag (`newsletter`) so momentum can weight differently (newsletters are already curated → prior +1.5×).
- [ ] Commit: `feat(sources): AI newsletter scout`.

## Task B4: HuggingFace Daily Papers

**Files:**
- Create: `agents/scouts/hf_papers_scout.py`
- Modify: `config.yaml`

- [ ] HF exposes `https://huggingface.co/api/daily_papers` (JSON). One row per paper with `arxivId`, `title`, `summary`, `upvotes`.
- [ ] Momentum: `upvotes / max(hours_since_published, 1)` (like HN).
- [ ] Dedup against arXiv items via arxiv_id (add to `metrics.arxiv_id`, let dedup use it).
- [ ] Commit: `feat(sources): HuggingFace Daily Papers`.

## Task B5: Lobsters AI tag

**Files:**
- Create: `agents/scouts/lobsters_scout.py`

- [ ] `https://lobste.rs/t/ai.rss` via `RSSCollector`.
- [ ] Momentum: parse score from description HTML, or use HN-like upvote/hours. If no numeric signal, freshness-only.
- [ ] Commit: `feat(sources): Lobsters AI tag`.

## Task B6: Papers With Code trending

**Files:**
- Create: `agents/scouts/papers_with_code_scout.py`

- [ ] PwC has no first-class RSS but `https://paperswithcode.com/latest` is RSS-compatible via the `.rss` suffix — verify. Else scrape the JSON API at `https://paperswithcode.com/api/v1/papers/`.
- [ ] Momentum: paper-methods count or github_stars field.
- [ ] Commit: `feat(sources): Papers With Code trending`.

## Task B7: GitHub release events

**Files:**
- Create: `collectors/github_releases.py`
- Create: `agents/scouts/github_releases_scout.py`
- Modify: `config.yaml` — `sources.github_releases.repos: ["anthropics/claude-code", "vllm-project/vllm", "ggerganov/llama.cpp", "langchain-ai/langchain", "huggingface/transformers", ...]`

- [ ] For each repo, GET `/repos/{owner}/{repo}/releases?per_page=5`. Build RawItem per release: title = repo + tag, url = release URL, description = body (truncated).
- [ ] Momentum: freshness only (a release published 2h ago beats one from 2 weeks ago).
- [ ] Authenticated with existing `GITHUB_TOKEN`.
- [ ] Commit: `feat(sources): GitHub release events for watched repos`.

## Task B8: Momentum branches for new sources

**Files:**
- Modify: `scoring/momentum.py`

- [ ] Add branches for `blog`, `newsletter`, `hf_papers`, `lobsters`, `papers_with_code`, `github_release`. Each uses freshness + whatever signal the source provides.
- [ ] Commit: `feat(scoring): momentum formulas for new sources`.

---

# Plan C — Analysis depth

## Task C1: Org/author prior

**Files:**
- Create: `scoring/prior.py`
- Create: `tests/test_prior.py`
- Modify: `config.yaml` — `scoring.org_priors: {"anthropic.com": 2.0, "openai.com": 2.0, "deepmind.google": 2.0, "github.com/openai": 1.8, "huggingface.co/meta-llama": 1.8, ...}`

- [ ] Test: `org_prior("https://anthropic.com/news/claude-4.7")` → `2.0`; unknown domain → `1.0`.
- [ ] Implement: URL → domain + path-prefix match against config.
- [ ] Wire into `compute_final_score` as a multiplier (new param defaulting 1.0).
- [ ] Commit: `feat(scoring): org/author prior multiplier`.

## Task C2: Topic velocity agent

**Files:**
- Create: `scoring/velocity.py`
- Create: `agents/analysts/topic_velocity.py`
- Create: `tests/test_velocity.py`
- Modify: `db/schema.sql` — `CREATE TABLE IF NOT EXISTS topic_velocity (id INTEGER PRIMARY KEY, topic_id INTEGER, window_hours INTEGER, item_count INTEGER, prev_count INTEGER, recorded_at TEXT)`.
- Modify: `config.yaml` — `orchestrator.agents.topic_velocity.schedule: "0 */4 * * *"`.

- [ ] Test: inject 5 items tagged `qwen` in last 6h, 1 in prior 6h → velocity=5× → row written.
- [ ] Agent computes per-topic counts in rolling 24h window vs prior 24h; writes rows.
- [ ] Digest reads top-N highest-velocity topics as a "rising" section header.
- [ ] Commit: `feat(analysis): topic velocity detection`.

## Task C3: Topic-aware scoring

**Files:**
- Modify: `agents/analysts/scorer.py`
- Modify: `scoring/momentum.py::compute_final_score` — add `topic_weight` param.
- Create: `tests/test_scorer_topic_weight.py`

- [ ] Test: item tagged with topic having `user_interests.weight=3.0` → final score ×3 vs same item with weight=1.0.
- [ ] Scorer: for each item, SELECT MAX(ui.weight) from `item_topics` JOIN `user_interests`. Default 1.0.
- [ ] Commit: `feat(scoring): user-topic weighting`.

## Task C4: Deep-dive with web search

**Files:**
- Modify: `claude_cli.py` — `call_claude(prompt, allowed_tools: list[str] | None = None)`; if set, append `--allowedTools <comma-sep>`.
- Modify: `agents/researchers/deep_diver.py` — pass `allowed_tools=["WebSearch","WebFetch"]`.
- Modify: `prompts/deep_dive.md` — add instruction: "Use web search to find competitor projects, recent benchmarks, and author track record. Cite URLs in your response."

- [ ] Manual verification: run one deep-dive and inspect output has URL citations.
- [ ] Commit: `feat(deep-dive): enable web search tools, prompt cites sources`.

## Task C5: Feedback loop from user_actions

**Files:**
- Modify: `interfaces/web/app.py:80-98` — on `bookmarked`/`dismissed`, bump topic weights.
- Create: `tests/test_feedback_loop.py`

- [ ] Test: POST bookmarked action → matching topics' `user_interests.weight` +0.1 (capped 5.0).
- [ ] Dismissed → −0.05 (floor 0.1).
- [ ] Apply to topics assigned to that item (via `item_topics`).
- [ ] Commit: `feat(feedback): user actions adjust topic weights`.

## Task C6: Digest ranking by topic affinity

**Files:**
- Modify: `agents/notifiers/digest_pusher.py` — after selecting filter-passed items, rank by `(interest_score, topic_affinity)`.

- [ ] Replace the current rank-by-score with rank-by-`(interest_score, topic_affinity)` tie-break.
- [ ] Commit: `feat(digest): rank by user topic affinity`.

---

# Execution Order

1. **A1 filter-aware dashboard** — single biggest visible win.
2. **A7 delete twitter** — trivial cleanup, frees config.
3. **A2 debounce** → **A3 batch** → **A4 dedup** — scorer performance cluster.
4. **A5 arXiv citations** — depends on new `collectors/semantic_scholar.py`.
5. **A6 DB mount** — last in A because restart affects live system; do after validating changes.
6. **B1 RSS base** → **B2 blogs** → **B3 newsletters** → **B4 HF papers** → **B5/B6/B7** parallel.
7. **B8 momentum branches** last in B.
8. **C1 prior** → **C3 topic weighting** → **C2 velocity** → **C4 deep-dive web search** → **C5 feedback** → **C6 digest**.

# Rollout & Verification

- After each task: run `pytest tests/` (must stay green).
- After A-cluster: local smoke-test `python main.py --no-telegram --run-now` then inspect `/` dashboard.
- After B-cluster: confirm each new scout logs `found N items` in a real run; no exceptions.
- After C-cluster: inspect one digest, one deep-dive, one item detail page.
- Deploy: `ssh 192.168.1.10`, `git pull`, rebuild, tail logs for one full 4h cycle before declaring done.
