# Dockerize & Deploy TrendBot to lab-cam (192.168.1.10) — Design Spec

**Date**: 2026-04-15
**Status**: Approved
**Scope**: Package the `main.py` orchestrator (APScheduler + FastAPI dashboard + Telegram bot) as a single Docker container and migrate from the macOS laptop to the LAN server `lab-cam-Precision-3630-Tower` (192.168.1.10). Retire the legacy `run.py` + host-cron path.

---

## 1. Motivation

The nightly `run.py` cron on macOS has been silently degraded for several days: every Claude CLI invocation returns `rc=1 stdout='Not logged in'` because macOS cron jobs cannot access the login Keychain where Claude Code stores its OAuth token. The recent commit `7bd364d` made the failure visible in the dashboard (the `[LLM filter unavailable — ranked by raw momentum]` rows) but did not fix the underlying auth problem.

Rather than work around macOS cron + Keychain, this spec moves the newer `main.py` orchestrator onto a Linux server where:

1. **Claude Code CLI uses file-based credentials** (`~/.claude/.credentials.json`) on Linux, so a container can read OAuth from a bind mount without keychain drama. The server already has a working `claudeAiOauth` block and passes `claude -p "OK"`.
2. **The same host already runs `fin-apps`**, which uses exactly this pattern (bind-mount read-only staging dir → container entrypoint copies to writable location → `claude -p` runs subprocesses). We mirror it.
3. **Docker, Compose, and outbound connectivity are already set up** (Docker 29.3, Compose v5.1, 62 GiB RAM, timezone Asia/Bangkok matching the current cron).

The legacy `run.py` + macOS cron is retired in favor of the always-on `main.py` orchestrator, which is where the recent commits (agents, events, dashboard, Telegram bot) have been pointing.

---

## 2. Goals & Non-goals

**Goals**
- Run `main.py` as a single long-running container on `lab-cam` with APScheduler driving scouts on their own cron, a FastAPI dashboard reachable on the LAN, and a bidirectional Telegram bot.
- Claude CLI inside the container authenticates via the host's `claudeAiOauth` token, using the fin-apps credential-staging pattern (no `ANTHROPIC_API_KEY`, no `CLAUDE_CODE_OAUTH_TOKEN`, no keychain).
- Bind-mount persistent state (`trendbot.db`, `data/`, `logs/`) under the host repo directory so SSH-shell debugging (`sqlite3 trendbot.db`, `tail -f logs/…`) stays ergonomic.
- `docker compose up -d` is the only operational command; updates are `git pull && docker compose build && docker compose up -d`.
- Start with an empty database and let APScheduler populate it from T+0. No data migration from the Mac.

**Non-goals**
- No CI/CD pipeline. This is a personal tool deployed from an SSH session.
- No split of `main.py` into multiple services. The process model stays as-is: one Python process, three cooperating threads (orchestrator / web / Telegram).
- No reverse-proxy integration with `fin-apps-nginx`. Dashboard is exposed directly on a dedicated port.
- No Playwright in the image. The current Twitter scout is a no-op; when it grows teeth we will revisit.
- No migration of `trendbot.db` or `data/` from the Mac. Start fresh.

---

## 3. Target environment

**Host**: `lab-cam-Precision-3630-Tower`, 192.168.1.10

| Attribute | Value |
|---|---|
| OS | Ubuntu 24.04.4 LTS (noble), kernel 6.17 HWE |
| CPU | Intel Xeon E-2124G @ 3.40 GHz, 4 cores |
| RAM | 62 GiB (50 GiB typically free) |
| Disk | `/` 79% full (16 GiB free), `/mnt/data` 70% full (242 GiB free) |
| Docker | 29.3.0, data-root `/mnt/data` |
| Compose | v5.1.0 |
| User | `lab-cam` (uid 1000, member of `docker` group) |
| Timezone | Asia/Bangkok (+07) — matches current cron wall-clock |
| Claude CLI | `/usr/bin/claude` 2.1.63, already logged in (`~/.claude/.credentials.json` has `claudeAiOauth`, `claude -p "OK"` returns `OK`) |

**Coexistence**: the box already hosts `fin-apps` (nginx/finance-gateway/postgres/etc. — port 8080 is owned by `fin-apps-nginx`) and `qwen-stack` (vLLM on 8020/8030/8040, litellm on 4100). The dashboard port is chosen to avoid this range.

**Contention note**: load average was 10.7/11.3/12.7 on a 4-core machine at survey time (Chrome + uvicorn from fin-apps were the top consumers). Our container is modest (Python + SQLite + occasional `claude` subprocess) but will share CPU with existing tenants. The nightly connector at 03:00 may run slower than on the Mac. This is acceptable.

---

## 4. Architecture — one container, one process, three threads

### 4.1 Topology

A single Compose service `trending-bot` built from a project-root `Dockerfile`. Image is Python 3.12-slim (not Playwright). Inside the container, `main.py` runs exactly as it does on development machines:

| Thread | Role | Lifecycle |
|---|---|---|
| Main — `orchestrator.app.Application.run_forever()` | APScheduler + TaskDispatcher; owns process lifetime | Blocking |
| Daemon — `_start_web` | `uvicorn` + FastAPI on `0.0.0.0:8080` in-container (→ `8090` on host) | Dies with process |
| Daemon — `_start_telegram` | `python-telegram-bot` long-polling | Dies with process |

No refactor of `main.py` is required for the deploy. The only code changes are (a) adding a rotating file-log handler, and (b) adding a trivial `/api/health` route if one doesn't already exist.

### 4.2 Filesystem layout inside the container

| Path | Source | Mode | Purpose |
|---|---|---|---|
| `/app/` | image | baked, effectively read-only | Application code + `config.yaml` |
| `/app/trendbot.db` | bind mount | writable | SQLite state |
| `/app/data/` | bind mount | writable | Date-partitioned JSON artifacts |
| `/app/logs/` | bind mount | writable | Rotating application logs |
| `/home/appuser/.claude/` | entrypoint copy (tmpfs / container FS) | writable | Claude CLI writable creds (for in-place OAuth refresh) |
| `/mnt/claude-creds` | bind mount | **read-only** | Host staging dir containing `.credentials.json` + `settings.json` |
| env vars | `env_file: .env` | read-only | `GITHUB_TOKEN`, `REDDIT_*`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, etc. |

The entrypoint script runs once at startup:
```bash
#!/usr/bin/env bash
set -euo pipefail
mkdir -p /home/appuser/.claude
cp -a /mnt/claude-creds/. /home/appuser/.claude/
exec python /app/main.py
```

This gives the in-container Claude CLI a writable copy it can refresh OAuth against, while the host staging dir stays pristine and read-only.

### 4.3 Compose service

```yaml
# deploy/docker-compose.yml
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
      interval: 1m
      timeout: 5s
      retries: 3
      start_period: 30s
```

Everything under `../` resolves to the repo root on the host, so `git pull`, `sqlite3 trendbot.db`, and `tail -f logs/…` all continue to work from an SSH shell.

### 4.4 Dockerfile sketch

```dockerfile
FROM python:3.12-slim AS base

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates nodejs npm \
 && npm install -g @anthropic-ai/claude-code@2.1.109 \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 --shell /bin/bash appuser
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R appuser:appuser /app
USER appuser

COPY --chown=appuser:appuser deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
```

`requirements.txt` in the image build context has `playwright>=1.40.0` removed (or pinned to a `dev` extra). The Twitter scout imports are tolerant of Playwright's absence today.

---

## 5. Claude CLI credential handoff

### 5.1 Staging directory

On the host, a curated copy of just what the CLI needs:

```
~/workspace/trending-bot/deploy/claude-credentials/.claude/
├── .credentials.json      # copied from ~/.claude/.credentials.json on lab-cam
└── settings.json          # minimal stub: {}
```

Copied once during bootstrap:
```bash
cp ~/.claude/.credentials.json ~/workspace/trending-bot/deploy/claude-credentials/.claude/
printf '{}\n' > ~/workspace/trending-bot/deploy/claude-credentials/.claude/settings.json
```

This directory is bind-mounted read-only to `/mnt/claude-creds`. The entrypoint copies it to `/home/appuser/.claude/` inside the container (writable), and `claude -p` runs against the writable copy.

### 5.2 Token lifecycle

- **Refresh inside the container**: Claude CLI rotates OAuth tokens in place. In-container refreshes write to `/home/appuser/.claude/.credentials.json` (writable copy). They persist until the container is rebuilt or the entrypoint re-copies.
- **Host rotation**: if the host's token rotates independently (e.g. the user runs `claude` interactively on `lab-cam`), the staging dir goes stale. Refresh with `cp ~/.claude/.credentials.json ~/workspace/trending-bot/deploy/claude-credentials/.claude/ && docker compose restart trending-bot`.
- **Hard failure**: if the token is revoked and refresh can't recover, `claude_cli.py` raises `RuntimeError("Claude CLI failed after N attempts: ... Not logged in")`. This surfaces as a failed task in `trendbot.db` and a dashboard banner; the orchestrator keeps running. Fix: re-sync the staging dir and restart.

No `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` is involved. Billing stays on the Claude Max subscription.

---

## 6. Error handling, logging & restart semantics

| Concern | Approach |
|---|---|
| Container crash | `restart: unless-stopped` — auto-restarts on crash; `docker compose down` keeps it down. |
| Missed APScheduler fires | `coalesce=True`, `misfire_grace_time=300s`. Container downtime ≤ 5 min → scout runs once at the next tick; longer → misfire is skipped, we wait for the next scheduled fire. No replay storm. |
| Claude CLI failure on one task | Task marked failed in `trendbot.db`; orchestrator + other tasks keep running. Already the behavior after commit `7bd364d`. |
| Telegram polling conflict | If another copy (e.g. Mac) is polling, the bot thread crashes with `Conflict: terminated by other getUpdates`, process exits, Compose restarts it, and it loops. Self-evident in `docker compose logs`. Fix: stop the other copy. |
| Logs | Stdout (for `docker logs`) **and** `/app/logs/` with `RotatingFileHandler` (50 MB × 5 files). Add the file handler to `main.py` logging setup. |
| Healthcheck | Dockerfile/Compose `HEALTHCHECK` hits `http://localhost:8080/api/health`. If `main.py` doesn't expose one yet, add a trivial route returning `{"ok": true, "version": "<git-sha>"}`. Failing healthchecks trigger restart via Compose. |
| Observability | v1: `docker compose logs`, the dashboard itself, Telegram delivery. No Prometheus, no alerts. A daily "alive" heartbeat to Telegram is a follow-up if needed. |

---

## 7. Deployment runbook

### 7.1 One-time bootstrap on `lab-cam`

```bash
ssh 192.168.1.10
cd ~/workspace
git clone <repo-url> trending-bot
cd trending-bot

mkdir -p data logs deploy/claude-credentials/.claude

cp ~/.claude/.credentials.json deploy/claude-credentials/.claude/
printf '{}\n' > deploy/claude-credentials/.claude/settings.json

touch trendbot.db    # create file before bind mount (else Docker creates a directory)

scp mac:~/workspace/trending-bot/.env .   # or hand-author with required keys

cd deploy
docker compose build
docker compose up -d
docker compose logs -f trending-bot
```

**Sanity checks** from the Mac:
```bash
curl http://192.168.1.10:8090/api/health    # {"ok": true, ...}
open http://192.168.1.10:8090/              # dashboard loads
# Send /digest to the Telegram bot → should respond within a few seconds
```

### 7.2 Everyday update

```bash
ssh 192.168.1.10
cd ~/workspace/trending-bot && git pull
cd deploy && docker compose build && docker compose up -d
docker compose logs -f trending-bot --tail 50
```

### 7.3 Rollback

```bash
cd ~/workspace/trending-bot
git reset --hard <prev-sha>
cd deploy && docker compose build && docker compose up -d
```

### 7.4 Cutover from the Mac

Because we start fresh (no DB migration), cutover is simple:

1. Bootstrap the server container per §7.1 and verify dashboard + Telegram.
2. Keep the Mac `run-nightly.sh` crontab entry running in parallel for 3–5 days as a safety net. It will keep hitting the "Not logged in" failure — that's fine, it's diagnostic noise, not data loss.
3. Once satisfied with the server's output, remove the Mac crontab line (`crontab -e`).

---

## 8. Code changes required

These are the only code-level changes the deploy depends on:

1. **`deploy/Dockerfile`** — new file, per §4.4.
2. **`deploy/docker-compose.yml`** — new file, per §4.3.
3. **`deploy/entrypoint.sh`** — new file, per §4.2.
4. **`deploy/claude-credentials/.gitkeep`** — new file; the real credentials dir is gitignored but the folder tree is checked in for clarity. Add `deploy/claude-credentials/.claude/` to `.gitignore`.
5. **`requirements.txt`** — remove `playwright>=1.40.0`. Verified: zero imports of `playwright` anywhere in the repo, so this is safe with no code changes.
6. **`main.py`** — add `RotatingFileHandler` writing to `/app/logs/trendbot.log` alongside the existing stream handler. Small patch to `logging.basicConfig(...)` at `main.py:42`.
7. **`interfaces/web/app.py`** — add `GET /api/health` returning `{"ok": True, "version": <git-sha-or-env>}`. Verified: no health route exists today.
8. **`.gitignore`** — add `deploy/claude-credentials/.claude/` and `/.env` (if not already ignored).
9. **`CLAUDE.md`** — update the "Project Overview" and "Commands" sections to document the server deployment as the primary runtime and `main.py` as the canonical entry point. Mark `run.py` as legacy.

No other application code changes are required. The orchestrator, scouts, analysts, researchers, dashboard, and Telegram bot all run unchanged.

---

## 9. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Claude CLI token revoked → full degradation | Low | High | Re-sync staging dir + restart (documented in §5.2). Error already surfaces clearly in logs. |
| Telegram polling conflict with Mac copy | Medium (during cutover window) | Medium | Cutover checklist in §7.4 — don't run `main.py` on the Mac simultaneously. |
| SQLite corruption under unexpected process kill | Low | High | WAL mode (SQLite default for modern Python); bind-mounted DB file; daily snapshot via `sqlite3 trendbot.db ".backup …"` in a follow-up if needed. |
| CPU contention from fin-apps / qwen-stack tenants | High | Low | Accept slower runs; APScheduler misfire grace already handles lateness. |
| Root disk fills (`/` 79% full) | Medium | High | Docker data is on `/mnt/data` (242 GiB free), so images/volumes don't hit `/`. Bind-mounted state is under `/home/lab-cam/workspace/trending-bot` which is on `/` — watch `du -sh ~/workspace/trending-bot/{data,logs}`. |
| OAuth refresh quietly stops working inside container | Low | Medium | Log Claude CLI rc/stdout/stderr at every call (already done by `claude_cli.py`). Dashboard will show `[LLM filter unavailable]` on the next run — self-evident. |

---

## 10. Success criteria

- `docker compose up -d` from `~/workspace/trending-bot/deploy/` brings up the container; it stays `healthy` for 24 h without manual intervention.
- `http://192.168.1.10:8090/` loads the dashboard with real scout data (not an empty DB) within one scheduled scout tick.
- The Telegram bot responds to `/digest` (or equivalent) within a few seconds.
- A full day of scheduled agent runs (scouts + scorer + filter + nightly connector) completes with **no** `Not logged in` Claude CLI failures in `docker compose logs`.
- Claude CLI calls for LLM filter, deep dive, and summary succeed — the dashboard shows scored 0–10 items and deep-dive cards, not the `[LLM filter unavailable — ranked by raw momentum]` fallback.

---

## 11. Out of scope / follow-ups

- Data migration from the Mac (can rsync `trendbot.db` + `data/` in a one-off if we change our minds — see §2 Non-goals).
- Reverse-proxy integration with `fin-apps-nginx` under a shared hostname.
- HTTPS / public exposure via Tailscale or Cloudflare Tunnel.
- Daily heartbeat ping to Telegram.
- Prometheus metrics and alerts.
- Reintroducing Playwright for a real Twitter scout (separate spec when the scraper is actually implemented).
- Splitting web/bot from the worker for zero-downtime orchestrator deploys.
- Automated DB snapshots via a sidecar or cron.
