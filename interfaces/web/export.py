"""Markdown export for dashboard items.

Pure formatter — no DB access, no HTTP. The web routes pass in dicts
already loaded from the DB and we return strings.
"""
from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 50) -> str:
    """Lowercase, collapse non-alphanumerics into single dashes, trim, truncate.

    Used for export filenames. Non-ASCII chars are treated as non-alphanumeric
    (no transliteration). Empty input returns empty string — callers should
    fall back to an id-based filename.
    """
    s = _NON_ALNUM.sub("-", text.lower()).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s
