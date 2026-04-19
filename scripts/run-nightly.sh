#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/hoangta/workspace/trending-bot"
PYTHON="/Users/hoangta/miniconda3/bin/python"
LOG_DIR="$PROJECT_DIR/logs"
TS="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
LOG_FILE="$LOG_DIR/nightly-$TS.log"

mkdir -p "$LOG_DIR"

export PATH="/Users/hoangta/.local/bin:/Users/hoangta/miniconda3/bin:/usr/local/bin:/usr/bin:/bin"

cd "$PROJECT_DIR"
exec "$PYTHON" run.py >> "$LOG_FILE" 2>&1
