from __future__ import annotations
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def org_prior(url: str, priors: dict[str, float]) -> float:
    """Look up a prior multiplier for this URL's host or host+path-prefix.

    `priors` maps a match string to a multiplier. Longer match strings win
    over shorter ones so `github.com/openai` beats `github.com` for an
    OpenAI repo URL.

    Example config:
        scoring:
          org_priors:
            anthropic.com: 2.0
            openai.com: 2.0
            github.com/openai: 1.8
            huggingface.co/meta-llama: 1.8

    Why: top labs and canonical orgs publish higher-signal items than the
    long tail. Without this, a random Medium blog post ranks equal to an
    Anthropic release if their freshness+momentum happen to match.
    """
    if not url or not priors:
        return 1.0

    try:
        parsed = urlparse(url)
    except Exception:
        return 1.0

    host = (parsed.netloc or "").replace("www.", "").lower()
    path = (parsed.path or "").lower().strip("/")
    candidate = f"{host}/{path}" if path else host

    # Longest-prefix match: try the full host+path first, then strip components.
    best_match_len = -1
    best_multiplier = 1.0
    for key, mult in priors.items():
        k = key.lower().strip("/")
        if candidate == k or candidate.startswith(k + "/") or host == k:
            if len(k) > best_match_len:
                best_match_len = len(k)
                best_multiplier = float(mult)
    return best_multiplier
