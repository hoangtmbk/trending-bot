import os
from pathlib import Path
from config import load_config


def test_load_config(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("""
scoring:
  digest_size: 10
  deep_dive_count: 3
  min_momentum_score: 0.5
  freshness_half_life_hours: 48
  cross_platform_boost:
    2: 1.5
    3: 2.5
    4: 4.0
sources:
  github:
    enabled: true
    topics: [ai]
  reddit:
    enabled: false
    subreddits: []
  arxiv:
    enabled: true
    categories: [cs.AI]
  huggingface:
    enabled: true
  hackernews:
    enabled: true
delivery:
  telegram:
    enabled: false
  dashboard:
    enabled: true
    port: 9090
    serve_dir: dash_out
""")
    config = load_config(str(cfg_file))
    assert config["scoring"]["digest_size"] == 10
    assert config["sources"]["github"]["enabled"] is True
    assert config["sources"]["reddit"]["enabled"] is False
    assert config["delivery"]["dashboard"]["port"] == 9090


def test_load_config_returns_defaults_for_missing_keys(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("sources:\n  github:\n    enabled: true\n")
    config = load_config(str(cfg_file))
    assert "scoring" in config
    assert config["scoring"]["digest_size"] == 15
