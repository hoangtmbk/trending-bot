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
