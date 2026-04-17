from __future__ import annotations
import json
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)


def call_claude(prompt: str, retries: int = 2, model: str | None = None) -> str:
    cmd = ["claude", "-p", prompt]
    if model:
        cmd.extend(["--model", model])

    last_rc = None
    last_stdout = ""
    last_stderr = ""
    for attempt in range(retries):
        logger.info(f"Claude CLI call attempt {attempt + 1}/{retries}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        last_rc = result.returncode
        last_stdout = result.stdout.strip()
        last_stderr = result.stderr.strip()
        if result.returncode == 0 and last_stdout:
            return last_stdout
        logger.warning(
            f"Claude CLI returned no usable output (attempt {attempt + 1}): "
            f"rc={last_rc} stdout={last_stdout!r} stderr={last_stderr!r}"
        )

    raise RuntimeError(
        f"Claude CLI failed after {retries} attempts: "
        f"rc={last_rc} stdout={last_stdout!r} stderr={last_stderr!r}"
    )


def _extract_json(raw: str) -> dict:
    """Pull a JSON object out of a Claude response.

    Claude often wraps JSON in a ```json fence and may write a preamble
    ('Here is the analysis:') before it. Falls back to the first balanced
    {...} span if no fence is present.
    """
    text = raw.strip()
    match = _FENCED_JSON_RE.search(text)
    if match:
        return json.loads(match.group(1))

    start = text.find("{")
    if start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[start:i + 1])

    return json.loads(text)


def call_claude_json(prompt: str, retries: int = 2, model: str | None = None) -> dict:
    last_err: Exception | None = None
    for attempt in range(retries):
        raw = call_claude(prompt, retries=1, model=model)
        try:
            return _extract_json(raw)
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            logger.warning(
                f"Claude CLI returned unparseable JSON (attempt {attempt + 1}/{retries}): "
                f"{e}; first 200 chars: {raw[:200]!r}"
            )

    raise RuntimeError(f"Claude CLI returned unparseable JSON after {retries} attempts: {last_err}")
