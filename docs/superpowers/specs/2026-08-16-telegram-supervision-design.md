# Telegram bot supervision — design

**Date:** 2026-08-16
**Status:** approved, ready to implement

## Problem

On 2026-08-15, a routine deploy left the Telegram bot permanently dead while
the container reported `healthy`. The bot only came back after a manual
`docker compose restart`.

Three independent gaps combined:

1. **No supervision.** `main.py:191-199` runs
   `loop.run_until_complete(_run_telegram_polling(tg_app))` on a
   `daemon=True` thread with **no `try`/`except`**. Any exception escapes to
   the thread's default excepthook and the thread dies silently — with no
   ERROR record from the application's own logger.
2. **The fatal call is network I/O.** `_run_telegram_polling`
   (`main.py:164-171`) opens `async with tg_app`, which performs
   `initialize()` → `get_me()`. That is a network round-trip *before* any
   resilient loop exists. The container has a well-documented intermittent
   DNS problem (668 connect failures over three months), so this call fails
   regularly.
3. **The healthcheck cannot detect it.** `/api/health`
   (`interfaces/web/app.py:99-104`) returns a hardcoded `{"ok": True}`. It
   proves only that uvicorn is serving. `orchestrator/app.py:66-81` never
   checks whether the telegram thread is alive either.

Note that python-telegram-bot **already self-heals during polling** — 790
polling exceptions were logged over three months and polling continued each
time. The vulnerable window is startup, before `start_polling()` returns.

## Non-goals

- **Not fixing `telegram.error.Conflict`.** Those 96 conflicts are a
  separate root cause: the bot token is shared across six projects and a
  second `getUpdates` consumer runs on a laptop schedule. The fix is a
  dedicated token, which is a credential change, not a code change.
- **No `digest_pusher` send retry.** The 2026-08-14 20:00 digest was lost to
  the same DNS flakiness, but delivery retry has its own idempotency
  question (`_record_digest` runs even after a partial send). Deliberately
  out of scope.
- **No container auto-restart**, and no change to `restart: unless-stopped`.
  Under plain `docker compose` a failing healthcheck marks the container
  unhealthy but does **not** restart it, so the health signal is
  observability only.

## Design

### 1. `interfaces/telegram/supervisor.py` (new)

The retry logic lives here, not in `main.py`, so it can be tested without a
network, a real clock, or a running bot.

**`BotStatus`** — a thread-safe state holder, written by the telegram thread
and read by the web app.

- States: `disabled`, `starting`, `running`, `retrying`.
- Carries `since` (when the current state began) and `last_error`.
- Compound updates are lock-guarded; `snapshot()` returns an immutable view
  so a reader never observes a half-written state.

**`supervise(attempt, status, sleep=time.sleep, max_delay=60.0)`** — the
retry loop, with `attempt` and `sleep` injected.

```
delay = INITIAL_DELAY          # 5s
while True:
    try:
        attempt()              # blocks until shutdown
        return                 # clean return == intentional shutdown
    except Exception as e:
        status.mark_retrying(e)
        sleep(delay)
        delay = min(delay * 2, max_delay)
```

Retry is **unbounded** with exponential backoff capped at 60s: 5, 10, 20,
40, 60, 60… The bot returns whenever DNS recovers with no human in the loop,
and the cap keeps log noise to roughly one line per minute during a long
outage. This mirrors `orchestrator/app.py:48-57`'s `_dispatch_loop`, which
is the existing convention in this codebase for a resilient background
thread.

The backoff **resets to 5s** whenever polling reaches `running`, so a
failure after a week of uptime reconnects in 5s rather than 60s.

### 2. `main.py` becomes thin

`_run()` delegates to `supervise(...)`. `attempt` **rebuilds the bot via
`create_bot(...)` on every try** rather than reusing a single `tg_app`: a
PTB `Application` whose `initialize()` failed partway through `async with`
is left half-initialized, and reusing it is the kind of thing that works in
testing and fails at 3am. Fresh application object and fresh event loop per
attempt.

`_run_telegram_polling` calls `status.mark_running()` after
`start_polling()` returns.

### 3. Honest `/api/health`

`create_app` gains an **optional** `bot_status` keyword argument. It
defaults to a `disabled` status so the 17 existing `create_app(db,
config={})` call sites in the test suite keep working unchanged.

The endpoint gains a `telegram` block and returns **503 once the state has
been `retrying` for longer than the grace period (5 min)**; otherwise 200.

```json
{
  "ok": true,
  "version": "...",
  "telegram": {"state": "retrying", "since": "...", "last_error": "httpx.ConnectError: ..."}
}
```

`disabled` never degrades — a bot intentionally turned off in config is not
a fault. The grace period exists so that ordinary short DNS blips do not
flap the container between healthy and unhealthy; only a sustained outage
raises the flag.

## Testing

Written test-first.

**`supervise`:**
- `attempt` raises twice then succeeds → ends `running`; asserts recovery
  *and* the 5s → 10s backoff sequence via an injected `sleep` that records
  its arguments.
- raises 20 times → still retrying (proves unbounded).
- backoff caps at `max_delay` and never exceeds it.
- backoff resets to the initial delay after reaching `running`.
- a clean return from `attempt` exits the loop without sleeping.

**`BotStatus`:** state transitions, `since` advances on change,
`last_error` recorded, `snapshot()` isolation.

**`/api/health`:** `disabled` → 200; `running` → 200; `retrying` within
grace → 200; `retrying` beyond grace → 503 with the detail block populated.

Plus: the existing 468 tests must still pass.

## Risk

Low. The supervisor is additive and the only change to existing behaviour is
that a previously-fatal exception now retries. The one behavioural risk is
the healthcheck returning 503, which under plain compose triggers no action
— it only changes what `docker compose ps` displays.
