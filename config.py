from __future__ import annotations
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

DEFAULTS = {
    "scoring": {
        "digest_size": 15,
        "deep_dive_count": 5,
        "min_momentum_score": 0.3,
        "freshness_half_life_hours": 48,
        "cross_platform_boost": {2: 1.5, 3: 2.5, 4: 4.0},
    },
    "sources": {},
    "delivery": {
        "telegram": {"enabled": False},
        "dashboard": {"enabled": True, "port": 8080, "serve_dir": "dashboard_out"},
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str = "config.yaml") -> dict:
    load_dotenv()
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            user_config = yaml.safe_load(f) or {}
    else:
        user_config = {}
    return _deep_merge(DEFAULTS, user_config)


def get_env(key: str) -> str:
    value = os.environ.get(key)
    if value is None:
        raise EnvironmentError(f"Missing required environment variable: {key}")
    return value
