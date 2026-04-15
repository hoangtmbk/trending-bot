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
