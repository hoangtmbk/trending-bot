FROM python:3.12-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps: curl for healthcheck, ca-certificates for TLS, git for
# optional runtime git-sha lookups.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
 && rm -rf /var/lib/apt/lists/*

# Node.js 20 LTS from NodeSource (Debian slim ships Node 18 which is too old
# for recent @anthropic-ai/claude-code releases).
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI — pinned for reproducibility.
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
