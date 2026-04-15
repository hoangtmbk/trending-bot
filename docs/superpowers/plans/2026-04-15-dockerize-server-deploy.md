# Dockerize & Deploy TrendBot to lab-cam — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the `main.py` orchestrator as a single Docker container and deploy it to `lab-cam-Precision-3630-Tower` (192.168.1.10), retiring the broken macOS `run.py` cron path.

**Architecture:** One Compose service running `python main.py` (orchestrator + FastAPI dashboard + Telegram bot — three threads, one process). Bind-mounts for state (`trendbot.db`, `data/`, `logs/`) under the repo dir so SSH-shell debugging stays ergonomic. Claude CLI inside the container reads OAuth from a read-only staging dir that the entrypoint copies into a writable in-container location, mirroring the fin-apps pattern that is already running on the same host.

**Tech Stack:** Python 3.12-slim, `@anthropic-ai/claude-code@2.1.109` (via npm), Docker 29.3 + Compose v5.1, APScheduler, FastAPI/uvicorn, python-telegram-bot, SQLite/WAL, pytest, bash entrypoint.

**Spec:** `docs/superpowers/specs/2026-04-15-dockerize-server-deploy-design.md`

---

## Reference: files touched by this plan

| File | Action | Owner task |
|---|---|---|
| `.gitignore` | Modify | Task 1 |
| `requirements.txt` | Modify (delete `playwright` line) | Task 2 |
| `tests/test_web.py` | Modify (add health test class) | Task 3 |
| `interfaces/web/app.py` | Modify (add `/api/health` route) | Task 3 |
| `tests/test_main_logging.py` | Create | Task 4 |
| `main.py` | Modify (logging setup → helper + file handler) | Task 4 |
| `deploy/entrypoint.sh` | Create | Task 5 |
| `deploy/Dockerfile` | Create | Task 6 |
| `deploy/docker-compose.yml` | Create | Task 7 |
| `deploy/README.md` | Create (bootstrap notes) | Task 8 |
| `deploy/claude-credentials/.gitkeep` | Create | Task 8 |
| `CLAUDE.md` | Modify (retire `run.py` narrative) | Task 9 |

**Operational tasks** (no code changes): Task 10 (`git push`), Task 11 (server bootstrap), Task 12 (24-hour smoke watch), Task 13 (retire Mac cron — follow-up).

---

## Part A: Code changes

### Task 1: Harden `.gitignore` for the new bind-mounted paths

**Files:**
- Modify: `.gitignore`

The server bind-mounts `trendbot.db`, `logs/`, and `deploy/claude-credentials/.claude/` into the container. None of these should ever land in git. `data/` and `.env` are already ignored.

- [ ] **Step 1: Read the current `.gitignore`**

Run: `cat .gitignore`

Expected: 36 lines, already ignores `.env` and `data/`. No entries for `logs/`, `trendbot.db`, or `deploy/claude-credentials/`.

- [ ] **Step 2: Append new ignore rules**

Edit `.gitignore` so the bottom of the file reads:

```
# Superpowers
.superpowers/

# Runtime state (bind-mounted on server)
logs/
trendbot.db
trendbot.db-wal
trendbot.db-shm

# Deploy-time credentials (host staging dir, never in git)
deploy/claude-credentials/.claude/
```

- [ ] **Step 3: Verify the new rules work**

Run: `git check-ignore -v logs/foo.log trendbot.db deploy/claude-credentials/.claude/.credentials.json 2>&1`

Expected: each path is reported as ignored, with the matching line in `.gitignore`.

- [ ] **Step 4: Verify nothing already-tracked gets untracked**

Run: `git ls-files | grep -E '^(logs/|trendbot\.db|deploy/claude-credentials/\.claude/)' || echo "nothing tracked, good"`

Expected: `nothing tracked, good`. If any files are reported, STOP and ask — they need a `git rm --cached` before proceeding.

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore runtime state and deploy credential staging"
```

---

### Task 2: Drop `playwright` from `requirements.txt`

**Files:**
- Modify: `requirements.txt`

Playwright adds ~1 GB to the image for zero value — `collectors/twitter.py:25-32` has a stub `_scrape_tweets` method that returns `[]` without importing Playwright, and there are no other imports anywhere in the repo (verified: `grep -r 'playwright' trending-bot/` returns only `requirements.txt` and a docstring).

- [ ] **Step 1: Verify no code imports Playwright**

Run:
```bash
grep -rnE '(^|[^a-zA-Z_])(import|from) *playwright' --include='*.py' .
```

Expected: no matches. If anything is found, STOP — the spec's assumption is wrong and we need to revisit.

- [ ] **Step 2: Remove the line**

Edit `requirements.txt` and delete the line:

```
playwright>=1.40.0
```

The final file should read:

```
requests>=2.31.0
praw>=7.7.0
arxiv>=2.1.0
huggingface-hub>=0.20.0
beautifulsoup4>=4.12.0
python-telegram-bot>=21.0
jinja2>=3.1.0
pyyaml>=6.0
python-dotenv>=1.0.0
thefuzz>=0.22.0
python-Levenshtein>=0.25.0
pytest>=8.0.0
apscheduler>=3.10.0
aiosqlite>=0.19.0
fastapi[standard]>=0.110.0
uvicorn>=0.27.0
```

- [ ] **Step 3: Run the full test suite to make sure nothing breaks**

Run: `pytest tests/ -x -q`

Expected: all tests pass. If `tests/test_twitter.py` fails because it imports Playwright, STOP — that's a signal the stub is deeper than we thought.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: drop unused playwright dep to shrink docker image"
```

---

### Task 3: Add `GET /api/health` endpoint (TDD)

**Files:**
- Modify: `tests/test_web.py`
- Modify: `interfaces/web/app.py`

The Compose `HEALTHCHECK` hits `/api/health`. There's no such route today (verified: `grep -n 'health' interfaces/web/app.py` returns no matches).

- [ ] **Step 1: Write the failing test**

Append this class at the end of `tests/test_web.py`:

```python
# ── GET /api/health ──

class TestApiHealth:
    def test_returns_ok_true(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_includes_version_field(self, client):
        resp = client.get("/api/health")
        body = resp.json()
        assert "version" in body
        assert isinstance(body["version"], str)

    def test_does_not_require_seeded_db(self, client):
        # Same fixture as the other tests — uses an empty db via tmp_path.
        # Health must not read from the schema.
        resp = client.get("/api/health")
        assert resp.status_code == 200
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_web.py::TestApiHealth -v`

Expected: 3 failures, all with `assert 404 == 200` or similar (route doesn't exist).

- [ ] **Step 3: Add the route to `interfaces/web/app.py`**

Insert this block in `interfaces/web/app.py` immediately after line 23 (`# ── API Endpoints ──`), before the existing `/api/items` route:

```python
    @app.get("/api/health")
    async def api_health():
        import os
        return {
            "ok": True,
            "version": os.environ.get("TRENDBOT_GIT_SHA", "dev"),
        }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_web.py::TestApiHealth -v`

Expected: 3 passes.

- [ ] **Step 5: Run the full test file to confirm no regressions**

Run: `pytest tests/test_web.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_web.py interfaces/web/app.py
git commit -m "feat(web): add /api/health endpoint for container healthcheck"
```

---

### Task 4: Refactor logging setup and add rotating file handler (TDD)

**Files:**
- Create: `tests/test_main_logging.py`
- Modify: `main.py` (lines 42-47 — the existing `logging.basicConfig(...)` block and the `logger = logging.getLogger("trendbot")` line directly after it)

Inside the container, logs need to land in `/app/logs/trendbot.log` as well as stdout. We extract logging setup into a helper function so it's testable and idempotent.

- [ ] **Step 1: Write the failing test**

Create `tests/test_main_logging.py` with exactly this content:

```python
import logging
import logging.handlers
from pathlib import Path


def test_configure_logging_creates_log_file(tmp_path):
    from main import _configure_logging

    log_dir = tmp_path / "logs"
    _configure_logging(log_dir)

    logger = logging.getLogger("trendbot")
    logger.info("hello from test")

    # Flush handlers so the test can observe the file.
    for h in logger.handlers + logging.getLogger().handlers:
        h.flush()

    log_file = log_dir / "trendbot.log"
    assert log_file.exists(), f"expected {log_file} to exist"
    content = log_file.read_text()
    assert "hello from test" in content


def test_configure_logging_is_idempotent(tmp_path):
    from main import _configure_logging

    log_dir = tmp_path / "logs"
    _configure_logging(log_dir)
    _configure_logging(log_dir)  # should not double-attach handlers

    root_file_handlers = [
        h for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    # Exactly one rotating file handler on the root logger.
    assert len(root_file_handlers) == 1


def test_configure_logging_creates_log_dir_if_missing(tmp_path):
    from main import _configure_logging

    log_dir = tmp_path / "does" / "not" / "exist"
    assert not log_dir.exists()

    _configure_logging(log_dir)

    assert log_dir.exists() and log_dir.is_dir()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_main_logging.py -v`

Expected: 3 failures — `AttributeError: module 'main' has no attribute '_configure_logging'` or `ImportError`.

- [ ] **Step 3: Replace the `logging.basicConfig(...)` block in `main.py`**

In `main.py`, replace lines 42-47 — the `logging.basicConfig(...)` call **and** the `logger = logging.getLogger("trendbot")` line immediately after it — with:

```python
import logging
import logging.handlers
from pathlib import Path


def _configure_logging(log_dir: Path | str = "logs") -> None:
    """Configure root logger with stream + rotating file handler.

    Idempotent: re-calling replaces the rotating file handler so tests
    and interactive reloads don't pile up duplicates.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.RotatingFileHandler)
               for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)

    # Remove any existing rotating file handlers (idempotency) before adding a fresh one.
    for h in list(root.handlers):
        if isinstance(h, logging.handlers.RotatingFileHandler):
            root.removeHandler(h)
            h.close()

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "trendbot.log",
        maxBytes=50 * 1024 * 1024,  # 50 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


_configure_logging(Path(__file__).parent / "logs")
logger = logging.getLogger("trendbot")
```

Leave everything else in `main.py` untouched — the `_register_all_agents`, `_wire_events`, `_start_web`, `_start_telegram`, `_run_now`, and `main()` functions stay exactly as they are.

- [ ] **Step 4: Run the logging test to verify it passes**

Run: `pytest tests/test_main_logging.py -v`

Expected: 3 passes.

- [ ] **Step 5: Run the full suite to catch collateral damage**

Run: `pytest tests/ -x -q`

Expected: all tests pass. If anything fails with a logging-related error (e.g. duplicate handler warnings), the idempotency branch needs tightening — STOP and investigate.

- [ ] **Step 6: Manually verify `main.py --help` still works**

Run: `python main.py --help`

Expected: the argparse help text prints and exits cleanly. No tracebacks.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_main_logging.py
git commit -m "feat(logging): add rotating file handler via _configure_logging helper"
```

---

### Task 5: Create the container entrypoint script

**Files:**
- Create: `deploy/entrypoint.sh`

Copies the read-only Claude credentials staging dir into the container's writable `$HOME/.claude` so the in-container CLI can refresh OAuth tokens in place, then execs `python main.py`.

- [ ] **Step 1: Create the `deploy/` directory**

Run: `mkdir -p deploy`

- [ ] **Step 2: Write `deploy/entrypoint.sh`**

Create `deploy/entrypoint.sh` with exactly this content:

```bash
#!/usr/bin/env bash
set -euo pipefail

# The image bind-mounts the host's Claude credential staging dir to
# /mnt/claude-creds (read-only). Claude CLI refreshes OAuth tokens in
# place, so we need a writable copy inside the container.

CREDS_SRC="/mnt/claude-creds"
CREDS_DST="${HOME}/.claude"

if [ -d "${CREDS_SRC}" ]; then
    mkdir -p "${CREDS_DST}"
    cp -a "${CREDS_SRC}/." "${CREDS_DST}/"
    chmod -R u+rw "${CREDS_DST}"
    echo "[entrypoint] copied Claude creds from ${CREDS_SRC} to ${CREDS_DST}"
else
    echo "[entrypoint] WARNING: ${CREDS_SRC} not mounted — Claude CLI calls will fail"
fi

exec python /app/main.py "$@"
```

- [ ] **Step 3: Mark it executable**

Run: `chmod +x deploy/entrypoint.sh`

- [ ] **Step 4: Verify it parses as valid bash**

Run: `bash -n deploy/entrypoint.sh && echo OK`

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add deploy/entrypoint.sh
git commit -m "feat(deploy): add container entrypoint that stages Claude creds"
```

---

### Task 6: Create the Dockerfile

**Files:**
- Create: `deploy/Dockerfile`

Python 3.12-slim base, Node.js/npm for Claude CLI install, non-root `appuser` at uid 1000 (matches `lab-cam` on the server), entrypoint from Task 5.

- [ ] **Step 1: Write `deploy/Dockerfile`**

Create `deploy/Dockerfile` with exactly this content:

```dockerfile
FROM python:3.12-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps: curl for healthcheck, ca-certificates for TLS, git for
# optional runtime git-sha lookups, nodejs+npm to host the Claude CLI.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        nodejs \
        npm \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI — same major as the host, pinned for reproducibility.
RUN npm install -g @anthropic-ai/claude-code@2.1.109

# Non-root user with uid matching `lab-cam` on the server so bind-mounted
# files keep predictable ownership.
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser

WORKDIR /app

# Install Python deps first so code changes don't bust the pip cache layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the whole project.
COPY . .

RUN chown -R appuser:appuser /app

COPY --chown=appuser:appuser deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER appuser

# The dashboard runs on 8080 inside the container; compose publishes to 8090 on the host.
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8080/api/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
```

- [ ] **Step 2: Verify the Dockerfile parses**

Run (Mac or server, anywhere with Docker): `docker buildx build --check -f deploy/Dockerfile .`

Expected: no syntax errors. If you don't have `buildx --check` available, skip — the real validation is Task 11 step 4 (the actual build on the server).

- [ ] **Step 3: Commit**

```bash
git add deploy/Dockerfile
git commit -m "feat(deploy): add Dockerfile with pinned claude-code CLI and non-root user"
```

---

### Task 7: Create the Compose file

**Files:**
- Create: `deploy/docker-compose.yml`

- [ ] **Step 1: Write `deploy/docker-compose.yml`**

Create `deploy/docker-compose.yml` with exactly this content:

```yaml
services:
  trending-bot:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    image: trending-bot:local
    container_name: trending-bot
    restart: unless-stopped
    env_file: ../.env
    environment:
      TZ: Asia/Bangkok
    ports:
      - "8090:8080"
    volumes:
      - ../data:/app/data
      - ../logs:/app/logs
      - ../trendbot.db:/app/trendbot.db
      - ./claude-credentials/.claude:/mnt/claude-creds:ro
    user: "1000:1000"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8080/api/health"]
      interval: 60s
      timeout: 5s
      retries: 3
      start_period: 30s
```

- [ ] **Step 2: Validate the Compose file syntax**

Run from the repo root:
```bash
docker compose -f deploy/docker-compose.yml config >/dev/null && echo OK
```

Expected: `OK`. If it complains about the `../.env` file not existing, that's fine for now — we'll create `.env` on the server in Task 11. The syntax should still validate.

If the compose CLI refuses to render the config because `.env` is missing, run instead:
```bash
(cd deploy && docker compose config --no-interpolate >/dev/null) && echo OK
```

- [ ] **Step 3: Commit**

```bash
git add deploy/docker-compose.yml
git commit -m "feat(deploy): add compose service with bind-mounted state"
```

---

### Task 8: Create the `deploy/` README and credentials placeholder

**Files:**
- Create: `deploy/README.md`
- Create: `deploy/claude-credentials/.gitkeep`

The credentials staging dir is gitignored for its `.claude/` subtree (from Task 1), but we check in a `.gitkeep` so the parent `deploy/claude-credentials/` folder exists in clones. The README documents the bootstrap for humans who stumble into `deploy/` without the spec.

- [ ] **Step 1: Create the placeholder directory**

Run: `mkdir -p deploy/claude-credentials && touch deploy/claude-credentials/.gitkeep`

- [ ] **Step 2: Write `deploy/README.md`**

Create `deploy/README.md` with exactly this content:

```markdown
# TrendBot Docker deploy

Single Compose service (`trending-bot`) running `python main.py`
(orchestrator + FastAPI dashboard + Telegram bot — one process, three threads).

Target host: `lab-cam-Precision-3630-Tower` (192.168.1.10), Ubuntu 24.04,
Docker 29.3, user `lab-cam` (uid 1000).

## One-time bootstrap

```bash
ssh 192.168.1.10
cd ~/workspace
git clone https://github.com/hoangtmbk/trending-bot.git
cd trending-bot

# Prepare bind-mount targets
mkdir -p data logs deploy/claude-credentials/.claude
touch trendbot.db                       # must be a file, not a dir

# Copy Claude creds from host ~/.claude (lab-cam already has a working
# claudeAiOauth session; verify with `claude -p "OK"`)
cp ~/.claude/.credentials.json deploy/claude-credentials/.claude/
printf '{}\n' > deploy/claude-credentials/.claude/settings.json

# Environment file (API tokens) — copy from your workstation or hand-author
scp mac:~/workspace/trending-bot/.env .

# Build & launch
cd deploy
docker compose build
docker compose up -d
docker compose logs -f trending-bot
```

From a LAN client:

```bash
curl http://192.168.1.10:8090/api/health   # {"ok": true, "version": "..."}
open http://192.168.1.10:8090/             # dashboard
```

## Everyday update

```bash
ssh 192.168.1.10
cd ~/workspace/trending-bot && git pull
cd deploy && docker compose build && docker compose up -d
docker compose logs -f trending-bot --tail 50
```

## Rollback

```bash
cd ~/workspace/trending-bot
git reset --hard <prev-sha>
cd deploy && docker compose build && docker compose up -d
```

## Credential refresh

If the in-container Claude CLI starts returning `Not logged in`,
re-sync the staging dir from the host's live credentials:

```bash
cp ~/.claude/.credentials.json ~/workspace/trending-bot/deploy/claude-credentials/.claude/
cd ~/workspace/trending-bot/deploy && docker compose restart trending-bot
```

See `docs/superpowers/specs/2026-04-15-dockerize-server-deploy-design.md`
for full context.
```

- [ ] **Step 3: Commit**

```bash
git add deploy/README.md deploy/claude-credentials/.gitkeep
git commit -m "docs(deploy): add README and claude-credentials placeholder"
```

---

### Task 9: Update `CLAUDE.md` to reflect the new canonical runtime

**Files:**
- Modify: `CLAUDE.md`

CLAUDE.md currently describes `run.py` + macOS cron as the production path. After this deploy the canonical runtime is `main.py` in a Docker container on `lab-cam`. The `run.py` pipeline becomes legacy.

- [ ] **Step 1: Read the current CLAUDE.md to see what's there**

Run: `cat CLAUDE.md`

Expected: the file exists and has a "Project Overview", "Commands", "Architecture", and "Conventions" section.

- [ ] **Step 2: Replace the "Project Overview" paragraph**

Find this line in `CLAUDE.md`:

```
Nightly pipeline that scans 6 platforms (GitHub, Reddit, arXiv, HuggingFace, Twitter, Hacker News) for rising AI topics, scores by momentum, deduplicates across sources, filters with Claude CLI, runs deep-dive analysis on top items, and delivers via Telegram + static HTML dashboard. Runs at 2:00 AM UTC via cron.
```

Replace it with:

```
Always-on personal AI-trends assistant. A single `main.py` process runs
an APScheduler-driven orchestrator, a FastAPI dashboard, and a
bidirectional Telegram bot; agents (scouts/analysts/researchers) fire
on their own cron schedules and persist to `trendbot.db`. Canonical
runtime is a Docker container on `lab-cam-Precision-3630-Tower`
(192.168.1.10). The older `run.py` batch pipeline is retained for
reference but is no longer scheduled.
```

- [ ] **Step 3: Replace the "Commands" section**

Find the `## Commands` section and replace everything from that heading down to (but not including) the next `##` heading with:

````markdown
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
````

- [ ] **Step 4: Add a note near the top of "Architecture"**

At the start of the `## Architecture` section, before any other content, insert:

```markdown
**Two parallel architectures live in this repo.** `main.py` (the canonical
always-on orchestrator) and `run.py` (the legacy 5-stage batch pipeline)
share the same collectors, scoring, and `claude_cli.py` module but have
different data stores — `main.py` uses SQLite (`trendbot.db`), `run.py`
uses date-partitioned JSON under `data/YYYY-MM-DD/`. New work should
target `main.py` and its agent model. `run.py` is documented below for
reference.
```

- [ ] **Step 5: Verify `grep 2:00 AM UTC` is gone**

Run: `grep -n "2:00 AM UTC" CLAUDE.md || echo "gone"`

Expected: `gone`.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): document docker deploy as canonical runtime"
```

---

## Part B: Deploy to `lab-cam`

These tasks run against the real server. Each step shows the exact command you type and the expected output.

### Task 10: Push commits to `origin`

**Files:** none (git operation)

- [ ] **Step 1: Confirm `origin` is the canonical remote**

Run: `git remote -v`

Expected:
```
origin	https://github.com/hoangtmbk/trending-bot.git (fetch)
origin	https://github.com/hoangtmbk/trending-bot.git (push)
```

- [ ] **Step 2: Confirm the branch you're on and the commits ahead of origin**

Run: `git status -sb && git log --oneline origin/main..HEAD`

Expected: on `main`, a handful of commits from Tasks 1-9 listed.

- [ ] **Step 3: Push**

Run: `git push origin main`

Expected: push succeeds. If it fails with an auth error, resolve it interactively (personal token, SSH key, etc.) before proceeding.

---

### Task 11: Bootstrap on `lab-cam`

**Files:** none (server-side operations)

These commands run over SSH. You can paste each block verbatim.

- [ ] **Step 1: SSH in and sanity-check the environment**

Run from your Mac:
```bash
ssh 192.168.1.10 'docker --version && docker compose version && claude -p "OK" 2>&1'
```

Expected:
```
Docker version 29.3.0, build ...
Docker Compose version v5.1.0
OK
```

If `claude -p "OK"` doesn't return `OK`, STOP — the server's Claude CLI is not logged in and the deploy will fail the same way the Mac cron did. Fix by running `claude /login` directly on `lab-cam` first.

- [ ] **Step 2: Clone the repo**

```bash
ssh 192.168.1.10 'cd ~/workspace && git clone https://github.com/hoangtmbk/trending-bot.git'
```

Expected: clone succeeds and `~/workspace/trending-bot` exists.

- [ ] **Step 3: Prepare bind-mount targets**

```bash
ssh 192.168.1.10 'cd ~/workspace/trending-bot && mkdir -p data logs deploy/claude-credentials/.claude && touch trendbot.db'
```

Expected: no output, exit code 0.

- [ ] **Step 4: Copy the host's Claude creds into the staging dir**

```bash
ssh 192.168.1.10 'cp ~/.claude/.credentials.json ~/workspace/trending-bot/deploy/claude-credentials/.claude/ && printf "{}\n" > ~/workspace/trending-bot/deploy/claude-credentials/.claude/settings.json && ls -la ~/workspace/trending-bot/deploy/claude-credentials/.claude/'
```

Expected: `.credentials.json` and `settings.json` listed, both owned by `lab-cam`.

- [ ] **Step 5: Copy `.env` from Mac**

```bash
scp ~/workspace/trending-bot/.env 192.168.1.10:~/workspace/trending-bot/.env
```

Expected: one file copied, ~few hundred bytes.

Sanity check the env file on the server (without leaking values):
```bash
ssh 192.168.1.10 'awk -F= "/^[A-Z_]+=/{print \$1}" ~/workspace/trending-bot/.env'
```

Expected: at minimum `GITHUB_TOKEN`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` listed.

- [ ] **Step 6: Build the image on the server**

```bash
ssh 192.168.1.10 'cd ~/workspace/trending-bot/deploy && docker compose build'
```

Expected: build completes. Tail should end with `naming to docker.io/library/trending-bot:local`. First build takes 3-8 minutes (apt + npm + pip).

- [ ] **Step 7: Launch the container**

```bash
ssh 192.168.1.10 'cd ~/workspace/trending-bot/deploy && docker compose up -d && docker compose ps'
```

Expected: one container named `trending-bot`, status `Up (health: starting)` or `Up (healthy)`.

- [ ] **Step 8: Tail the logs for 30 seconds of startup**

```bash
ssh 192.168.1.10 'cd ~/workspace/trending-bot/deploy && timeout 30 docker compose logs -f trending-bot || true'
```

Expected:
- `[entrypoint] copied Claude creds from /mnt/claude-creds to /home/appuser/.claude`
- `Database: /app/trendbot.db`
- `Registering agents:` followed by 13 lines of `✓ <agent_name> (<schedule>)`
- `Web dashboard running at http://localhost:8080`
- `Telegram bot started` (or `Telegram bot disabled in config` if you left it off)
- `TrendBot is live. Press Ctrl+C to stop.`

If you see `Not logged in` from Claude CLI, STOP — re-check Task 11 step 4.

- [ ] **Step 9: Hit `/api/health` from the Mac**

```bash
curl -fsS http://192.168.1.10:8090/api/health
```

Expected: `{"ok":true,"version":"dev"}` (or similar).

- [ ] **Step 10: Confirm container is healthy**

```bash
ssh 192.168.1.10 'docker inspect trending-bot --format "{{.State.Health.Status}}"'
```

Expected: `healthy` within 90 seconds of launch.

---

### Task 12: 24-hour smoke watch

**Files:** none (observation only)

The orchestrator's first real value shows up when scouts start firing on APScheduler. This task is a 24-hour watch window where you check in twice to make sure the pipeline is actually producing data end-to-end.

- [ ] **Step 1: Wait for the first scout tick and confirm items landed**

Most scouts are `0 */4 * * *` (every 4 h at minute 0). Wait until the next top-of-the-4-hours wall-clock on `lab-cam` (Asia/Bangkok), then:

```bash
ssh 192.168.1.10 'cd ~/workspace/trending-bot/deploy && docker compose logs trending-bot --tail 200 | grep -E "scout|items_updated"'
```

Expected: lines from at least `github_scout` and `hackernews_scout` showing item counts.

- [ ] **Step 2: Confirm items are in `trendbot.db`**

```bash
ssh 192.168.1.10 'sqlite3 ~/workspace/trending-bot/trendbot.db "SELECT source, COUNT(*) FROM items GROUP BY source;"'
```

Expected: rows for `github`, `hackernews`, `huggingface`, `reddit`, `arxiv` (twitter may be empty — expected).

- [ ] **Step 3: Confirm Claude CLI calls are succeeding**

```bash
ssh 192.168.1.10 'cd ~/workspace/trending-bot/deploy && docker compose logs trending-bot --tail 500 | grep -iE "claude cli|not logged in"'
```

Expected: `Claude CLI call attempt 1/2` lines, no `Not logged in` lines. If you see `Not logged in`, re-run Task 11 step 4 and restart.

- [ ] **Step 4: Hit the dashboard and scroll**

From any browser on the LAN: `http://192.168.1.10:8090/`

Expected: items listed with real scores (not the `[LLM filter unavailable]` fallback text from the broken Mac run).

- [ ] **Step 5: Send `/digest` to the Telegram bot**

In your Telegram chat with the bot, send `/digest`.

Expected: the bot responds with the current digest within a few seconds. If you get a `Conflict: terminated by other getUpdates` error in `docker compose logs`, another instance of the bot is still polling somewhere (probably the Mac). STOP that other instance.

---

### Task 13 (follow-up, not time-sensitive): Retire the Mac cron

After 3-5 days of the server running cleanly, remove the macOS cron entry so it stops generating noise.

- [ ] **Step 1: Edit your macOS crontab**

Run: `crontab -e`

- [ ] **Step 2: Delete the line**

```
0 9 * * * /Users/hoangta/workspace/trending-bot/scripts/run-nightly.sh
```

- [ ] **Step 3: Save and verify**

Run: `crontab -l | grep trending-bot || echo gone`

Expected: `gone`.

---

## Plan self-review checklist (for the plan author, not the executor)

Covered against the spec:

- [x] §4.1 topology (one container, three threads) → Task 6 (Dockerfile), Task 7 (compose)
- [x] §4.2 filesystem layout → Task 7 (volumes) + Task 5 (entrypoint cp)
- [x] §4.3 compose service → Task 7
- [x] §4.4 Dockerfile sketch → Task 6
- [x] §5 credential handoff → Task 5 (entrypoint) + Task 8 (README bootstrap) + Task 11 step 4
- [x] §6 error handling — logs → Task 4 (rotating file handler); restart policy → Task 7; healthcheck → Tasks 3, 6
- [x] §7 runbook → Tasks 10, 11, 12, 13
- [x] §8 required code changes — items 1-9 → Tasks 1-9 respectively
- [x] §9 risks — credential re-sync documented in Task 8 README and spec
- [x] §10 success criteria → Task 12 verifies all of them
