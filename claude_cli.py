from __future__ import annotations
import json
import logging
import subprocess

logger = logging.getLogger(__name__)


def call_claude(prompt: str, retries: int = 2, model: str | None = None) -> str:
    cmd = ["claude", "-p", prompt]
    if model:
        cmd.extend(["--model", model])

    for attempt in range(retries):
        logger.info(f"Claude CLI call attempt {attempt + 1}/{retries}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return result.stdout.strip()
        logger.warning(f"Claude CLI failed (attempt {attempt + 1}): {result.stderr}")

    raise RuntimeError(f"Claude CLI failed after {retries} attempts: {result.stderr}")


def call_claude_json(prompt: str, retries: int = 2, model: str | None = None) -> dict:
    raw = call_claude(prompt, retries=retries, model=model)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    return json.loads(cleaned)
