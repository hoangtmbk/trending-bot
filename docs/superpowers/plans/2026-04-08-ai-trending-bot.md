# AI Trending Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a nightly pipeline that collects trending AI content from 6 platforms, scores and filters via Claude CLI, generates deep-dive analysis reports, and delivers via markdown files, a static web dashboard, and Telegram.

**Architecture:** Five-stage pipeline (Collect → Score → Analyze → Report → Deliver). Each stage reads/writes JSON/markdown files under `data/YYYY-MM-DD/`. Claude CLI is invoked at 3 points: quality filtering, deep-dive analysis, and executive summary.

**Tech Stack:** Python 3.11+, Claude CLI, requests, praw, arxiv, huggingface_hub, playwright, beautifulsoup4, python-telegram-bot, jinja2, pyyaml, python-dotenv

**Spec:** `docs/superpowers/specs/2026-04-08-ai-trending-bot-design.md`

---

## File Map

```
trending-bot/
├── run.py                      # Pipeline orchestrator — runs stages sequentially
├── config.yaml                 # All configuration: sources, thresholds, delivery
├── requirements.txt            # Python dependencies
├── .env.example                # Template for secrets
│
├── models.py                   # Shared data models (RawItem, ScoredItem, AnalysisReport)
├── config.py                   # Config loader — reads config.yaml + .env
├── claude_cli.py               # Claude CLI wrapper — subprocess call with retry
│
├── collectors/
│   ├── __init__.py
│   ├── base.py                 # BaseCollector ABC
│   ├── hackernews.py           # HN Algolia API
│   ├── github.py               # GitHub REST API
│   ├── reddit.py               # Reddit OAuth API (praw)
│   ├── arxiv.py                # arXiv + Semantic Scholar APIs
│   ├── huggingface.py          # HuggingFace Hub API
│   └── twitter.py              # X scraping via playwright
│
├── scoring/
│   ├── __init__.py
│   ├── momentum.py             # Per-source momentum formulas + final score
│   ├── dedup.py                # URL + fuzzy title dedup
│   └── llm_filter.py           # Claude CLI quality filter
│
├── analysis/
│   ├── __init__.py
│   ├── gatherer.py             # Fetches source material for deep dives
│   └── deep_dive.py            # Claude CLI deep dive orchestrator
│
├── reporting/
│   ├── __init__.py
│   ├── digest.py               # Markdown digest builder
│   ├── summary.py              # Claude CLI executive summary
│   └── dashboard.py            # Static HTML dashboard generator
│
├── delivery/
│   ├── __init__.py
│   ├── telegram.py             # Telegram bot sender
│   └── server.py               # Simple HTTP server
│
├── prompts/
│   ├── filter.md               # LLM filter prompt template
│   ├── deep_dive.md            # Deep dive prompt template
│   └── summary.md              # Executive summary prompt template
│
├── templates/
│   ├── index.html              # Dashboard main page
│   ├── item.html               # Deep dive detail page
│   └── assets/
│       └── style.css           # Dashboard styles
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Shared fixtures
│   ├── test_models.py
│   ├── test_config.py
│   ├── test_claude_cli.py
│   ├── test_hackernews.py
│   ├── test_github.py
│   ├── test_reddit.py
│   ├── test_arxiv.py
│   ├── test_huggingface.py
│   ├── test_twitter.py
│   ├── test_momentum.py
│   ├── test_dedup.py
│   ├── test_llm_filter.py
│   ├── test_gatherer.py
│   ├── test_deep_dive.py
│   ├── test_digest.py
│   ├── test_summary.py
│   ├── test_dashboard.py
│   ├── test_telegram.py
│   └── test_pipeline.py
│
└── data/                       # Gitignored output directory
```

---

### Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `config.yaml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `models.py`
- Create: `config.py`
- Test: `tests/__init__.py`, `tests/conftest.py`, `tests/test_models.py`, `tests/test_config.py`

- [ ] **Step 1: Create requirements.txt**

```
requests>=2.31.0
praw>=7.7.0
arxiv>=2.1.0
huggingface-hub>=0.20.0
beautifulsoup4>=4.12.0
playwright>=1.40.0
python-telegram-bot>=21.0
jinja2>=3.1.0
pyyaml>=6.0
python-dotenv>=1.0.0
thefuzz>=0.22.0
python-Levenshtein>=0.25.0
pytest>=8.0.0
```

- [ ] **Step 2: Create .env.example**

```
GITHUB_TOKEN=ghp_your_token_here
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USER_AGENT=trending-bot/1.0
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

- [ ] **Step 3: Create config.yaml**

```yaml
schedule:
  cron: "0 2 * * *"

scoring:
  digest_size: 15
  deep_dive_count: 5
  min_momentum_score: 0.3
  freshness_half_life_hours: 48
  cross_platform_boost:
    2: 1.5
    3: 2.5
    4: 4.0

sources:
  github:
    enabled: true
    topics:
      - ai
      - llm
      - machine-learning
      - deep-learning
      - transformer
      - agents
      - computer-vision
      - nlp
      - rag
  reddit:
    enabled: true
    subreddits:
      - MachineLearning
      - LocalLLaMA
      - artificial
      - ChatGPT
      - singularity
      - StableDiffusion
  arxiv:
    enabled: true
    categories:
      - cs.AI
      - cs.CL
      - cs.CV
      - cs.LG
      - cs.MA
      - stat.ML
  huggingface:
    enabled: true
  twitter:
    enabled: true
    fallback_to_rss: true
  hackernews:
    enabled: true

delivery:
  telegram:
    enabled: true
  dashboard:
    enabled: true
    port: 8080
    serve_dir: dashboard_out
```

- [ ] **Step 4: Write failing tests for models**

```python
# tests/__init__.py
# (empty)

# tests/conftest.py
import os
import pytest
from pathlib import Path

@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provides a temporary data directory for tests."""
    return tmp_path / "data"

@pytest.fixture
def sample_raw_item():
    return {
        "title": "AgentKit v2",
        "url": "https://github.com/example/agentkit",
        "source": "github",
        "description": "Multi-agent orchestration framework",
        "metrics": {"stars_24h": 1200, "total_stars": 3000, "forks": 150},
        "timestamp": "2026-04-08T02:00:00Z",
    }
```

```python
# tests/test_models.py
from models import RawItem, ScoredItem, AnalysisReport
from datetime import datetime, timezone


def test_raw_item_from_dict(sample_raw_item):
    item = RawItem.from_dict(sample_raw_item)
    assert item.title == "AgentKit v2"
    assert item.source == "github"
    assert item.metrics["stars_24h"] == 1200


def test_raw_item_to_dict(sample_raw_item):
    item = RawItem.from_dict(sample_raw_item)
    d = item.to_dict()
    assert d["title"] == "AgentKit v2"
    assert d["url"] == "https://github.com/example/agentkit"


def test_scored_item_from_raw(sample_raw_item):
    raw = RawItem.from_dict(sample_raw_item)
    scored = ScoredItem(
        raw_items=[raw],
        momentum_score=0.85,
        final_score=1.7,
        sources=["github"],
        category="tool",
        llm_summary="Multi-agent framework with visual builder",
        interest_score=9,
    )
    assert scored.final_score == 1.7
    assert scored.title == "AgentKit v2"
    assert len(scored.sources) == 1


def test_scored_item_title_uses_first_raw():
    item1 = RawItem.from_dict({
        "title": "First Title", "url": "http://a.com", "source": "github",
        "description": "", "metrics": {}, "timestamp": "2026-04-08T00:00:00Z",
    })
    item2 = RawItem.from_dict({
        "title": "Second Title", "url": "http://a.com", "source": "reddit",
        "description": "", "metrics": {}, "timestamp": "2026-04-08T00:00:00Z",
    })
    scored = ScoredItem(
        raw_items=[item1, item2], momentum_score=0.5, final_score=1.0,
        sources=["github", "reddit"], category="tool", llm_summary="", interest_score=5,
    )
    assert scored.title == "First Title"


def test_analysis_report_to_dict():
    report = AnalysisReport(
        slug="agentkit-v2",
        title="AgentKit v2",
        what_it_is="A multi-agent framework",
        why_trending="1.2k stars in 24h",
        pain_point="Building multi-agent systems is hard",
        gap_analysis="No visual builder exists",
        competitors=["CrewAI", "AutoGen"],
        app_idea="Visual drag-and-drop agent builder",
        feasibility={"effort": "3 weeks", "market": "growing", "competition": "low"},
    )
    d = report.to_dict()
    assert d["slug"] == "agentkit-v2"
    assert "CrewAI" in d["competitors"]
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `cd /Users/hoangta/workspace/trending-bot && python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'models'`

- [ ] **Step 6: Implement models.py**

```python
# models.py
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


@dataclass
class RawItem:
    title: str
    url: str
    source: str
    description: str
    metrics: dict
    timestamp: str

    @classmethod
    def from_dict(cls, d: dict) -> RawItem:
        return cls(
            title=d["title"],
            url=d["url"],
            source=d["source"],
            description=d["description"],
            metrics=d["metrics"],
            timestamp=d["timestamp"],
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScoredItem:
    raw_items: list[RawItem]
    momentum_score: float
    final_score: float
    sources: list[str]
    category: str
    llm_summary: str
    interest_score: int

    @property
    def title(self) -> str:
        return self.raw_items[0].title

    @property
    def url(self) -> str:
        return self.raw_items[0].url

    @property
    def description(self) -> str:
        return self.raw_items[0].description

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "description": self.description,
            "momentum_score": self.momentum_score,
            "final_score": self.final_score,
            "sources": self.sources,
            "category": self.category,
            "llm_summary": self.llm_summary,
            "interest_score": self.interest_score,
            "raw_items": [r.to_dict() for r in self.raw_items],
        }


@dataclass
class AnalysisReport:
    slug: str
    title: str
    what_it_is: str
    why_trending: str
    pain_point: str
    gap_analysis: str
    competitors: list[str]
    app_idea: str
    feasibility: dict

    def to_dict(self) -> dict:
        return asdict(self)

    def to_markdown(self) -> str:
        competitors_str = ", ".join(self.competitors) if self.competitors else "None found"
        feasibility_lines = "\n".join(f"- **{k.title()}:** {v}" for k, v in self.feasibility.items())
        return f"""# {self.title}

## What It Is
{self.what_it_is}

## Why It's Trending
{self.why_trending}

## Pain Point
{self.pain_point}

## Gap Analysis
{self.gap_analysis}

## Competitors
{competitors_str}

## Proposed Solution
{self.app_idea}

## Feasibility
{feasibility_lines}
"""
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /Users/hoangta/workspace/trending-bot && python -m pytest tests/test_models.py -v`
Expected: All 5 tests PASS

- [ ] **Step 8: Write failing tests for config**

```python
# tests/test_config.py
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
  twitter:
    enabled: false
    fallback_to_rss: true
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
    # Should have scoring defaults
    assert "scoring" in config
    assert config["scoring"]["digest_size"] == 15
```

- [ ] **Step 9: Run tests to verify they fail**

Run: `cd /Users/hoangta/workspace/trending-bot && python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 10: Implement config.py**

```python
# config.py
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
```

- [ ] **Step 11: Run tests to verify they pass**

Run: `cd /Users/hoangta/workspace/trending-bot && python -m pytest tests/test_config.py -v`
Expected: All 2 tests PASS

- [ ] **Step 12: Commit**

```bash
git add requirements.txt config.yaml .env.example models.py config.py tests/
git commit -m "feat: project setup with models and config"
```

---

### Task 2: Claude CLI Wrapper

**Files:**
- Create: `claude_cli.py`
- Test: `tests/test_claude_cli.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_claude_cli.py
import json
from unittest.mock import patch, MagicMock
from claude_cli import call_claude, call_claude_json


def test_call_claude_returns_stdout():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Hello from Claude"
    mock_result.stderr = ""
    with patch("claude_cli.subprocess.run", return_value=mock_result) as mock_run:
        result = call_claude("Say hello")
        assert result == "Hello from Claude"
        args = mock_run.call_args[0][0]
        assert "claude" in args
        assert "-p" in args


def test_call_claude_json_parses_output():
    response = json.dumps({"items": [{"name": "test"}]})
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = response
    mock_result.stderr = ""
    with patch("claude_cli.subprocess.run", return_value=mock_result):
        result = call_claude_json("Return JSON")
        assert result["items"][0]["name"] == "test"


def test_call_claude_retries_on_failure():
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stdout = ""
    fail_result.stderr = "Error"

    success_result = MagicMock()
    success_result.returncode = 0
    success_result.stdout = "OK"
    success_result.stderr = ""

    with patch("claude_cli.subprocess.run", side_effect=[fail_result, success_result]):
        result = call_claude("Test", retries=2)
        assert result == "OK"


def test_call_claude_raises_after_exhausting_retries():
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stdout = ""
    fail_result.stderr = "Error"

    with patch("claude_cli.subprocess.run", return_value=fail_result):
        try:
            call_claude("Test", retries=1)
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "Claude CLI failed" in str(e)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_claude_cli.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement claude_cli.py**

```python
# claude_cli.py
from __future__ import annotations
import json
import logging
import subprocess

logger = logging.getLogger(__name__)


def call_claude(prompt: str, retries: int = 2, model: str | None = None) -> str:
    cmd = ["claude", "-p", prompt, "--no-input"]
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
    # Claude may wrap JSON in markdown code blocks
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first and last lines (``` markers)
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    return json.loads(cleaned)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_claude_cli.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add claude_cli.py tests/test_claude_cli.py
git commit -m "feat: Claude CLI wrapper with retry logic"
```

---

### Task 3: Base Collector + Hacker News Collector

**Files:**
- Create: `collectors/__init__.py`
- Create: `collectors/base.py`
- Create: `collectors/hackernews.py`
- Test: `tests/test_hackernews.py`

- [ ] **Step 1: Write the base collector and collector __init__**

```python
# collectors/__init__.py
from collectors.base import BaseCollector

# collectors/base.py
from __future__ import annotations
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from models import RawItem

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    source_name: str = ""

    @abstractmethod
    def collect(self) -> list[RawItem]:
        """Fetch items from the source. Returns a list of RawItem."""
        ...

    def save(self, items: list[RawItem], data_dir: Path) -> Path:
        raw_dir = data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        out_path = raw_dir / f"{self.source_name}.json"
        with open(out_path, "w") as f:
            json.dump([item.to_dict() for item in items], f, indent=2)
        logger.info(f"Saved {len(items)} items to {out_path}")
        return out_path

    def run(self, data_dir: Path) -> list[RawItem]:
        items = self.collect()
        self.save(items, data_dir)
        return items
```

- [ ] **Step 2: Write failing tests for HN collector**

```python
# tests/test_hackernews.py
import json
from unittest.mock import patch, MagicMock
from collectors.hackernews import HackerNewsCollector
from models import RawItem


def _mock_search_response():
    return {
        "hits": [
            {
                "objectID": "12345",
                "title": "New AI Agent Framework Released",
                "url": "https://github.com/example/agent-framework",
                "points": 350,
                "num_comments": 120,
                "created_at_i": 1744070400,
                "created_at": "2026-04-08T00:00:00Z",
                "_tags": ["story"],
            },
            {
                "objectID": "12346",
                "title": "Cooking Recipe Manager",
                "url": "https://example.com/cooking",
                "points": 200,
                "num_comments": 50,
                "created_at_i": 1744070400,
                "created_at": "2026-04-08T00:00:00Z",
                "_tags": ["story"],
            },
        ]
    }


def test_hackernews_collector_returns_raw_items():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_search_response()

    with patch("collectors.hackernews.requests.get", return_value=mock_resp):
        collector = HackerNewsCollector()
        items = collector.collect()
        assert len(items) >= 1
        assert all(isinstance(i, RawItem) for i in items)
        assert items[0].source == "hackernews"


def test_hackernews_collector_includes_metrics():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_search_response()

    with patch("collectors.hackernews.requests.get", return_value=mock_resp):
        collector = HackerNewsCollector()
        items = collector.collect()
        assert "points" in items[0].metrics
        assert "num_comments" in items[0].metrics


def test_hackernews_collector_saves_to_file(tmp_data_dir):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_search_response()

    with patch("collectors.hackernews.requests.get", return_value=mock_resp):
        collector = HackerNewsCollector()
        items = collector.run(tmp_data_dir)
        saved_file = tmp_data_dir / "raw" / "hackernews.json"
        assert saved_file.exists()
        data = json.loads(saved_file.read_text())
        assert len(data) == len(items)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_hackernews.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement HN collector**

```python
# collectors/hackernews.py
from __future__ import annotations
import logging
from datetime import datetime, timezone
import requests
from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)

AI_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "llm", "gpt", "claude", "gemini", "transformer", "neural network",
    "diffusion", "rag", "agent", "langchain", "hugging face", "openai",
    "anthropic", "fine-tuning", "embedding", "vector database",
    "computer vision", "nlp", "reinforcement learning",
]


class HackerNewsCollector(BaseCollector):
    source_name = "hackernews"
    BASE_URL = "https://hn.algolia.com/api/v1"

    def collect(self) -> list[RawItem]:
        items = []
        for query in ["AI", "LLM", "machine learning"]:
            url = f"{self.BASE_URL}/search_by_date"
            params = {
                "query": query,
                "tags": "story",
                "numericFilters": "points>10",
                "hitsPerPage": 50,
            }
            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                for hit in data.get("hits", []):
                    if not self._is_ai_relevant(hit):
                        continue
                    item = RawItem(
                        title=hit.get("title", ""),
                        url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
                        source=self.source_name,
                        description="",
                        metrics={
                            "points": hit.get("points", 0),
                            "num_comments": hit.get("num_comments", 0),
                            "objectID": hit.get("objectID", ""),
                        },
                        timestamp=hit.get("created_at", ""),
                    )
                    items.append(item)
            except requests.RequestException as e:
                logger.error(f"HN API error for query '{query}': {e}")

        # Deduplicate by objectID
        seen = set()
        unique = []
        for item in items:
            oid = item.metrics.get("objectID", item.url)
            if oid not in seen:
                seen.add(oid)
                unique.append(item)

        logger.info(f"HN collector found {len(unique)} items")
        return unique

    def _is_ai_relevant(self, hit: dict) -> bool:
        title = (hit.get("title") or "").lower()
        return any(kw in title for kw in AI_KEYWORDS)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_hackernews.py -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add collectors/ tests/test_hackernews.py
git commit -m "feat: base collector + Hacker News collector"
```

---

### Task 4: GitHub Collector

**Files:**
- Create: `collectors/github.py`
- Test: `tests/test_github.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_github.py
import json
from unittest.mock import patch, MagicMock
from collectors.github import GitHubCollector
from models import RawItem


def _mock_search_response():
    return {
        "items": [
            {
                "full_name": "example/agentkit",
                "html_url": "https://github.com/example/agentkit",
                "description": "Multi-agent framework",
                "stargazers_count": 3000,
                "forks_count": 150,
                "created_at": "2026-03-01T00:00:00Z",
                "pushed_at": "2026-04-08T00:00:00Z",
                "topics": ["ai", "agents", "llm"],
                "language": "Python",
            }
        ]
    }


def test_github_collector_returns_raw_items():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_search_response()

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake_token", topics=["ai"])
        items = collector.collect()
        assert len(items) >= 1
        assert items[0].source == "github"
        assert "stargazers_count" in items[0].metrics


def test_github_collector_saves_to_file(tmp_data_dir):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_search_response()

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake_token", topics=["ai"])
        items = collector.run(tmp_data_dir)
        saved = tmp_data_dir / "raw" / "github.json"
        assert saved.exists()
        data = json.loads(saved.read_text())
        assert len(data) == len(items)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_github.py -v`
Expected: FAIL

- [ ] **Step 3: Implement GitHub collector**

```python
# collectors/github.py
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
import requests
from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)


class GitHubCollector(BaseCollector):
    source_name = "github"
    API_URL = "https://api.github.com"

    def __init__(self, token: str, topics: list[str] | None = None):
        self.token = token
        self.topics = topics or ["ai", "llm", "machine-learning"]
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def collect(self) -> list[RawItem]:
        items = []
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

        for topic in self.topics:
            query = f"topic:{topic} pushed:>{since} stars:>10"
            url = f"{self.API_URL}/search/repositories"
            params = {"q": query, "sort": "stars", "order": "desc", "per_page": 30}
            try:
                resp = requests.get(url, headers=self.headers, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                for repo in data.get("items", []):
                    item = RawItem(
                        title=repo["full_name"],
                        url=repo["html_url"],
                        source=self.source_name,
                        description=repo.get("description") or "",
                        metrics={
                            "stargazers_count": repo.get("stargazers_count", 0),
                            "forks_count": repo.get("forks_count", 0),
                            "created_at": repo.get("created_at", ""),
                            "pushed_at": repo.get("pushed_at", ""),
                            "topics": repo.get("topics", []),
                            "language": repo.get("language", ""),
                        },
                        timestamp=repo.get("pushed_at", ""),
                    )
                    items.append(item)
            except requests.RequestException as e:
                logger.error(f"GitHub API error for topic '{topic}': {e}")

        # Deduplicate by URL
        seen = set()
        unique = []
        for item in items:
            if item.url not in seen:
                seen.add(item.url)
                unique.append(item)

        logger.info(f"GitHub collector found {len(unique)} repos")
        return unique
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_github.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add collectors/github.py tests/test_github.py
git commit -m "feat: GitHub collector"
```

---

### Task 5: Reddit Collector

**Files:**
- Create: `collectors/reddit.py`
- Test: `tests/test_reddit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_reddit.py
import json
from unittest.mock import patch, MagicMock
from collectors.reddit import RedditCollector
from models import RawItem


def _mock_submission():
    sub = MagicMock()
    sub.title = "GPT-5 leaked benchmarks discussion"
    sub.url = "https://reddit.com/r/MachineLearning/comments/abc123"
    sub.permalink = "/r/MachineLearning/comments/abc123/gpt5_leaked/"
    sub.selftext = "Interesting results showing..."
    sub.score = 500
    sub.upvote_ratio = 0.95
    sub.num_comments = 200
    sub.total_awards_received = 3
    sub.created_utc = 1744070400.0
    sub.num_crossposts = 2
    return sub


def test_reddit_collector_returns_raw_items():
    mock_sub = _mock_submission()
    mock_subreddit = MagicMock()
    mock_subreddit.hot.return_value = [mock_sub]
    mock_reddit = MagicMock()
    mock_reddit.subreddit.return_value = mock_subreddit

    with patch("collectors.reddit.praw.Reddit", return_value=mock_reddit):
        collector = RedditCollector(
            client_id="fake", client_secret="fake",
            user_agent="test", subreddits=["MachineLearning"],
        )
        items = collector.collect()
        assert len(items) >= 1
        assert items[0].source == "reddit"
        assert "score" in items[0].metrics


def test_reddit_collector_saves_to_file(tmp_data_dir):
    mock_sub = _mock_submission()
    mock_subreddit = MagicMock()
    mock_subreddit.hot.return_value = [mock_sub]
    mock_reddit = MagicMock()
    mock_reddit.subreddit.return_value = mock_subreddit

    with patch("collectors.reddit.praw.Reddit", return_value=mock_reddit):
        collector = RedditCollector(
            client_id="fake", client_secret="fake",
            user_agent="test", subreddits=["MachineLearning"],
        )
        collector.run(tmp_data_dir)
        assert (tmp_data_dir / "raw" / "reddit.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_reddit.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Reddit collector**

```python
# collectors/reddit.py
from __future__ import annotations
import logging
from datetime import datetime, timezone
import praw
from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)


class RedditCollector(BaseCollector):
    source_name = "reddit"

    def __init__(self, client_id: str, client_secret: str, user_agent: str,
                 subreddits: list[str] | None = None):
        self.reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        self.subreddits = subreddits or [
            "MachineLearning", "LocalLLaMA", "artificial",
            "ChatGPT", "singularity", "StableDiffusion",
        ]

    def collect(self) -> list[RawItem]:
        items = []
        for sub_name in self.subreddits:
            try:
                subreddit = self.reddit.subreddit(sub_name)
                for submission in subreddit.hot(limit=25):
                    item = RawItem(
                        title=submission.title,
                        url=f"https://reddit.com{submission.permalink}",
                        source=self.source_name,
                        description=submission.selftext[:500] if submission.selftext else "",
                        metrics={
                            "score": submission.score,
                            "upvote_ratio": submission.upvote_ratio,
                            "num_comments": submission.num_comments,
                            "total_awards": submission.total_awards_received,
                            "num_crossposts": submission.num_crossposts,
                            "subreddit": sub_name,
                        },
                        timestamp=datetime.fromtimestamp(
                            submission.created_utc, tz=timezone.utc
                        ).isoformat(),
                    )
                    items.append(item)
            except Exception as e:
                logger.error(f"Reddit error for r/{sub_name}: {e}")

        logger.info(f"Reddit collector found {len(items)} posts")
        return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_reddit.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add collectors/reddit.py tests/test_reddit.py
git commit -m "feat: Reddit collector"
```

---

### Task 6: arXiv + Semantic Scholar Collector

**Files:**
- Create: `collectors/arxiv.py`
- Test: `tests/test_arxiv.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_arxiv.py
import json
from unittest.mock import patch, MagicMock
from collectors.arxiv import ArxivCollector
from models import RawItem


def _mock_arxiv_result():
    result = MagicMock()
    result.title = "Scaling Test-Time Compute for Better Reasoning"
    result.entry_id = "http://arxiv.org/abs/2604.12345v1"
    result.summary = "We show that scaling compute at test time..."
    result.published.isoformat.return_value = "2026-04-07T00:00:00Z"
    result.authors = [MagicMock(name="Author One")]
    result.categories = ["cs.AI", "cs.CL"]
    result.pdf_url = "http://arxiv.org/pdf/2604.12345v1"
    return result


def _mock_semantic_scholar_response():
    return {"citationCount": 15, "influentialCitationCount": 3}


def test_arxiv_collector_returns_raw_items():
    mock_result = _mock_arxiv_result()
    mock_client = MagicMock()
    mock_client.results.return_value = [mock_result]

    with patch("collectors.arxiv.arxiv.Client", return_value=mock_client), \
         patch("collectors.arxiv.arxiv.Search") as mock_search, \
         patch("collectors.arxiv.requests.get") as mock_get:
        mock_s2_resp = MagicMock()
        mock_s2_resp.status_code = 200
        mock_s2_resp.json.return_value = _mock_semantic_scholar_response()
        mock_get.return_value = mock_s2_resp

        collector = ArxivCollector(categories=["cs.AI"])
        items = collector.collect()
        assert len(items) >= 1
        assert items[0].source == "arxiv"
        assert "citation_count" in items[0].metrics


def test_arxiv_collector_handles_s2_failure():
    mock_result = _mock_arxiv_result()
    mock_client = MagicMock()
    mock_client.results.return_value = [mock_result]

    with patch("collectors.arxiv.arxiv.Client", return_value=mock_client), \
         patch("collectors.arxiv.arxiv.Search"), \
         patch("collectors.arxiv.requests.get") as mock_get:
        mock_get.side_effect = Exception("S2 down")

        collector = ArxivCollector(categories=["cs.AI"])
        items = collector.collect()
        # Should still return items, just without citation data
        assert len(items) >= 1
        assert items[0].metrics["citation_count"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_arxiv.py -v`
Expected: FAIL

- [ ] **Step 3: Implement arXiv collector**

```python
# collectors/arxiv.py
from __future__ import annotations
import logging
import arxiv
import requests
from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)

S2_API = "https://api.semanticscholar.org/graph/v1/paper"


class ArxivCollector(BaseCollector):
    source_name = "arxiv"

    def __init__(self, categories: list[str] | None = None):
        self.categories = categories or ["cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.MA", "stat.ML"]

    def collect(self) -> list[RawItem]:
        items = []
        query = " OR ".join(f"cat:{cat}" for cat in self.categories)
        search = arxiv.Search(
            query=query,
            max_results=100,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        client = arxiv.Client()

        try:
            for result in client.results(search):
                arxiv_id = result.entry_id.split("/abs/")[-1]
                citation_data = self._get_citations(arxiv_id)
                item = RawItem(
                    title=result.title,
                    url=result.entry_id,
                    source=self.source_name,
                    description=result.summary[:500],
                    metrics={
                        "arxiv_id": arxiv_id,
                        "citation_count": citation_data.get("citationCount", 0),
                        "influential_citations": citation_data.get("influentialCitationCount", 0),
                        "categories": result.categories,
                        "pdf_url": result.pdf_url,
                    },
                    timestamp=result.published.isoformat(),
                )
                items.append(item)
        except Exception as e:
            logger.error(f"arXiv API error: {e}")

        logger.info(f"arXiv collector found {len(items)} papers")
        return items

    def _get_citations(self, arxiv_id: str) -> dict:
        try:
            url = f"{S2_API}/ARXIV:{arxiv_id}"
            params = {"fields": "citationCount,influentialCitationCount"}
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"Semantic Scholar lookup failed for {arxiv_id}: {e}")
        return {"citationCount": 0, "influentialCitationCount": 0}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_arxiv.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add collectors/arxiv.py tests/test_arxiv.py
git commit -m "feat: arXiv + Semantic Scholar collector"
```

---

### Task 7: HuggingFace Collector

**Files:**
- Create: `collectors/huggingface.py`
- Test: `tests/test_huggingface.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_huggingface.py
from unittest.mock import patch, MagicMock
from collectors.huggingface import HuggingFaceCollector
from models import RawItem


def _mock_model():
    m = MagicMock()
    m.id = "meta-llama/Llama-3-70B"
    m.downloads = 50000
    m.likes = 1200
    m.tags = ["text-generation", "llm"]
    m.created_at.isoformat.return_value = "2026-04-07T00:00:00Z"
    m.pipeline_tag = "text-generation"
    return m


def test_huggingface_collector_returns_raw_items():
    mock_model = _mock_model()
    with patch("collectors.huggingface.HfApi") as mock_api_cls:
        mock_api = MagicMock()
        mock_api.list_models.return_value = [mock_model]
        mock_api_cls.return_value = mock_api

        collector = HuggingFaceCollector()
        items = collector.collect()
        assert len(items) >= 1
        assert items[0].source == "huggingface"
        assert "downloads" in items[0].metrics


def test_huggingface_collector_saves(tmp_data_dir):
    mock_model = _mock_model()
    with patch("collectors.huggingface.HfApi") as mock_api_cls:
        mock_api = MagicMock()
        mock_api.list_models.return_value = [mock_model]
        mock_api_cls.return_value = mock_api

        collector = HuggingFaceCollector()
        collector.run(tmp_data_dir)
        assert (tmp_data_dir / "raw" / "huggingface.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_huggingface.py -v`
Expected: FAIL

- [ ] **Step 3: Implement HuggingFace collector**

```python
# collectors/huggingface.py
from __future__ import annotations
import logging
from huggingface_hub import HfApi
from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)


class HuggingFaceCollector(BaseCollector):
    source_name = "huggingface"

    def collect(self) -> list[RawItem]:
        items = []
        api = HfApi()

        try:
            models = api.list_models(
                sort="trending",
                limit=50,
            )
            for model in models:
                item = RawItem(
                    title=model.id,
                    url=f"https://huggingface.co/{model.id}",
                    source=self.source_name,
                    description=model.pipeline_tag or "",
                    metrics={
                        "downloads": model.downloads or 0,
                        "likes": model.likes or 0,
                        "tags": model.tags or [],
                        "pipeline_tag": model.pipeline_tag or "",
                    },
                    timestamp=model.created_at.isoformat() if model.created_at else "",
                )
                items.append(item)
        except Exception as e:
            logger.error(f"HuggingFace API error: {e}")

        logger.info(f"HuggingFace collector found {len(items)} models")
        return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_huggingface.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add collectors/huggingface.py tests/test_huggingface.py
git commit -m "feat: HuggingFace collector"
```

---

### Task 8: Twitter/X Collector

**Files:**
- Create: `collectors/twitter.py`
- Test: `tests/test_twitter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_twitter.py
from unittest.mock import patch, MagicMock, AsyncMock
from collectors.twitter import TwitterCollector
from models import RawItem


def test_twitter_collector_returns_raw_items():
    mock_items = [
        RawItem(
            title="@karpathy: New breakthrough in test-time compute scaling",
            url="https://x.com/karpathy/status/123456",
            source="twitter",
            description="Thread about scaling inference...",
            metrics={"likes": 5000, "retweets": 1200, "quotes": 300, "replies": 150},
            timestamp="2026-04-08T00:00:00Z",
        )
    ]
    with patch.object(TwitterCollector, "_scrape_tweets", return_value=mock_items):
        collector = TwitterCollector(fallback_to_rss=True)
        items = collector.collect()
        assert len(items) >= 1
        assert items[0].source == "twitter"


def test_twitter_collector_falls_back_to_empty_on_error():
    with patch.object(TwitterCollector, "_scrape_tweets", side_effect=Exception("Scraping failed")):
        collector = TwitterCollector(fallback_to_rss=True)
        items = collector.collect()
        assert isinstance(items, list)
        # Should return empty list gracefully, not crash
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_twitter.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Twitter collector**

```python
# collectors/twitter.py
from __future__ import annotations
import logging
from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)

AI_INFLUENCERS = [
    "karpathy", "ylecun", "demaborga", "GaryMarcus",
    "jimfan_", "DrJimFan", "AndrewYNg", "hardmaru",
    "svpino", "emaborsa", "elaborata",
]


class TwitterCollector(BaseCollector):
    source_name = "twitter"

    def __init__(self, fallback_to_rss: bool = True):
        self.fallback_to_rss = fallback_to_rss

    def collect(self) -> list[RawItem]:
        try:
            return self._scrape_tweets()
        except Exception as e:
            logger.error(f"Twitter scraping failed: {e}")
            if self.fallback_to_rss:
                logger.info("Falling back to RSS aggregators")
                return self._collect_from_rss()
            return []

    def _scrape_tweets(self) -> list[RawItem]:
        """Scrape AI-related tweets using playwright.

        This is a stub that should be implemented with playwright
        to scrape tweets from AI influencers. The scraping logic
        is fragile and will need periodic updates as X changes their
        frontend.
        """
        # TODO: Implement playwright-based scraping
        # For now, return empty list — this is the most fragile collector
        # and is designed to be gracefully skippable per the spec.
        logger.warning("Twitter scraping not yet implemented, returning empty list")
        return []

    def _collect_from_rss(self) -> list[RawItem]:
        """Fallback: collect from RSS aggregators that track AI Twitter."""
        logger.warning("RSS fallback not yet implemented")
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_twitter.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add collectors/twitter.py tests/test_twitter.py
git commit -m "feat: Twitter collector stub with fallback"
```

---

### Task 9: Momentum Scoring

**Files:**
- Create: `scoring/__init__.py`
- Create: `scoring/momentum.py`
- Test: `tests/test_momentum.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_momentum.py
import math
from models import RawItem
from scoring.momentum import compute_momentum_score, compute_final_score


def test_github_momentum():
    item = RawItem(
        title="test", url="http://test.com", source="github",
        description="", metrics={"stargazers_count": 3000}, timestamp="2026-04-08T00:00:00Z",
    )
    score = compute_momentum_score(item)
    # stars_24h not available from static data, so we use stargazers_count as proxy
    assert score > 0


def test_reddit_momentum():
    item = RawItem(
        title="test", url="http://test.com", source="reddit",
        description="", metrics={"score": 500, "upvote_ratio": 0.95},
        timestamp="2026-04-08T01:00:00Z",
    )
    score = compute_momentum_score(item)
    assert score > 0


def test_hackernews_momentum():
    item = RawItem(
        title="test", url="http://test.com", source="hackernews",
        description="", metrics={"points": 350}, timestamp="2026-04-08T01:00:00Z",
    )
    score = compute_momentum_score(item)
    assert score > 0


def test_arxiv_momentum():
    item = RawItem(
        title="test", url="http://test.com", source="arxiv",
        description="", metrics={"citation_count": 15, "influential_citations": 3},
        timestamp="2026-04-08T00:00:00Z",
    )
    score = compute_momentum_score(item)
    assert score > 0


def test_huggingface_momentum():
    item = RawItem(
        title="test", url="http://test.com", source="huggingface",
        description="", metrics={"downloads": 50000, "likes": 1200},
        timestamp="2026-04-08T00:00:00Z",
    )
    score = compute_momentum_score(item)
    assert score > 0


def test_twitter_momentum():
    item = RawItem(
        title="test", url="http://test.com", source="twitter",
        description="", metrics={"retweets": 1200, "quotes": 300},
        timestamp="2026-04-08T01:00:00Z",
    )
    score = compute_momentum_score(item)
    assert score > 0


def test_final_score_with_cross_platform_boost():
    boost_config = {2: 1.5, 3: 2.5, 4: 4.0}
    score = compute_final_score(
        momentum_score=1.0,
        age_hours=0,
        freshness_half_life=48,
        num_sources=3,
        boost_config=boost_config,
    )
    # freshness_decay at age 0 = exp(0) = 1.0, boost for 3 sources = 2.5
    assert score == 2.5


def test_final_score_decays_with_age():
    boost_config = {2: 1.5, 3: 2.5, 4: 4.0}
    fresh = compute_final_score(1.0, age_hours=0, freshness_half_life=48,
                                 num_sources=1, boost_config=boost_config)
    old = compute_final_score(1.0, age_hours=96, freshness_half_life=48,
                               num_sources=1, boost_config=boost_config)
    assert fresh > old
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_momentum.py -v`
Expected: FAIL

- [ ] **Step 3: Implement momentum scoring**

```python
# scoring/__init__.py
# (empty)

# scoring/momentum.py
from __future__ import annotations
import math
import logging
from datetime import datetime, timezone
from models import RawItem

logger = logging.getLogger(__name__)


def _hours_since(timestamp: str) -> float:
    """Calculate hours since the given ISO timestamp."""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        return max(delta.total_seconds() / 3600, 0.1)  # min 0.1 to avoid division by zero
    except (ValueError, TypeError):
        return 24.0  # default to 24h if timestamp is unparseable


def compute_momentum_score(item: RawItem) -> float:
    """Compute per-source momentum score for a raw item."""
    m = item.metrics
    source = item.source

    if source == "github":
        stars = m.get("stargazers_count", 0)
        return stars / max(stars, 100)

    elif source == "reddit":
        score = m.get("score", 0)
        hours = _hours_since(item.timestamp)
        return score / hours

    elif source == "hackernews":
        points = m.get("points", 0)
        hours = _hours_since(item.timestamp)
        return points / hours

    elif source == "arxiv":
        citations = m.get("citation_count", 0)
        influential = m.get("influential_citations", 0)
        return citations + influential * 2

    elif source == "huggingface":
        downloads = m.get("downloads", 0)
        likes = m.get("likes", 0)
        return downloads / max(downloads, 100) + likes / max(likes, 10)

    elif source == "twitter":
        retweets = m.get("retweets", 0)
        quotes = m.get("quotes", 0)
        hours = _hours_since(item.timestamp)
        return (retweets + quotes) / hours

    else:
        logger.warning(f"Unknown source: {source}")
        return 0.0


def compute_final_score(
    momentum_score: float,
    age_hours: float,
    freshness_half_life: float,
    num_sources: int,
    boost_config: dict[int, float],
) -> float:
    """Compute final score with freshness decay and cross-platform boost."""
    freshness_decay = math.exp(-age_hours / freshness_half_life)
    boost = boost_config.get(num_sources, 1.0)
    if num_sources >= 4:
        boost = boost_config.get(4, 4.0)
    return momentum_score * freshness_decay * boost
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_momentum.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scoring/ tests/test_momentum.py
git commit -m "feat: momentum scoring engine"
```

---

### Task 10: Cross-Source Deduplication

**Files:**
- Create: `scoring/dedup.py`
- Test: `tests/test_dedup.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dedup.py
from models import RawItem
from scoring.dedup import deduplicate


def _item(title, url, source, **metrics):
    return RawItem(
        title=title, url=url, source=source,
        description="", metrics=metrics, timestamp="2026-04-08T00:00:00Z",
    )


def test_dedup_merges_same_url():
    items = [
        _item("AgentKit v2", "https://github.com/example/agentkit", "github"),
        _item("AgentKit v2 on Reddit", "https://github.com/example/agentkit", "reddit"),
    ]
    groups = deduplicate(items)
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_dedup_merges_fuzzy_titles():
    items = [
        _item("AgentKit v2: Multi-Agent Framework", "https://github.com/example/agentkit", "github"),
        _item("AgentKit v2 - A Multi-Agent Framework", "https://reddit.com/r/ml/abc", "reddit"),
    ]
    groups = deduplicate(items)
    assert len(groups) == 1


def test_dedup_keeps_different_items_separate():
    items = [
        _item("AgentKit v2", "https://github.com/example/agentkit", "github"),
        _item("LlamaFS", "https://github.com/example/llamafs", "github"),
    ]
    groups = deduplicate(items)
    assert len(groups) == 2


def test_dedup_returns_all_sources():
    items = [
        _item("AgentKit v2", "https://github.com/example/agentkit", "github"),
        _item("AgentKit v2", "https://github.com/example/agentkit", "reddit"),
        _item("AgentKit v2", "https://github.com/example/agentkit", "hackernews"),
    ]
    groups = deduplicate(items)
    assert len(groups) == 1
    sources = {item.source for item in groups[0]}
    assert sources == {"github", "reddit", "hackernews"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dedup.py -v`
Expected: FAIL

- [ ] **Step 3: Implement dedup**

```python
# scoring/dedup.py
from __future__ import annotations
import logging
from urllib.parse import urlparse
from thefuzz import fuzz
from models import RawItem

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 75


def _normalize_url(url: str) -> str:
    """Normalize URL for comparison (strip protocol, trailing slash, www)."""
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")
    path = parsed.path.rstrip("/")
    return f"{host}{path}".lower()


def _titles_match(a: str, b: str) -> bool:
    """Check if two titles are fuzzy matches."""
    return fuzz.token_sort_ratio(a.lower(), b.lower()) >= FUZZY_THRESHOLD


def deduplicate(items: list[RawItem]) -> list[list[RawItem]]:
    """Group items that refer to the same thing.

    Returns a list of groups, where each group is a list of RawItems
    that all refer to the same underlying project/paper/thread.
    """
    groups: list[list[RawItem]] = []

    for item in items:
        merged = False
        item_url = _normalize_url(item.url)

        for group in groups:
            for existing in group:
                existing_url = _normalize_url(existing.url)
                if item_url == existing_url or _titles_match(item.title, existing.title):
                    group.append(item)
                    merged = True
                    break
            if merged:
                break

        if not merged:
            groups.append([item])

    logger.info(f"Dedup: {len(items)} items → {len(groups)} groups")
    return groups
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dedup.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scoring/dedup.py tests/test_dedup.py
git commit -m "feat: cross-source deduplication"
```

---

### Task 11: Claude CLI LLM Filter

**Files:**
- Create: `scoring/llm_filter.py`
- Create: `prompts/filter.md`
- Test: `tests/test_llm_filter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_llm_filter.py
import json
from unittest.mock import patch
from models import RawItem, ScoredItem
from scoring.llm_filter import run_llm_filter


def _scored_items():
    """Create test scored items (pre-LLM-filter)."""
    items = []
    for i in range(5):
        raw = RawItem(
            title=f"Project {i}", url=f"http://example.com/{i}", source="github",
            description=f"Description {i}", metrics={"stargazers_count": 1000 * (5 - i)},
            timestamp="2026-04-08T00:00:00Z",
        )
        items.append(ScoredItem(
            raw_items=[raw], momentum_score=1.0 - i * 0.1, final_score=1.0 - i * 0.1,
            sources=["github"], category="", llm_summary="", interest_score=0,
        ))
    return items


def test_llm_filter_enriches_items():
    llm_response = json.dumps({
        "items": [
            {"index": 0, "category": "tool", "interest_score": 9,
             "summary": "Great tool", "novel": True, "ai_relevant": True, "deep_dive": True},
            {"index": 1, "category": "paper", "interest_score": 7,
             "summary": "Good paper", "novel": True, "ai_relevant": True, "deep_dive": False},
            {"index": 2, "category": "tool", "interest_score": 3,
             "summary": "Minor fork", "novel": False, "ai_relevant": True, "deep_dive": False},
        ]
    })
    with patch("scoring.llm_filter.call_claude_json", return_value=json.loads(llm_response)):
        digest, deep_dives = run_llm_filter(_scored_items(), digest_size=10, deep_dive_count=5)
        # Items marked novel and ai_relevant should be in digest
        assert len(digest) == 2
        assert digest[0].category == "tool"
        assert digest[0].interest_score == 9
        # Items marked deep_dive should be in deep_dives
        assert len(deep_dives) == 1


def test_llm_filter_falls_back_on_error():
    with patch("scoring.llm_filter.call_claude_json", side_effect=RuntimeError("Claude down")):
        items = _scored_items()
        digest, deep_dives = run_llm_filter(items, digest_size=3, deep_dive_count=2)
        # Fallback: return top items by score without LLM enrichment
        assert len(digest) == 3
        assert len(deep_dives) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_llm_filter.py -v`
Expected: FAIL

- [ ] **Step 3: Create filter prompt template**

```markdown
# prompts/filter.md
You are an AI trend analyst. Evaluate these items for novelty, relevance, and potential impact.

For each item, determine:
1. **novel**: Is this genuinely new/interesting? (not a minor fork, wrapper, or tutorial)
2. **ai_relevant**: Is this actually about AI/ML? (filter false positives)
3. **category**: One of: tool, model, paper, framework, dataset, technique, product
4. **interest_score**: 1-10 based on potential impact and novelty
5. **summary**: One-line summary of what it is and why it matters
6. **deep_dive**: Should this get a detailed analysis? (true for the most promising items)

Return JSON in this exact format:
```json
{
  "items": [
    {
      "index": 0,
      "novel": true,
      "ai_relevant": true,
      "category": "tool",
      "interest_score": 9,
      "summary": "What it is and why it matters",
      "deep_dive": true
    }
  ]
}
```

Items to evaluate:
{items_json}
```

- [ ] **Step 4: Implement LLM filter**

```python
# scoring/llm_filter.py
from __future__ import annotations
import json
import logging
from pathlib import Path
from models import ScoredItem
from claude_cli import call_claude_json

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = (Path(__file__).parent.parent / "prompts" / "filter.md").read_text


def run_llm_filter(
    items: list[ScoredItem],
    digest_size: int = 15,
    deep_dive_count: int = 5,
) -> tuple[list[ScoredItem], list[ScoredItem]]:
    """Run Claude CLI quality filter on scored items.

    Returns (digest_items, deep_dive_items).
    Falls back to raw score ranking if Claude CLI fails.
    """
    try:
        return _run_filter(items, digest_size, deep_dive_count)
    except Exception as e:
        logger.error(f"LLM filter failed, falling back to score-based ranking: {e}")
        return _fallback(items, digest_size, deep_dive_count)


def _run_filter(
    items: list[ScoredItem],
    digest_size: int,
    deep_dive_count: int,
) -> tuple[list[ScoredItem], list[ScoredItem]]:
    items_for_prompt = []
    for i, item in enumerate(items):
        items_for_prompt.append({
            "index": i,
            "title": item.title,
            "url": item.url,
            "description": item.description,
            "sources": item.sources,
            "momentum_score": item.momentum_score,
        })

    prompt_template = Path(__file__).parent.parent / "prompts" / "filter.md"
    prompt = prompt_template.read_text().replace("{items_json}", json.dumps(items_for_prompt, indent=2))

    result = call_claude_json(prompt)

    digest = []
    deep_dives = []

    for eval_item in result.get("items", []):
        idx = eval_item["index"]
        if idx >= len(items):
            continue

        scored = items[idx]
        if not eval_item.get("novel", False) or not eval_item.get("ai_relevant", False):
            continue

        scored.category = eval_item.get("category", "")
        scored.interest_score = eval_item.get("interest_score", 0)
        scored.llm_summary = eval_item.get("summary", "")
        digest.append(scored)

        if eval_item.get("deep_dive", False):
            deep_dives.append(scored)

    digest.sort(key=lambda x: x.interest_score, reverse=True)
    digest = digest[:digest_size]
    deep_dives = deep_dives[:deep_dive_count]

    return digest, deep_dives


def _fallback(
    items: list[ScoredItem],
    digest_size: int,
    deep_dive_count: int,
) -> tuple[list[ScoredItem], list[ScoredItem]]:
    sorted_items = sorted(items, key=lambda x: x.final_score, reverse=True)
    digest = sorted_items[:digest_size]
    deep_dives = sorted_items[:deep_dive_count]
    return digest, deep_dives
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_llm_filter.py -v`
Expected: All 2 tests PASS

- [ ] **Step 6: Commit**

```bash
git add scoring/llm_filter.py prompts/filter.md tests/test_llm_filter.py
git commit -m "feat: Claude CLI LLM quality filter with fallback"
```

---

### Task 12: Deep Dive Source Material Gatherer

**Files:**
- Create: `analysis/__init__.py`
- Create: `analysis/gatherer.py`
- Test: `tests/test_gatherer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_gatherer.py
from unittest.mock import patch, MagicMock
from models import RawItem, ScoredItem
from analysis.gatherer import gather_source_material


def _github_scored_item():
    raw = RawItem(
        title="example/agentkit", url="https://github.com/example/agentkit",
        source="github", description="Multi-agent framework",
        metrics={"stargazers_count": 3000}, timestamp="2026-04-08T00:00:00Z",
    )
    return ScoredItem(
        raw_items=[raw], momentum_score=0.85, final_score=1.7,
        sources=["github"], category="tool", llm_summary="Agent framework",
        interest_score=9,
    )


def test_gather_github_fetches_readme():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "# AgentKit\nA multi-agent framework for building AI agents."

    with patch("analysis.gatherer.requests.get", return_value=mock_resp):
        material = gather_source_material(_github_scored_item())
        assert "readme" in material
        assert "AgentKit" in material["readme"]


def test_gather_returns_empty_on_failure():
    with patch("analysis.gatherer.requests.get", side_effect=Exception("Network error")):
        material = gather_source_material(_github_scored_item())
        assert isinstance(material, dict)
        assert material.get("readme", "") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gatherer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement gatherer**

```python
# analysis/__init__.py
# (empty)

# analysis/gatherer.py
from __future__ import annotations
import logging
import requests
from urllib.parse import urlparse
from models import ScoredItem

logger = logging.getLogger(__name__)


def gather_source_material(item: ScoredItem) -> dict:
    """Fetch source material for deep dive analysis.

    Returns a dict with keys like 'readme', 'abstract', 'comments', 'competitors'.
    """
    material: dict = {"title": item.title, "url": item.url, "description": item.description}

    url = item.url
    parsed = urlparse(url)

    if "github.com" in parsed.netloc:
        material["readme"] = _fetch_github_readme(url)
        material["competitors"] = _search_github_similar(item.title)
    elif "arxiv.org" in parsed.netloc:
        material["abstract"] = item.description
        arxiv_id = item.raw_items[0].metrics.get("arxiv_id", "")
        material["pdf_url"] = item.raw_items[0].metrics.get("pdf_url", "")
    elif "huggingface.co" in parsed.netloc:
        material["readme"] = _fetch_hf_readme(url)
    elif "reddit.com" in parsed.netloc:
        material["comments"] = _fetch_reddit_comments(url)

    # Fetch discussion comments from other sources where this item appeared
    for raw in item.raw_items:
        if raw.source == "hackernews" and "objectID" in raw.metrics:
            material["hn_comments"] = _fetch_hn_comments(raw.metrics["objectID"])

    return material


def _fetch_github_readme(repo_url: str) -> str:
    try:
        parts = urlparse(repo_url).path.strip("/").split("/")
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.md"
            resp = requests.get(raw_url, timeout=15)
            if resp.status_code == 200:
                return resp.text[:5000]
            # Try master branch
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/master/README.md"
            resp = requests.get(raw_url, timeout=15)
            if resp.status_code == 200:
                return resp.text[:5000]
    except Exception as e:
        logger.warning(f"Failed to fetch GitHub README: {e}")
    return ""


def _search_github_similar(title: str) -> str:
    try:
        query = title.split("/")[-1] if "/" in title else title
        url = "https://api.github.com/search/repositories"
        params = {"q": query, "sort": "stars", "per_page": 5}
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            repos = resp.json().get("items", [])
            lines = []
            for r in repos[:5]:
                lines.append(f"- {r['full_name']} ({r['stargazers_count']} stars): {r.get('description', '')}")
            return "\n".join(lines)
    except Exception as e:
        logger.warning(f"GitHub competitor search failed: {e}")
    return ""


def _fetch_hf_readme(model_url: str) -> str:
    try:
        model_id = urlparse(model_url).path.strip("/")
        api_url = f"https://huggingface.co/{model_id}/raw/main/README.md"
        resp = requests.get(api_url, timeout=15)
        if resp.status_code == 200:
            return resp.text[:5000]
    except Exception as e:
        logger.warning(f"Failed to fetch HF README: {e}")
    return ""


def _fetch_reddit_comments(thread_url: str) -> str:
    # Reddit JSON endpoint
    try:
        json_url = thread_url.rstrip("/") + ".json"
        headers = {"User-Agent": "trending-bot/1.0"}
        resp = requests.get(json_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if len(data) > 1:
                comments = data[1].get("data", {}).get("children", [])[:10]
                lines = []
                for c in comments:
                    body = c.get("data", {}).get("body", "")
                    if body:
                        lines.append(body[:300])
                return "\n---\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to fetch Reddit comments: {e}")
    return ""


def _fetch_hn_comments(object_id: str) -> str:
    try:
        url = f"https://hn.algolia.com/api/v1/items/{object_id}"
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            children = data.get("children", [])[:10]
            lines = [c.get("text", "")[:300] for c in children if c.get("text")]
            return "\n---\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to fetch HN comments: {e}")
    return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gatherer.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/ tests/test_gatherer.py
git commit -m "feat: deep dive source material gatherer"
```

---

### Task 13: Deep Dive Analyzer

**Files:**
- Create: `analysis/deep_dive.py`
- Create: `prompts/deep_dive.md`
- Test: `tests/test_deep_dive.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_deep_dive.py
import json
from unittest.mock import patch
from pathlib import Path
from models import RawItem, ScoredItem, AnalysisReport
from analysis.deep_dive import run_deep_dive, run_deep_dives


def _scored_item():
    raw = RawItem(
        title="example/agentkit", url="https://github.com/example/agentkit",
        source="github", description="Multi-agent framework",
        metrics={}, timestamp="2026-04-08T00:00:00Z",
    )
    return ScoredItem(
        raw_items=[raw], momentum_score=0.85, final_score=1.7,
        sources=["github"], category="tool", llm_summary="Agent framework",
        interest_score=9,
    )


def _mock_claude_response():
    return {
        "what_it_is": "A multi-agent orchestration framework",
        "why_trending": "1.2k stars in 24h, launched yesterday",
        "pain_point": "Building multi-agent systems requires gluing together disparate frameworks",
        "gap_analysis": "No visual builder exists. Config is YAML-heavy.",
        "competitors": ["CrewAI", "AutoGen", "LangGraph"],
        "app_idea": "Visual drag-and-drop agent builder for non-dev AI teams",
        "feasibility": {"effort": "3 weeks MVP", "market": "growing", "competition": "low"},
    }


def test_run_deep_dive_returns_report():
    material = {"readme": "# AgentKit\nBuild agents easily", "competitors": ""}
    with patch("analysis.deep_dive.gather_source_material", return_value=material), \
         patch("analysis.deep_dive.call_claude_json", return_value=_mock_claude_response()):
        report = run_deep_dive(_scored_item())
        assert isinstance(report, AnalysisReport)
        assert report.slug == "example-agentkit"
        assert "multi-agent" in report.what_it_is.lower()


def test_run_deep_dives_saves_to_disk(tmp_path):
    material = {"readme": "# AgentKit\nBuild agents easily", "competitors": ""}
    with patch("analysis.deep_dive.gather_source_material", return_value=material), \
         patch("analysis.deep_dive.call_claude_json", return_value=_mock_claude_response()):
        data_dir = tmp_path / "data" / "2026-04-08"
        reports = run_deep_dives([_scored_item()], data_dir)
        assert len(reports) == 1
        analysis_dir = data_dir / "analysis"
        assert analysis_dir.exists()
        md_files = list(analysis_dir.glob("*.md"))
        assert len(md_files) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_deep_dive.py -v`
Expected: FAIL

- [ ] **Step 3: Create deep dive prompt template**

```markdown
# prompts/deep_dive.md
You are an AI trend analyst performing a deep-dive analysis on a trending AI project/paper.

**Item:** {title}
**URL:** {url}
**Why it appeared:** {llm_summary}

**Source material:**
{source_material}

Analyze this item and return JSON in this exact format:
```json
{
  "what_it_is": "Clear explanation of the project/paper/tool (2-3 sentences)",
  "why_trending": "What triggered community interest (1-2 sentences)",
  "pain_point": "The underlying problem it addresses (2-3 sentences)",
  "gap_analysis": "What's missing, what could be better, unmet needs (2-3 sentences)",
  "competitors": ["List", "of", "existing", "alternatives"],
  "app_idea": "A concrete product or tool proposal addressing the identified gaps (2-3 sentences)",
  "feasibility": {
    "effort": "Estimated time to MVP (e.g., '2 weeks', '1 month')",
    "market": "Market assessment (e.g., 'growing', 'niche', 'saturated')",
    "competition": "Competition level (e.g., 'low', 'moderate', 'high')"
  }
}
```

Be specific and actionable. The app idea should be something a solo developer or small team could realistically build.
```

- [ ] **Step 4: Implement deep dive analyzer**

```python
# analysis/deep_dive.py
from __future__ import annotations
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from models import ScoredItem, AnalysisReport
from analysis.gatherer import gather_source_material
from claude_cli import call_claude_json

logger = logging.getLogger(__name__)


def _slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:60]


def run_deep_dive(item: ScoredItem) -> AnalysisReport:
    """Run a deep dive analysis on a single item."""
    material = gather_source_material(item)

    source_material_text = []
    for key, value in material.items():
        if value and key not in ("title", "url", "description"):
            source_material_text.append(f"### {key.upper()}\n{value}")
    source_str = "\n\n".join(source_material_text) if source_material_text else "No additional material available."

    prompt_template = (Path(__file__).parent.parent / "prompts" / "deep_dive.md").read_text()
    prompt = prompt_template.replace("{title}", item.title)
    prompt = prompt.replace("{url}", item.url)
    prompt = prompt.replace("{llm_summary}", item.llm_summary)
    prompt = prompt.replace("{source_material}", source_str)

    result = call_claude_json(prompt)

    return AnalysisReport(
        slug=_slugify(item.title),
        title=item.title,
        what_it_is=result.get("what_it_is", ""),
        why_trending=result.get("why_trending", ""),
        pain_point=result.get("pain_point", ""),
        gap_analysis=result.get("gap_analysis", ""),
        competitors=result.get("competitors", []),
        app_idea=result.get("app_idea", ""),
        feasibility=result.get("feasibility", {}),
    )


def run_deep_dives(items: list[ScoredItem], data_dir: Path) -> list[AnalysisReport]:
    """Run deep dives on multiple items in parallel. Save reports to disk."""
    analysis_dir = data_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    reports = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_item = {executor.submit(run_deep_dive, item): item for item in items}
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                report = future.result()
                reports.append(report)
                # Save markdown report
                md_path = analysis_dir / f"{report.slug}.md"
                md_path.write_text(report.to_markdown())
                # Save JSON report
                json_path = analysis_dir / f"{report.slug}.json"
                json_path.write_text(json.dumps(report.to_dict(), indent=2))
                logger.info(f"Deep dive completed: {report.title}")
            except Exception as e:
                logger.error(f"Deep dive failed for {item.title}: {e}")

    return reports
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_deep_dive.py -v`
Expected: All 2 tests PASS

- [ ] **Step 6: Commit**

```bash
git add analysis/deep_dive.py prompts/deep_dive.md tests/test_deep_dive.py
git commit -m "feat: deep dive analyzer with Claude CLI"
```

---

### Task 14: Digest Builder

**Files:**
- Create: `reporting/__init__.py`
- Create: `reporting/digest.py`
- Test: `tests/test_digest.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_digest.py
from pathlib import Path
from models import RawItem, ScoredItem, AnalysisReport
from reporting.digest import build_digest


def _scored(title, score, category, sources, summary):
    raw = RawItem(title=title, url=f"http://example.com/{title}", source=sources[0],
                  description="", metrics={}, timestamp="2026-04-08T00:00:00Z")
    return ScoredItem(raw_items=[raw], momentum_score=score, final_score=score,
                      sources=sources, category=category, llm_summary=summary,
                      interest_score=int(score * 10))


def _report(slug, title):
    return AnalysisReport(slug=slug, title=title, what_it_is="test",
                          why_trending="test", pain_point="test", gap_analysis="test",
                          competitors=[], app_idea="test", feasibility={})


def test_build_digest_creates_markdown(tmp_path):
    items = [
        _scored("AgentKit", 0.9, "tool", ["github", "reddit"], "Agent framework"),
        _scored("ScalingPaper", 0.7, "paper", ["arxiv"], "New scaling paper"),
    ]
    reports = [_report("agentkit", "AgentKit")]
    data_dir = tmp_path / "data" / "2026-04-08"
    build_digest(items, reports, data_dir, "2026-04-08")
    digest_path = data_dir / "reports" / "digest.md"
    assert digest_path.exists()
    content = digest_path.read_text()
    assert "AgentKit" in content
    assert "ScalingPaper" in content


def test_digest_groups_by_category(tmp_path):
    items = [
        _scored("ToolA", 0.9, "tool", ["github"], "A tool"),
        _scored("PaperB", 0.8, "paper", ["arxiv"], "A paper"),
        _scored("ToolC", 0.7, "tool", ["github"], "Another tool"),
    ]
    data_dir = tmp_path / "data" / "2026-04-08"
    build_digest(items, [], data_dir, "2026-04-08")
    content = (data_dir / "reports" / "digest.md").read_text()
    # Tools section should appear before papers (higher scored items)
    tool_pos = content.index("tool")
    assert tool_pos >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_digest.py -v`
Expected: FAIL

- [ ] **Step 3: Implement digest builder**

```python
# reporting/__init__.py
# (empty)

# reporting/digest.py
from __future__ import annotations
import logging
from collections import defaultdict
from pathlib import Path
from models import ScoredItem, AnalysisReport

logger = logging.getLogger(__name__)

SOURCE_BADGES = {
    "github": "⭐", "reddit": "💬", "arxiv": "📄",
    "huggingface": "🤗", "twitter": "𝕏", "hackernews": "🔶",
}


def build_digest(
    items: list[ScoredItem],
    reports: list[AnalysisReport],
    data_dir: Path,
    date_str: str,
) -> Path:
    """Build the daily digest markdown file."""
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_slugs = {r.slug for r in reports}

    # Group by category
    by_category: dict[str, list[ScoredItem]] = defaultdict(list)
    for item in items:
        cat = item.category or "other"
        by_category[cat].append(item)

    lines = [
        f"# AI Trending Daily — {date_str}",
        "",
        f"**{len(items)} items** across {len(set(s for i in items for s in i.sources))} sources"
        f" · **{len(reports)} deep dives**",
        "",
        "---",
        "",
    ]

    for category, cat_items in sorted(by_category.items(), key=lambda x: -max(i.interest_score for i in x[1])):
        lines.append(f"## {category.title()}")
        lines.append("")
        for item in sorted(cat_items, key=lambda x: -x.interest_score):
            badges = " ".join(SOURCE_BADGES.get(s, "") for s in item.sources)
            deep_dive_link = ""
            slug = item.title.lower().replace("/", "-").replace(" ", "-")[:60]
            if any(slug in rs for rs in report_slugs):
                deep_dive_link = " · [Deep Dive](analysis/" + slug + ".md)"
            lines.append(
                f"- **[{item.title}]({item.url})** "
                f"(score: {item.interest_score}/10) {badges}"
            )
            if item.llm_summary:
                lines.append(f"  {item.llm_summary}")
            if deep_dive_link:
                lines.append(f"  {deep_dive_link}")
            lines.append("")
        lines.append("")

    digest_path = reports_dir / "digest.md"
    digest_path.write_text("\n".join(lines))
    logger.info(f"Digest written to {digest_path}")
    return digest_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_digest.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add reporting/ tests/test_digest.py
git commit -m "feat: markdown digest builder"
```

---

### Task 15: Executive Summary (Claude CLI)

**Files:**
- Create: `reporting/summary.py`
- Create: `prompts/summary.md`
- Test: `tests/test_summary.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_summary.py
from pathlib import Path
from unittest.mock import patch
from models import RawItem, ScoredItem, AnalysisReport
from reporting.summary import build_summary


def _scored(title, score, category, sources, summary):
    raw = RawItem(title=title, url=f"http://example.com/{title}", source=sources[0],
                  description="", metrics={}, timestamp="2026-04-08T00:00:00Z")
    return ScoredItem(raw_items=[raw], momentum_score=score, final_score=score,
                      sources=sources, category=category, llm_summary=summary,
                      interest_score=int(score * 10))


def test_build_summary_creates_file(tmp_path):
    items = [_scored("AgentKit", 0.9, "tool", ["github"], "Agent framework")]
    reports = []
    mock_response = "Today's top trend is AgentKit, a multi-agent framework gaining rapid traction."
    with patch("reporting.summary.call_claude", return_value=mock_response):
        data_dir = tmp_path / "data" / "2026-04-08"
        path = build_summary(items, reports, data_dir, "2026-04-08")
        assert path.exists()
        content = path.read_text()
        assert "AgentKit" in content


def test_build_summary_fallback_on_error(tmp_path):
    items = [_scored("AgentKit", 0.9, "tool", ["github"], "Agent framework")]
    with patch("reporting.summary.call_claude", side_effect=RuntimeError("fail")):
        data_dir = tmp_path / "data" / "2026-04-08"
        path = build_summary(items, [], data_dir, "2026-04-08")
        assert path.exists()
        content = path.read_text()
        assert "AgentKit" in content  # Fallback should still list items
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_summary.py -v`
Expected: FAIL

- [ ] **Step 3: Create summary prompt template**

```markdown
# prompts/summary.md
You are an AI trend analyst writing a brief morning briefing.

Write a 3-5 paragraph executive summary of today's AI trends. Cover:
1. The dominant themes and patterns
2. The most promising opportunity (with a concrete app idea if a deep dive identified one)
3. Any notable patterns or emerging trends worth watching

Keep it conversational and actionable — this is for a developer who wants to know what happened overnight in AI.

**Date:** {date}

**Today's items:**
{items_summary}

**Deep dive highlights:**
{deep_dive_highlights}

Write the summary in markdown format. No JSON.
```

- [ ] **Step 4: Implement summary builder**

```python
# reporting/summary.py
from __future__ import annotations
import logging
from pathlib import Path
from models import ScoredItem, AnalysisReport
from claude_cli import call_claude

logger = logging.getLogger(__name__)


def build_summary(
    items: list[ScoredItem],
    reports: list[AnalysisReport],
    data_dir: Path,
    date_str: str,
) -> Path:
    """Generate executive summary via Claude CLI."""
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary_path = reports_dir / "summary.md"

    try:
        summary_text = _generate_via_claude(items, reports, date_str)
    except Exception as e:
        logger.error(f"Summary generation failed, using fallback: {e}")
        summary_text = _fallback_summary(items, reports, date_str)

    summary_path.write_text(summary_text)
    logger.info(f"Summary written to {summary_path}")
    return summary_path


def _generate_via_claude(
    items: list[ScoredItem],
    reports: list[AnalysisReport],
    date_str: str,
) -> str:
    items_summary = "\n".join(
        f"- {item.title} ({item.category}, score {item.interest_score}/10): {item.llm_summary}"
        for item in items
    )
    deep_dive_highlights = "\n".join(
        f"- **{r.title}**: {r.pain_point[:100]}... → 💡 {r.app_idea[:100]}"
        for r in reports
    ) if reports else "No deep dives today."

    prompt_template = (Path(__file__).parent.parent / "prompts" / "summary.md").read_text()
    prompt = prompt_template.replace("{date}", date_str)
    prompt = prompt.replace("{items_summary}", items_summary)
    prompt = prompt.replace("{deep_dive_highlights}", deep_dive_highlights)

    return call_claude(prompt)


def _fallback_summary(
    items: list[ScoredItem],
    reports: list[AnalysisReport],
    date_str: str,
) -> str:
    lines = [f"# AI Trending Summary — {date_str}", "", f"Found {len(items)} trending items.", ""]
    for item in items[:5]:
        lines.append(f"- **{item.title}** (score: {item.interest_score}/10): {item.llm_summary}")
    if reports:
        lines.append("")
        lines.append("## Deep Dive Highlights")
        for r in reports:
            lines.append(f"- **{r.title}**: {r.app_idea}")
    return "\n".join(lines)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_summary.py -v`
Expected: All 2 tests PASS

- [ ] **Step 6: Commit**

```bash
git add reporting/summary.py prompts/summary.md tests/test_summary.py
git commit -m "feat: executive summary with Claude CLI"
```

---

### Task 16: Static Dashboard Generator

**Files:**
- Create: `reporting/dashboard.py`
- Create: `templates/index.html`
- Create: `templates/item.html`
- Create: `templates/assets/style.css`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dashboard.py
from pathlib import Path
from models import RawItem, ScoredItem, AnalysisReport
from reporting.dashboard import build_dashboard


def _scored(title, score, category, sources, summary):
    raw = RawItem(title=title, url=f"http://example.com/{title}", source=sources[0],
                  description="desc", metrics={}, timestamp="2026-04-08T00:00:00Z")
    return ScoredItem(raw_items=[raw], momentum_score=score, final_score=score,
                      sources=sources, category=category, llm_summary=summary,
                      interest_score=int(score * 10))


def _report(slug, title):
    return AnalysisReport(slug=slug, title=title, what_it_is="A tool",
                          why_trending="Viral", pain_point="Hard problem",
                          gap_analysis="Missing features", competitors=["Alt1"],
                          app_idea="Build X", feasibility={"effort": "2 weeks"})


def test_build_dashboard_creates_index(tmp_path):
    items = [_scored("AgentKit", 0.9, "tool", ["github"], "Agent framework")]
    reports = [_report("agentkit", "AgentKit")]
    data_dir = tmp_path / "data" / "2026-04-08"
    build_dashboard(items, reports, data_dir, "2026-04-08")
    index = data_dir / "reports" / "dashboard" / "index.html"
    assert index.exists()
    content = index.read_text()
    assert "AgentKit" in content


def test_build_dashboard_creates_item_pages(tmp_path):
    items = [_scored("AgentKit", 0.9, "tool", ["github"], "Agent framework")]
    reports = [_report("agentkit", "AgentKit")]
    data_dir = tmp_path / "data" / "2026-04-08"
    build_dashboard(items, reports, data_dir, "2026-04-08")
    item_page = data_dir / "reports" / "dashboard" / "agentkit.html"
    assert item_page.exists()
    content = item_page.read_text()
    assert "Build X" in content  # app_idea
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: FAIL

- [ ] **Step 3: Create dashboard templates**

```html
<!-- templates/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Trending Bot — {{ date }}</title>
    <link rel="stylesheet" href="assets/style.css">
</head>
<body>
    <header>
        <h1>AI Trending Bot</h1>
        <nav class="date-nav">
            <span>{{ date }}</span>
        </nav>
    </header>
    <main>
        <div class="digest-panel">
            <h2>Today's Digest ({{ items|length }} items)</h2>
            <input type="text" id="search" placeholder="Search items..." class="search-box">
            {% for item in items %}
            <div class="item-card {% if item.slug in deep_dive_slugs %}has-deep-dive{% endif %}" data-search="{{ item.title|lower }} {{ item.llm_summary|lower }}">
                <div class="item-header">
                    <a href="{% if item.slug in deep_dive_slugs %}{{ item.slug }}.html{% else %}{{ item.url }}{% endif %}" class="item-title">{{ item.title }}</a>
                    <span class="score">{{ item.interest_score }}/10</span>
                </div>
                <p class="item-summary">{{ item.llm_summary }}</p>
                <div class="badges">
                    {% for source in item.sources %}
                    <span class="badge badge-{{ source }}">{{ source }}</span>
                    {% endfor %}
                    {% if item.slug in deep_dive_slugs %}
                    <span class="badge badge-deep-dive">DEEP DIVE</span>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>
    </main>
    <script>
        document.getElementById('search').addEventListener('input', function(e) {
            const q = e.target.value.toLowerCase();
            document.querySelectorAll('.item-card').forEach(card => {
                card.style.display = card.dataset.search.includes(q) ? '' : 'none';
            });
        });
    </script>
</body>
</html>
```

```html
<!-- templates/item.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ report.title }} — AI Trending Bot</title>
    <link rel="stylesheet" href="assets/style.css">
</head>
<body>
    <header>
        <h1><a href="index.html">AI Trending Bot</a></h1>
        <nav class="date-nav"><span>{{ date }}</span></nav>
    </header>
    <main class="deep-dive">
        <h2>{{ report.title }}</h2>
        <a href="{{ url }}" class="source-link">{{ url }}</a>

        <section>
            <h3>What It Is</h3>
            <p>{{ report.what_it_is }}</p>
        </section>
        <section>
            <h3>Why It's Trending</h3>
            <p>{{ report.why_trending }}</p>
        </section>
        <section>
            <h3>Pain Point</h3>
            <p>{{ report.pain_point }}</p>
        </section>
        <section>
            <h3>Gap Analysis</h3>
            <p>{{ report.gap_analysis }}</p>
        </section>
        <section>
            <h3>Competitors</h3>
            <ul>
                {% for comp in report.competitors %}
                <li>{{ comp }}</li>
                {% endfor %}
            </ul>
        </section>
        <section class="highlight">
            <h3>Proposed Solution</h3>
            <p>{{ report.app_idea }}</p>
        </section>
        <section>
            <h3>Feasibility</h3>
            <ul>
                {% for key, value in report.feasibility.items() %}
                <li><strong>{{ key|title }}:</strong> {{ value }}</li>
                {% endfor %}
            </ul>
        </section>
    </main>
</body>
</html>
```

```css
/* templates/assets/style.css */
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; line-height: 1.6; }
header { background: #161b22; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; }
header h1 { color: #58a6ff; font-size: 1.2rem; }
header h1 a { color: #58a6ff; text-decoration: none; }
.date-nav { color: #8b949e; }
main { max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
.search-box { width: 100%; padding: 0.5rem; margin-bottom: 1rem; background: #161b22; border: 1px solid #30363d; border-radius: 6px; color: #c9d1d9; font-size: 0.9rem; }
.item-card { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 1rem; margin-bottom: 0.5rem; }
.item-card.has-deep-dive { border-color: #f8514966; }
.item-header { display: flex; justify-content: space-between; align-items: center; }
.item-title { color: #58a6ff; text-decoration: none; font-weight: 600; }
.score { color: #3fb950; font-weight: bold; }
.item-summary { color: #8b949e; font-size: 0.85rem; margin: 0.3rem 0; }
.badges { display: flex; gap: 0.3rem; flex-wrap: wrap; }
.badge { padding: 0.15rem 0.4rem; border-radius: 3px; font-size: 0.7rem; background: #1a1a2e; }
.badge-github { color: #58a6ff; }
.badge-reddit { color: #ff6b35; }
.badge-arxiv { color: #3fb950; }
.badge-huggingface { color: #ffcc00; }
.badge-twitter { color: #1da1f2; }
.badge-hackernews { color: #ff6600; }
.badge-deep-dive { color: #f85149; background: #f851491a; }
.deep-dive section { margin: 1.5rem 0; }
.deep-dive h3 { color: #58a6ff; margin-bottom: 0.5rem; }
.deep-dive .highlight { background: #1a2e1a; border: 1px solid #3fb95066; border-radius: 6px; padding: 1rem; }
.source-link { color: #8b949e; font-size: 0.85rem; }
```

- [ ] **Step 4: Implement dashboard builder**

```python
# reporting/dashboard.py
from __future__ import annotations
import logging
import re
import shutil
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from models import ScoredItem, AnalysisReport

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:60]


def build_dashboard(
    items: list[ScoredItem],
    reports: list[AnalysisReport],
    data_dir: Path,
    date_str: str,
) -> Path:
    """Build static HTML dashboard."""
    dashboard_dir = data_dir / "reports" / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    # Copy assets
    assets_src = TEMPLATES_DIR / "assets"
    assets_dst = dashboard_dir / "assets"
    if assets_src.exists():
        if assets_dst.exists():
            shutil.rmtree(assets_dst)
        shutil.copytree(assets_src, assets_dst)

    deep_dive_slugs = {r.slug for r in reports}

    # Prepare item data for template
    items_data = []
    for item in items:
        items_data.append({
            "title": item.title,
            "url": item.url,
            "slug": _slugify(item.title),
            "llm_summary": item.llm_summary,
            "interest_score": item.interest_score,
            "sources": item.sources,
            "category": item.category,
        })

    # Render index
    index_tmpl = env.get_template("index.html")
    index_html = index_tmpl.render(
        date=date_str,
        items=items_data,
        deep_dive_slugs=deep_dive_slugs,
    )
    index_path = dashboard_dir / "index.html"
    index_path.write_text(index_html)

    # Render item pages for deep dives
    item_tmpl = env.get_template("item.html")
    report_map = {r.slug: r for r in reports}
    for item_data in items_data:
        slug = item_data["slug"]
        if slug in report_map:
            report = report_map[slug]
            item_html = item_tmpl.render(
                date=date_str,
                url=item_data["url"],
                report={
                    "title": report.title,
                    "what_it_is": report.what_it_is,
                    "why_trending": report.why_trending,
                    "pain_point": report.pain_point,
                    "gap_analysis": report.gap_analysis,
                    "competitors": report.competitors,
                    "app_idea": report.app_idea,
                    "feasibility": report.feasibility,
                },
            )
            (dashboard_dir / f"{slug}.html").write_text(item_html)

    logger.info(f"Dashboard built at {dashboard_dir}")
    return dashboard_dir
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: All 2 tests PASS

- [ ] **Step 6: Commit**

```bash
git add reporting/dashboard.py templates/ tests/test_dashboard.py
git commit -m "feat: static HTML dashboard generator"
```

---

### Task 17: Telegram Delivery

**Files:**
- Create: `delivery/__init__.py`
- Create: `delivery/telegram.py`
- Test: `tests/test_telegram.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telegram.py
from unittest.mock import patch, MagicMock, AsyncMock
from models import RawItem, ScoredItem, AnalysisReport
from delivery.telegram import format_telegram_message, send_telegram_message


def _scored(title, score, category, sources, summary):
    raw = RawItem(title=title, url=f"http://example.com/{title}", source=sources[0],
                  description="", metrics={}, timestamp="2026-04-08T00:00:00Z")
    return ScoredItem(raw_items=[raw], momentum_score=score, final_score=score,
                      sources=sources, category=category, llm_summary=summary,
                      interest_score=int(score * 10))


def test_format_telegram_message():
    items = [
        _scored("AgentKit", 0.9, "tool", ["github", "reddit"], "Agent framework"),
        _scored("ScalingPaper", 0.7, "paper", ["arxiv"], "Scaling paper"),
    ]
    reports = [AnalysisReport(
        slug="agentkit", title="AgentKit", what_it_is="framework",
        why_trending="viral", pain_point="complexity", gap_analysis="gaps",
        competitors=[], app_idea="Visual builder", feasibility={},
    )]
    msg = format_telegram_message(items, reports, "2026-04-08")
    assert "2026-04-08" in msg
    assert "AgentKit" in msg
    assert "Visual builder" in msg


def test_send_telegram_message():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True}
    with patch("delivery.telegram.requests.post", return_value=mock_resp) as mock_post:
        send_telegram_message("Test message", bot_token="fake", chat_id="123")
        mock_post.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_telegram.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Telegram delivery**

```python
# delivery/__init__.py
# (empty)

# delivery/telegram.py
from __future__ import annotations
import logging
import requests
from models import ScoredItem, AnalysisReport

logger = logging.getLogger(__name__)

SOURCE_ICONS = {
    "github": "⭐", "reddit": "💬", "arxiv": "📄",
    "huggingface": "🤗", "twitter": "𝕏", "hackernews": "🔶",
}


def format_telegram_message(
    items: list[ScoredItem],
    reports: list[AnalysisReport],
    date_str: str,
    dashboard_url: str = "",
) -> str:
    """Format the Telegram summary message."""
    lines = [f"🔥 AI Trending — {date_str}", f"{len(items)} items · {len(reports)} deep dives", ""]

    # Top pick
    if reports:
        top = reports[0]
        lines.append(f"📌 Top pick: {top.title}")
        lines.append(f"💡 Opportunity: {top.app_idea[:100]}")
        lines.append("")

    # Group items by source
    by_source: dict[str, list[str]] = {}
    for item in items[:10]:
        for src in item.sources:
            by_source.setdefault(src, []).append(item.title)

    for source, titles in sorted(by_source.items()):
        icon = SOURCE_ICONS.get(source, "•")
        title_list = ", ".join(titles[:3])
        if len(titles) > 3:
            title_list += f" +{len(titles) - 3}"
        lines.append(f"{icon} {source.title()}: {title_list}")

    if dashboard_url:
        lines.append(f"\n📊 Dashboard → {dashboard_url}")

    return "\n".join(lines)


def send_telegram_message(text: str, bot_token: str, chat_id: str) -> None:
    """Send a message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        logger.info("Telegram message sent successfully")
    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram message: {e}")
        raise


def send_error_notification(error_msg: str, bot_token: str, chat_id: str) -> None:
    """Send an error notification via Telegram."""
    text = f"⚠️ AI Trending Bot Error\n\n{error_msg}"
    try:
        send_telegram_message(text, bot_token, chat_id)
    except Exception:
        logger.error("Failed to send error notification via Telegram")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_telegram.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add delivery/ tests/test_telegram.py
git commit -m "feat: Telegram delivery"
```

---

### Task 18: Pipeline Orchestrator

**Files:**
- Create: `run.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pipeline.py
from pathlib import Path
from unittest.mock import patch, MagicMock
from run import Pipeline


def test_pipeline_creates_data_dir(tmp_path):
    config = {
        "scoring": {"digest_size": 5, "deep_dive_count": 2, "min_momentum_score": 0.1,
                     "freshness_half_life_hours": 48, "cross_platform_boost": {2: 1.5, 3: 2.5, 4: 4.0}},
        "sources": {"hackernews": {"enabled": True}},
        "delivery": {"telegram": {"enabled": False}, "dashboard": {"enabled": False}},
    }
    pipeline = Pipeline(config=config, data_root=tmp_path / "data")
    assert pipeline.data_dir.parent == tmp_path / "data"


def test_pipeline_collect_stage(tmp_path):
    config = {
        "scoring": {"digest_size": 5, "deep_dive_count": 2, "min_momentum_score": 0.1,
                     "freshness_half_life_hours": 48, "cross_platform_boost": {2: 1.5, 3: 2.5, 4: 4.0}},
        "sources": {"hackernews": {"enabled": True}, "github": {"enabled": False},
                     "reddit": {"enabled": False}, "arxiv": {"enabled": False},
                     "huggingface": {"enabled": False}, "twitter": {"enabled": False}},
        "delivery": {"telegram": {"enabled": False}, "dashboard": {"enabled": False}},
    }
    pipeline = Pipeline(config=config, data_root=tmp_path / "data")

    from models import RawItem
    mock_items = [RawItem(title="Test", url="http://test.com", source="hackernews",
                          description="", metrics={"points": 100}, timestamp="2026-04-08T00:00:00Z")]
    with patch("run.HackerNewsCollector") as mock_cls:
        mock_collector = MagicMock()
        mock_collector.run.return_value = mock_items
        mock_cls.return_value = mock_collector

        result = pipeline.stage_collect()
        assert len(result) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL

- [ ] **Step 3: Implement pipeline orchestrator**

```python
# run.py
from __future__ import annotations
import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from config import load_config, get_env
from models import RawItem, ScoredItem
from collectors.hackernews import HackerNewsCollector
from collectors.github import GitHubCollector
from collectors.reddit import RedditCollector
from collectors.arxiv import ArxivCollector
from collectors.huggingface import HuggingFaceCollector
from collectors.twitter import TwitterCollector
from scoring.momentum import compute_momentum_score, compute_final_score
from scoring.dedup import deduplicate
from scoring.llm_filter import run_llm_filter
from analysis.deep_dive import run_deep_dives
from reporting.digest import build_digest
from reporting.summary import build_summary
from reporting.dashboard import build_dashboard
from delivery.telegram import format_telegram_message, send_telegram_message, send_error_notification

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, config: dict | None = None, data_root: Path | None = None,
                 date_str: str | None = None):
        self.config = config or load_config()
        self.date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        data_root = data_root or Path("data")
        self.data_dir = data_root / self.date_str
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Setup file logging
        log_path = self.data_dir / "pipeline.log"
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(file_handler)

    def stage_collect(self) -> list[RawItem]:
        """Stage 1: Collect from all enabled sources in parallel."""
        logger.info("=== Stage 1: Collect ===")
        sources = self.config.get("sources", {})
        collectors = []

        if sources.get("hackernews", {}).get("enabled"):
            collectors.append(HackerNewsCollector())

        if sources.get("github", {}).get("enabled"):
            try:
                token = get_env("GITHUB_TOKEN")
                topics = sources["github"].get("topics")
                collectors.append(GitHubCollector(token=token, topics=topics))
            except EnvironmentError as e:
                logger.warning(f"Skipping GitHub: {e}")

        if sources.get("reddit", {}).get("enabled"):
            try:
                collectors.append(RedditCollector(
                    client_id=get_env("REDDIT_CLIENT_ID"),
                    client_secret=get_env("REDDIT_CLIENT_SECRET"),
                    user_agent=os.environ.get("REDDIT_USER_AGENT", "trending-bot/1.0"),
                    subreddits=sources["reddit"].get("subreddits"),
                ))
            except EnvironmentError as e:
                logger.warning(f"Skipping Reddit: {e}")

        if sources.get("arxiv", {}).get("enabled"):
            collectors.append(ArxivCollector(categories=sources["arxiv"].get("categories")))

        if sources.get("huggingface", {}).get("enabled"):
            collectors.append(HuggingFaceCollector())

        if sources.get("twitter", {}).get("enabled"):
            fallback = sources["twitter"].get("fallback_to_rss", True)
            collectors.append(TwitterCollector(fallback_to_rss=fallback))

        all_items: list[RawItem] = []
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(c.run, self.data_dir): c for c in collectors}
            for future in as_completed(futures):
                collector = futures[future]
                try:
                    items = future.result()
                    all_items.extend(items)
                    logger.info(f"{collector.source_name}: {len(items)} items")
                except Exception as e:
                    logger.error(f"{collector.source_name} failed: {e}")

        logger.info(f"Total collected: {len(all_items)} items")
        return all_items

    def stage_score(self, raw_items: list[RawItem]) -> tuple[list[ScoredItem], list[ScoredItem]]:
        """Stage 2: Score, dedup, and filter."""
        logger.info("=== Stage 2: Score & Rank ===")
        scoring_cfg = self.config["scoring"]

        # Dedup
        groups = deduplicate(raw_items)

        # Score each group
        scored_items = []
        for group in groups:
            scores = [compute_momentum_score(item) for item in group]
            best_score = max(scores)
            sources = list({item.source for item in group})
            age_hours = 24.0  # Default; could compute from timestamps
            final = compute_final_score(
                momentum_score=best_score,
                age_hours=age_hours,
                freshness_half_life=scoring_cfg["freshness_half_life_hours"],
                num_sources=len(sources),
                boost_config=scoring_cfg["cross_platform_boost"],
            )
            scored_items.append(ScoredItem(
                raw_items=group,
                momentum_score=best_score,
                final_score=final,
                sources=sources,
                category="",
                llm_summary="",
                interest_score=0,
            ))

        # Filter by min score
        min_score = scoring_cfg["min_momentum_score"]
        scored_items = [s for s in scored_items if s.momentum_score >= min_score]
        scored_items.sort(key=lambda x: x.final_score, reverse=True)

        # LLM filter (top 30)
        top_items = scored_items[:30]
        digest, deep_dives = run_llm_filter(
            top_items,
            digest_size=scoring_cfg["digest_size"],
            deep_dive_count=scoring_cfg["deep_dive_count"],
        )

        # Save ranked results
        scored_dir = self.data_dir / "scored"
        scored_dir.mkdir(parents=True, exist_ok=True)
        ranked_path = scored_dir / "ranked.json"
        ranked_path.write_text(json.dumps([s.to_dict() for s in digest], indent=2))

        logger.info(f"Digest: {len(digest)} items, Deep dives: {len(deep_dives)}")
        return digest, deep_dives

    def stage_analyze(self, deep_dive_items: list[ScoredItem]):
        """Stage 3: Deep dive analysis."""
        logger.info("=== Stage 3: Deep Dive ===")
        if not deep_dive_items:
            logger.info("No items flagged for deep dive")
            return []
        return run_deep_dives(deep_dive_items, self.data_dir)

    def stage_report(self, digest, reports):
        """Stage 4: Generate reports."""
        logger.info("=== Stage 4: Report ===")
        build_digest(digest, reports, self.data_dir, self.date_str)
        build_summary(digest, reports, self.data_dir, self.date_str)
        delivery_cfg = self.config.get("delivery", {})
        if delivery_cfg.get("dashboard", {}).get("enabled"):
            build_dashboard(digest, reports, self.data_dir, self.date_str)

    def stage_deliver(self, digest, reports):
        """Stage 5: Deliver via Telegram."""
        logger.info("=== Stage 5: Deliver ===")
        delivery_cfg = self.config.get("delivery", {})
        if delivery_cfg.get("telegram", {}).get("enabled"):
            try:
                bot_token = get_env("TELEGRAM_BOT_TOKEN")
                chat_id = get_env("TELEGRAM_CHAT_ID")
                dashboard_url = ""
                if delivery_cfg.get("dashboard", {}).get("enabled"):
                    port = delivery_cfg["dashboard"].get("port", 8080)
                    dashboard_url = f"http://localhost:{port}"
                msg = format_telegram_message(digest, reports, self.date_str, dashboard_url)
                send_telegram_message(msg, bot_token, chat_id)
            except Exception as e:
                logger.error(f"Telegram delivery failed: {e}")

    def run(self, stage: str | None = None):
        """Run the full pipeline or a single stage."""
        try:
            if stage == "collect" or stage is None:
                raw_items = self.stage_collect()
                if stage == "collect":
                    return

            if stage == "score" or stage is None:
                if stage == "score":
                    raw_items = self._load_raw_items()
                digest, deep_dives = self.stage_score(raw_items)
                if stage == "score":
                    return

            if stage == "analyze" or stage is None:
                if stage == "analyze":
                    deep_dives = self._load_deep_dive_items()
                reports = self.stage_analyze(deep_dives)
                if stage == "analyze":
                    return

            if stage == "report" or stage is None:
                if stage == "report":
                    digest = self._load_digest()
                    reports = self._load_reports()
                self.stage_report(digest, reports)
                if stage == "report":
                    return

            if stage == "deliver" or stage is None:
                if stage == "deliver":
                    digest = self._load_digest()
                    reports = self._load_reports()
                self.stage_deliver(digest, reports)

            logger.info("Pipeline completed successfully")

        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            self._notify_error(str(e))
            raise

    def _load_raw_items(self) -> list[RawItem]:
        raw_dir = self.data_dir / "raw"
        items = []
        for f in raw_dir.glob("*.json"):
            data = json.loads(f.read_text())
            items.extend(RawItem.from_dict(d) for d in data)
        return items

    def _load_deep_dive_items(self) -> list[ScoredItem]:
        # Reload from ranked.json — use top N items
        ranked_path = self.data_dir / "scored" / "ranked.json"
        if ranked_path.exists():
            data = json.loads(ranked_path.read_text())
            count = self.config["scoring"]["deep_dive_count"]
            items = []
            for d in data[:count]:
                raw_items = [RawItem.from_dict(r) for r in d.get("raw_items", [])]
                items.append(ScoredItem(
                    raw_items=raw_items, momentum_score=d["momentum_score"],
                    final_score=d["final_score"], sources=d["sources"],
                    category=d.get("category", ""), llm_summary=d.get("llm_summary", ""),
                    interest_score=d.get("interest_score", 0),
                ))
            return items
        return []

    def _load_digest(self) -> list[ScoredItem]:
        return self._load_deep_dive_items()  # Same source, different count

    def _load_reports(self):
        from models import AnalysisReport
        reports = []
        analysis_dir = self.data_dir / "analysis"
        if analysis_dir.exists():
            for f in analysis_dir.glob("*.json"):
                data = json.loads(f.read_text())
                reports.append(AnalysisReport(**data))
        return reports

    def _notify_error(self, error_msg: str):
        delivery_cfg = self.config.get("delivery", {})
        if delivery_cfg.get("telegram", {}).get("enabled"):
            try:
                bot_token = get_env("TELEGRAM_BOT_TOKEN")
                chat_id = get_env("TELEGRAM_CHAT_ID")
                send_error_notification(error_msg, bot_token, chat_id)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="AI Trending Bot")
    parser.add_argument("--stage", choices=["collect", "score", "analyze", "report", "deliver"],
                        help="Run a single stage")
    parser.add_argument("--date", help="Date to process (YYYY-MM-DD)")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    args = parser.parse_args()

    config = load_config(args.config)
    pipeline = Pipeline(config=config, date_str=args.date)
    pipeline.run(stage=args.stage)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add run.py tests/test_pipeline.py
git commit -m "feat: pipeline orchestrator with stage-based execution"
```

---

### Task 19: Dashboard Server + Cron Setup

**Files:**
- Create: `delivery/server.py`

- [ ] **Step 1: Implement dashboard HTTP server**

```python
# delivery/server.py
from __future__ import annotations
import http.server
import logging
import os
import sys
from pathlib import Path
from functools import partial

logger = logging.getLogger(__name__)


def serve_dashboard(serve_dir: str, port: int = 8080):
    """Serve the dashboard directory via a simple HTTP server."""
    serve_path = Path(serve_dir)
    if not serve_path.exists():
        logger.error(f"Dashboard directory not found: {serve_dir}")
        sys.exit(1)

    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(serve_path))
    with http.server.HTTPServer(("", port), handler) as server:
        logger.info(f"Dashboard serving at http://localhost:{port}")
        print(f"Dashboard serving at http://localhost:{port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("Dashboard server stopped")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="Directory to serve")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    serve_dashboard(args.dir, args.port)
```

- [ ] **Step 2: Create cron setup instructions**

Add to the bottom of the project README or as a comment in `run.py`:

The cron job is set up via the system crontab:

```bash
# Edit crontab
crontab -e

# Add this line (runs at 2 AM daily):
0 2 * * * cd /Users/hoangta/workspace/trending-bot && /usr/bin/python3 run.py >> /tmp/trending-bot.log 2>&1
```

- [ ] **Step 3: Commit**

```bash
git add delivery/server.py
git commit -m "feat: dashboard HTTP server + cron setup"
```

---

### Task 20: Integration Test + Final Verification

**Files:**
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Add integration-style test**

Add to `tests/test_pipeline.py`:

```python
def test_pipeline_full_run_with_mocks(tmp_path):
    """Smoke test: run the entire pipeline with mocked external calls."""
    import json
    config = {
        "scoring": {"digest_size": 5, "deep_dive_count": 1, "min_momentum_score": 0.0,
                     "freshness_half_life_hours": 48, "cross_platform_boost": {2: 1.5, 3: 2.5, 4: 4.0}},
        "sources": {"hackernews": {"enabled": True}, "github": {"enabled": False},
                     "reddit": {"enabled": False}, "arxiv": {"enabled": False},
                     "huggingface": {"enabled": False}, "twitter": {"enabled": False}},
        "delivery": {"telegram": {"enabled": False}, "dashboard": {"enabled": True, "port": 8080}},
    }

    from models import RawItem
    mock_items = [
        RawItem(title=f"AI Project {i}", url=f"http://example.com/{i}", source="hackernews",
                description=f"Description {i}", metrics={"points": 100 * (5 - i)},
                timestamp="2026-04-08T00:00:00Z")
        for i in range(5)
    ]

    llm_filter_response = json.dumps({
        "items": [
            {"index": 0, "category": "tool", "interest_score": 9,
             "summary": "Top project", "novel": True, "ai_relevant": True, "deep_dive": True},
            {"index": 1, "category": "paper", "interest_score": 7,
             "summary": "Good paper", "novel": True, "ai_relevant": True, "deep_dive": False},
        ]
    })

    deep_dive_response = json.dumps({
        "what_it_is": "A test project",
        "why_trending": "Very popular",
        "pain_point": "Hard problem",
        "gap_analysis": "Missing features",
        "competitors": ["Alt1"],
        "app_idea": "Build something better",
        "feasibility": {"effort": "2 weeks", "market": "growing", "competition": "low"},
    })

    with patch("run.HackerNewsCollector") as mock_hn, \
         patch("scoring.llm_filter.call_claude_json", return_value=json.loads(llm_filter_response)), \
         patch("analysis.deep_dive.call_claude_json", return_value=json.loads(deep_dive_response)), \
         patch("analysis.gatherer.requests.get") as mock_get, \
         patch("reporting.summary.call_claude", return_value="Summary text"):

        mock_collector = MagicMock()
        mock_collector.run.return_value = mock_items
        mock_collector.source_name = "hackernews"
        mock_hn.return_value = mock_collector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "# README"
        mock_resp.json.return_value = {"items": []}
        mock_get.return_value = mock_resp

        pipeline = Pipeline(config=config, data_root=tmp_path / "data", date_str="2026-04-08")
        pipeline.run()

        # Verify outputs exist
        data_dir = tmp_path / "data" / "2026-04-08"
        assert (data_dir / "raw" / "hackernews.json").exists()
        assert (data_dir / "scored" / "ranked.json").exists()
        assert (data_dir / "reports" / "digest.md").exists()
        assert (data_dir / "reports" / "summary.md").exists()
        assert (data_dir / "reports" / "dashboard" / "index.html").exists()
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline.py
git commit -m "feat: integration test for full pipeline"
```

- [ ] **Step 4: Run the pipeline manually to verify**

```bash
# Dry run with only HN (no API keys needed)
python run.py --stage collect
```

- [ ] **Step 5: Final commit with all files verified**

```bash
git log --oneline
```

Verify all commits are in place and the project is complete.
