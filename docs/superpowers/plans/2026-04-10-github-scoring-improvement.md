# GitHub Scoring & Collection Improvement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the trending-bot so GitHub items actually appear in the dashboard by fixing the collector (find trending repos, not just popular ones), fixing the momentum formula (star velocity instead of capped-at-1.0), normalizing scores across sources, and guaranteeing source diversity.

**Architecture:** The collector gets two search strategies (rising stars + breakout updates). Momentum scoring switches to `stars/age_days` for GitHub. A new normalization step converts raw momentum to percentile rank within each source before dedup. A round-robin selector replaces the simple top-30 sort to ensure every source gets LLM filter slots. The filter prompt gets source-aware guidance.

**Tech Stack:** Python 3.11, pytest, requests (GitHub API)

**Spec:** `docs/superpowers/specs/2026-04-10-github-scoring-improvement-design.md`

---

### Task 1: Add `normalized_score` to ScoredItem model

**Files:**
- Modify: `models.py:30-64`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write test for normalized_score field**

In `tests/test_models.py`, add:

```python
def test_scored_item_normalized_score_defaults():
    raw = RawItem.from_dict({
        "title": "Test", "url": "http://a.com", "source": "github",
        "description": "", "metrics": {}, "timestamp": "2026-04-08T00:00:00Z",
    })
    scored = ScoredItem(
        raw_items=[raw], momentum_score=1.0, final_score=0.6,
        sources=["github"], category="tool", llm_summary="", interest_score=5,
    )
    assert scored.normalized_score == 0.0


def test_scored_item_normalized_score_in_to_dict():
    raw = RawItem.from_dict({
        "title": "Test", "url": "http://a.com", "source": "github",
        "description": "", "metrics": {}, "timestamp": "2026-04-08T00:00:00Z",
    })
    scored = ScoredItem(
        raw_items=[raw], momentum_score=1.0, final_score=0.6,
        sources=["github"], category="tool", llm_summary="", interest_score=5,
        normalized_score=75.0,
    )
    d = scored.to_dict()
    assert d["normalized_score"] == 75.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_models.py::test_scored_item_normalized_score_defaults tests/test_models.py::test_scored_item_normalized_score_in_to_dict -v`
Expected: FAIL — `ScoredItem.__init__() got an unexpected keyword argument 'normalized_score'`

- [ ] **Step 3: Add normalized_score field to ScoredItem**

In `models.py`, modify the `ScoredItem` dataclass:

```python
@dataclass
class ScoredItem:
    raw_items: list[RawItem]
    momentum_score: float
    final_score: float
    sources: list[str]
    category: str
    llm_summary: str
    interest_score: int
    normalized_score: float = 0.0
```

And add `normalized_score` to `to_dict()`:

```python
    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "description": self.description,
            "momentum_score": self.momentum_score,
            "normalized_score": self.normalized_score,
            "final_score": self.final_score,
            "sources": self.sources,
            "category": self.category,
            "llm_summary": self.llm_summary,
            "interest_score": self.interest_score,
            "raw_items": [r.to_dict() for r in self.raw_items],
        }
```

- [ ] **Step 4: Run all model tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: All pass (existing tests use positional args or don't set `normalized_score`, so the default of 0.0 kicks in)

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: add normalized_score field to ScoredItem"
```

---

### Task 2: Fix GitHub momentum formula to star velocity

**Files:**
- Modify: `scoring/momentum.py:23-25`
- Test: `tests/test_momentum.py`

- [ ] **Step 1: Write tests for the new GitHub momentum formula**

In `tests/test_momentum.py`, replace `test_github_momentum` and add new tests:

```python
def test_github_momentum_new_repo():
    """3-day-old repo with 500 stars = 500/3 = ~167 momentum"""
    item = RawItem(title="test", url="http://test.com", source="github",
                   description="", metrics={"stargazers_count": 500, "age_days": 3},
                   timestamp="2026-04-08T00:00:00Z")
    score = compute_momentum_score(item)
    assert abs(score - 500 / 3) < 0.01


def test_github_momentum_old_repo():
    """5-year-old repo (1825 days) with 100K stars = ~55 momentum"""
    item = RawItem(title="test", url="http://test.com", source="github",
                   description="", metrics={"stargazers_count": 100000, "age_days": 1825},
                   timestamp="2026-04-08T00:00:00Z")
    score = compute_momentum_score(item)
    assert abs(score - 100000 / 1825) < 0.1


def test_github_momentum_defaults_age_to_365():
    """Missing age_days defaults to 365"""
    item = RawItem(title="test", url="http://test.com", source="github",
                   description="", metrics={"stargazers_count": 3000},
                   timestamp="2026-04-08T00:00:00Z")
    score = compute_momentum_score(item)
    assert abs(score - 3000 / 365) < 0.1


def test_github_momentum_zero_age_clamped():
    """age_days=0 should be clamped to 1 to avoid division by zero"""
    item = RawItem(title="test", url="http://test.com", source="github",
                   description="", metrics={"stargazers_count": 200, "age_days": 0},
                   timestamp="2026-04-08T00:00:00Z")
    score = compute_momentum_score(item)
    assert score == 200.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_momentum.py::test_github_momentum_new_repo tests/test_momentum.py::test_github_momentum_old_repo tests/test_momentum.py::test_github_momentum_defaults_age_to_365 tests/test_momentum.py::test_github_momentum_zero_age_clamped -v`
Expected: FAIL — old formula returns ~1.0 for all cases

- [ ] **Step 3: Update the GitHub momentum formula**

In `scoring/momentum.py`, replace lines 23-25:

```python
    if source == "github":
        stars = m.get("stargazers_count", 0)
        age_days = m.get("age_days", 365)
        return stars / max(age_days, 1)
```

- [ ] **Step 4: Run all momentum tests**

Run: `python -m pytest tests/test_momentum.py -v`
Expected: All pass (new GitHub tests + existing Reddit/HN/arXiv/etc tests unchanged)

- [ ] **Step 5: Commit**

```bash
git add scoring/momentum.py tests/test_momentum.py
git commit -m "fix: GitHub momentum uses star velocity (stars/age_days) instead of capped formula"
```

---

### Task 3: Add `normalize_by_source` function

**Files:**
- Modify: `scoring/momentum.py`
- Test: `tests/test_momentum.py`

- [ ] **Step 1: Write tests for normalize_by_source**

Append to `tests/test_momentum.py`:

```python
from scoring.momentum import normalize_by_source


def test_normalize_by_source_single_source():
    items = [
        RawItem(title="low", url="http://a.com", source="github",
                description="", metrics={}, timestamp=""),
        RawItem(title="mid", url="http://b.com", source="github",
                description="", metrics={}, timestamp=""),
        RawItem(title="high", url="http://c.com", source="github",
                description="", metrics={}, timestamp=""),
    ]
    scores = {"http://a.com": 10, "http://b.com": 50, "http://c.com": 100}
    result = normalize_by_source(items, scores)
    assert result["http://a.com"] == 0.0
    assert result["http://b.com"] == 50.0
    assert result["http://c.com"] == 100.0


def test_normalize_by_source_multiple_sources():
    items = [
        RawItem(title="gh1", url="http://gh1.com", source="github",
                description="", metrics={}, timestamp=""),
        RawItem(title="gh2", url="http://gh2.com", source="github",
                description="", metrics={}, timestamp=""),
        RawItem(title="rd1", url="http://rd1.com", source="reddit",
                description="", metrics={}, timestamp=""),
        RawItem(title="rd2", url="http://rd2.com", source="reddit",
                description="", metrics={}, timestamp=""),
    ]
    scores = {
        "http://gh1.com": 10,   # lowest github
        "http://gh2.com": 200,  # highest github
        "http://rd1.com": 5,    # lowest reddit
        "http://rd2.com": 80,   # highest reddit
    }
    result = normalize_by_source(items, scores)
    # Each source normalized independently
    assert result["http://gh1.com"] == 0.0
    assert result["http://gh2.com"] == 100.0
    assert result["http://rd1.com"] == 0.0
    assert result["http://rd2.com"] == 100.0


def test_normalize_by_source_single_item():
    items = [
        RawItem(title="only", url="http://a.com", source="github",
                description="", metrics={}, timestamp=""),
    ]
    scores = {"http://a.com": 50}
    result = normalize_by_source(items, scores)
    assert result["http://a.com"] == 0.0  # single item = percentile 0/0 = 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_momentum.py::test_normalize_by_source_single_source tests/test_momentum.py::test_normalize_by_source_multiple_sources tests/test_momentum.py::test_normalize_by_source_single_item -v`
Expected: FAIL — `cannot import name 'normalize_by_source'`

- [ ] **Step 3: Implement normalize_by_source**

Add to `scoring/momentum.py`:

```python
from collections import defaultdict

def normalize_by_source(
    raw_items: list[RawItem],
    scores: dict[str, float],
) -> dict[str, float]:
    """Normalize raw momentum scores to 0-100 percentile rank within each source."""
    by_source: dict[str, list[RawItem]] = defaultdict(list)
    for item in raw_items:
        by_source[item.source].append(item)

    normalized: dict[str, float] = {}
    for src, items in by_source.items():
        items.sort(key=lambda x: scores.get(x.url, 0))
        n = len(items)
        for i, item in enumerate(items):
            percentile = (i / max(n - 1, 1)) * 100
            if item.url not in normalized or percentile > normalized[item.url]:
                normalized[item.url] = percentile
    return normalized
```

- [ ] **Step 4: Run all momentum tests**

Run: `python -m pytest tests/test_momentum.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add scoring/momentum.py tests/test_momentum.py
git commit -m "feat: add normalize_by_source for percentile normalization across sources"
```

---

### Task 4: Add `select_diverse_top` function to run.py

**Files:**
- Modify: `run.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write tests for select_diverse_top**

Append to `tests/test_pipeline.py`:

```python
from run import select_diverse_top
from models import RawItem, ScoredItem


def _make_scored(title, source, final_score):
    raw = RawItem(title=title, url=f"http://{source}/{title}", source=source,
                  description="", metrics={}, timestamp="")
    return ScoredItem(
        raw_items=[raw], momentum_score=final_score, final_score=final_score,
        sources=[source], category="", llm_summary="", interest_score=0,
    )


def test_select_diverse_top_interleaves_sources():
    items = [
        _make_scored("r1", "reddit", 100),
        _make_scored("r2", "reddit", 90),
        _make_scored("r3", "reddit", 80),
        _make_scored("g1", "github", 70),
        _make_scored("g2", "github", 60),
        _make_scored("h1", "hackernews", 50),
    ]
    result = select_diverse_top(items, count=6)
    # First 3 should be one from each source (highest of each)
    first_three_sources = {r.sources[0] for r in result[:3]}
    assert first_three_sources == {"reddit", "github", "hackernews"}


def test_select_diverse_top_respects_count():
    items = [
        _make_scored("r1", "reddit", 100),
        _make_scored("r2", "reddit", 90),
        _make_scored("g1", "github", 80),
        _make_scored("g2", "github", 70),
    ]
    result = select_diverse_top(items, count=3)
    assert len(result) == 3


def test_select_diverse_top_handles_uneven_sources():
    items = [
        _make_scored("r1", "reddit", 100),
        _make_scored("g1", "github", 50),
        _make_scored("g2", "github", 40),
        _make_scored("g3", "github", 30),
    ]
    result = select_diverse_top(items, count=4)
    assert len(result) == 4
    # First round: reddit r1, github g1
    # Second round: github g2 (reddit exhausted)
    # Third round: github g3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py::test_select_diverse_top_interleaves_sources tests/test_pipeline.py::test_select_diverse_top_respects_count tests/test_pipeline.py::test_select_diverse_top_handles_uneven_sources -v`
Expected: FAIL — `cannot import name 'select_diverse_top' from 'run'`

- [ ] **Step 3: Implement select_diverse_top**

Add to `run.py` (before the `Pipeline` class):

```python
from collections import defaultdict


def select_diverse_top(items: list[ScoredItem], count: int = 30) -> list[ScoredItem]:
    """Select top items with round-robin source interleaving for diversity."""
    by_source: dict[str, list[ScoredItem]] = defaultdict(list)
    for item in items:
        primary_source = item.sources[0]
        by_source[primary_source].append(item)

    for src in by_source:
        by_source[src].sort(key=lambda x: x.final_score, reverse=True)

    selected: list[ScoredItem] = []
    pointers: dict[str, int] = {src: 0 for src in by_source}

    while len(selected) < count:
        added_this_round = False
        for src in sorted(by_source.keys()):
            if pointers[src] < len(by_source[src]):
                selected.append(by_source[src][pointers[src]])
                pointers[src] += 1
                added_this_round = True
                if len(selected) >= count:
                    break
        if not added_this_round:
            break

    return selected
```

- [ ] **Step 4: Run pipeline tests**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add run.py tests/test_pipeline.py
git commit -m "feat: add select_diverse_top for round-robin source diversity"
```

---

### Task 5: Rewrite GitHub collector with two-strategy collection

**Files:**
- Modify: `collectors/github.py`
- Modify: `config.yaml`
- Test: `tests/test_github.py`

- [ ] **Step 1: Write tests for the new collector**

Replace the contents of `tests/test_github.py` with:

```python
import json
from unittest.mock import patch, MagicMock, call
from collectors.github import GitHubCollector
from models import RawItem


def _mock_rising_stars_response():
    return {
        "items": [
            {
                "full_name": "new-org/cool-agent",
                "html_url": "https://github.com/new-org/cool-agent",
                "description": "A brand new AI agent framework",
                "stargazers_count": 500,
                "forks_count": 30,
                "created_at": "2026-04-05T00:00:00Z",
                "pushed_at": "2026-04-08T00:00:00Z",
                "topics": ["ai", "agents"],
                "language": "Python",
            }
        ]
    }


def _mock_breakout_response():
    return {
        "items": [
            {
                "full_name": "big-org/established-ml",
                "html_url": "https://github.com/big-org/established-ml",
                "description": "Well-known ML library with major update",
                "stargazers_count": 8000,
                "forks_count": 400,
                "created_at": "2025-01-01T00:00:00Z",
                "pushed_at": "2026-04-08T00:00:00Z",
                "topics": ["ai", "machine-learning"],
                "language": "Python",
            }
        ]
    }


def test_github_collector_uses_two_strategies():
    """Collector should make both rising-stars and breakout queries per topic."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = [_mock_rising_stars_response(), _mock_breakout_response()]

    with patch("collectors.github.requests.get", return_value=mock_resp) as mock_get:
        collector = GitHubCollector(token="fake", topics=["ai"])
        items = collector.collect()
        # Two API calls per topic (rising stars + breakout)
        assert mock_get.call_count == 2


def test_github_collector_computes_age_days():
    """Items should have age_days in metrics."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_rising_stars_response()

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake", topics=["ai"])
        items = collector.collect()
        assert len(items) >= 1
        assert "age_days" in items[0].metrics
        assert items[0].metrics["age_days"] > 0


def test_github_collector_uses_description_as_title():
    """Title should use description when available, not bare full_name."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_rising_stars_response()

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake", topics=["ai"])
        items = collector.collect()
        assert items[0].title == "A brand new AI agent framework"


def test_github_collector_falls_back_to_full_name():
    """Title falls back to full_name when description is empty."""
    resp_data = _mock_rising_stars_response()
    resp_data["items"][0]["description"] = ""

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = resp_data

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake", topics=["ai"])
        items = collector.collect()
        assert items[0].title == "new-org/cool-agent"


def test_github_collector_deduplicates_across_strategies():
    """Same repo appearing in both strategies should be deduplicated."""
    same_repo = {
        "full_name": "org/repo",
        "html_url": "https://github.com/org/repo",
        "description": "Shared repo",
        "stargazers_count": 1000,
        "forks_count": 50,
        "created_at": "2026-04-03T00:00:00Z",
        "pushed_at": "2026-04-08T00:00:00Z",
        "topics": ["ai"],
        "language": "Python",
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": [same_repo]}

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake", topics=["ai"])
        items = collector.collect()
        assert len(items) == 1


def test_github_collector_saves_to_file(tmp_data_dir):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_rising_stars_response()

    with patch("collectors.github.requests.get", return_value=mock_resp):
        collector = GitHubCollector(token="fake", topics=["ai"])
        items = collector.run(tmp_data_dir)
        saved = tmp_data_dir / "raw" / "github.json"
        assert saved.exists()
        data = json.loads(saved.read_text())
        assert len(data) == len(items)


def test_github_collector_reads_config_thresholds():
    """Collector should accept min_stars_new and min_stars_established."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": []}

    with patch("collectors.github.requests.get", return_value=mock_resp) as mock_get:
        collector = GitHubCollector(
            token="fake", topics=["ai"],
            min_stars_new=50, min_stars_established=1000,
        )
        collector.collect()
        # Check the query parameters contain the custom thresholds
        calls = mock_get.call_args_list
        queries = [c.kwargs.get("params", {}).get("q", "") or c[1].get("params", {}).get("q", "") for c in calls]
        assert any("stars:>50" in q for q in queries)
        assert any("stars:>1000" in q for q in queries)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_github.py -v`
Expected: FAIL — old collector doesn't match new test expectations

- [ ] **Step 3: Rewrite the GitHub collector**

Replace `collectors/github.py` with:

```python
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

    def __init__(
        self,
        token: str,
        topics: list[str] | None = None,
        min_stars_new: int = 20,
        min_stars_established: int = 500,
    ):
        self.token = token
        self.topics = topics or ["ai", "llm", "machine-learning"]
        self.min_stars_new = min_stars_new
        self.min_stars_established = min_stars_established
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def collect(self) -> list[RawItem]:
        items: list[RawItem] = []
        now = datetime.now(timezone.utc)
        seven_days_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        two_days_ago = (now - timedelta(days=2)).strftime("%Y-%m-%d")

        for topic in self.topics:
            # Strategy A: Rising stars — new repos gaining traction
            items.extend(self._search(
                query=f"topic:{topic} created:>{seven_days_ago} stars:>{self.min_stars_new}",
                now=now,
            ))
            # Strategy B: Breakout updates — established repos with recent pushes
            items.extend(self._search(
                query=f"topic:{topic} pushed:>{two_days_ago} stars:>{self.min_stars_established}",
                now=now,
            ))

        seen: set[str] = set()
        unique: list[RawItem] = []
        for item in items:
            if item.url not in seen:
                seen.add(item.url)
                unique.append(item)

        logger.info(f"GitHub collector found {len(unique)} repos")
        return unique

    def _search(self, query: str, now: datetime) -> list[RawItem]:
        url = f"{self.API_URL}/search/repositories"
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": 30}
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            items = []
            for repo in data.get("items", []):
                age_days = self._compute_age_days(repo.get("created_at", ""), now)
                description = repo.get("description") or ""
                title = description if description else repo["full_name"]
                item = RawItem(
                    title=title,
                    url=repo["html_url"],
                    source=self.source_name,
                    description=description,
                    metrics={
                        "stargazers_count": repo.get("stargazers_count", 0),
                        "forks_count": repo.get("forks_count", 0),
                        "created_at": repo.get("created_at", ""),
                        "pushed_at": repo.get("pushed_at", ""),
                        "topics": repo.get("topics", []),
                        "language": repo.get("language", ""),
                        "full_name": repo["full_name"],
                        "age_days": age_days,
                    },
                    timestamp=repo.get("pushed_at", ""),
                )
                items.append(item)
            return items
        except requests.RequestException as e:
            logger.error(f"GitHub API error for query '{query}': {e}")
            return []

    def _compute_age_days(self, created_at: str, now: datetime) -> float:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            delta = now - dt
            return max(delta.total_seconds() / 86400, 1)
        except (ValueError, TypeError):
            return 365.0
```

- [ ] **Step 4: Update config.yaml with new settings**

Add `min_stars_new_repo` and `min_stars_established` to `config.yaml` under `sources.github`:

```yaml
sources:
  github:
    enabled: true
    min_stars_new_repo: 20
    min_stars_established: 500
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
```

- [ ] **Step 5: Update run.py to pass new config to GitHubCollector**

In `run.py`, change the GitHub collector initialization (inside `stage_collect`):

```python
        if sources.get("github", {}).get("enabled"):
            try:
                token = get_env("GITHUB_TOKEN")
                gh_cfg = sources["github"]
                collectors.append(GitHubCollector(
                    token=token,
                    topics=gh_cfg.get("topics"),
                    min_stars_new=gh_cfg.get("min_stars_new_repo", 20),
                    min_stars_established=gh_cfg.get("min_stars_established", 500),
                ))
            except EnvironmentError as e:
                logger.warning(f"Skipping GitHub: {e}")
```

- [ ] **Step 6: Run all GitHub and pipeline tests**

Run: `python -m pytest tests/test_github.py tests/test_pipeline.py -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add collectors/github.py config.yaml run.py tests/test_github.py
git commit -m "feat: rewrite GitHub collector with rising-stars and breakout-updates strategies"
```

---

### Task 6: Wire normalization and diversity into the scoring pipeline

**Files:**
- Modify: `run.py` (stage_score method)
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write integration test for the new scoring pipeline**

Append to `tests/test_pipeline.py`:

```python
def test_pipeline_score_includes_github_items(tmp_path):
    """GitHub items should appear in the ranked output after normalization + diversity."""
    config = {
        "scoring": {"digest_size": 5, "deep_dive_count": 2, "min_momentum_score": 0.0,
                     "freshness_half_life_hours": 48, "cross_platform_boost": {2: 1.5, 3: 2.5, 4: 4.0}},
        "sources": {},
        "delivery": {"telegram": {"enabled": False}, "dashboard": {"enabled": False}},
    }
    pipeline = Pipeline(config=config, data_root=tmp_path / "data")

    raw_items = [
        # Reddit items with high raw momentum
        RawItem(title="Big AI News", url="http://reddit.com/1", source="reddit",
                description="Important", metrics={"score": 5000},
                timestamp="2026-04-09T01:00:00Z"),
        RawItem(title="Another AI Post", url="http://reddit.com/2", source="reddit",
                description="Also important", metrics={"score": 3000},
                timestamp="2026-04-09T01:00:00Z"),
        # GitHub items with low raw momentum but genuine signal
        RawItem(title="New agent framework", url="http://github.com/1", source="github",
                description="Cool new tool", metrics={"stargazers_count": 500, "age_days": 3},
                timestamp="2026-04-09T00:00:00Z"),
        RawItem(title="ML compiler", url="http://github.com/2", source="github",
                description="Fast ML compiler", metrics={"stargazers_count": 200, "age_days": 5},
                timestamp="2026-04-09T00:00:00Z"),
    ]

    llm_filter_response = {
        "items": [
            {"index": i, "category": "tool", "interest_score": 8,
             "summary": f"Item {i}", "novel": True, "ai_relevant": True, "deep_dive": False}
            for i in range(4)
        ]
    }

    with patch("scoring.llm_filter.call_claude_json", return_value=llm_filter_response):
        digest, _ = pipeline.stage_score(raw_items)

    sources_in_digest = set()
    for item in digest:
        sources_in_digest.update(item.sources)
    assert "github" in sources_in_digest, "GitHub items should appear in digest after normalization"
    assert "reddit" in sources_in_digest
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline.py::test_pipeline_score_includes_github_items -v`
Expected: FAIL — GitHub items don't make it through with old pipeline

- [ ] **Step 3: Rewrite stage_score to use normalization and diversity**

In `run.py`, update the `stage_score` method and add the required import:

At top of `run.py`, add `normalize_by_source` to the import:

```python
from scoring.momentum import compute_momentum_score, compute_final_score, normalize_by_source
```

Replace the `stage_score` method body:

```python
    def stage_score(self, raw_items: list[RawItem]) -> tuple[list[ScoredItem], list[ScoredItem]]:
        logger.info("=== Stage 2: Score & Rank ===")
        scoring_cfg = self.config["scoring"]

        # 1. Compute raw momentum per RawItem
        raw_scores: dict[str, float] = {}
        for item in raw_items:
            score = compute_momentum_score(item)
            if item.url not in raw_scores or score > raw_scores[item.url]:
                raw_scores[item.url] = score

        # 2. Normalize within each source (percentile rank)
        normalized = normalize_by_source(raw_items, raw_scores)

        # 3. Deduplicate
        groups = deduplicate(raw_items)

        # 4. Build ScoredItems with normalized scores
        scored_items = []
        for group in groups:
            best_norm = max(normalized.get(item.url, 0) for item in group)
            best_raw = max(raw_scores.get(item.url, 0) for item in group)
            sources = list({item.source for item in group})
            age_hours = 24.0
            final = compute_final_score(
                momentum_score=best_norm,
                age_hours=age_hours,
                freshness_half_life=scoring_cfg["freshness_half_life_hours"],
                num_sources=len(sources),
                boost_config=scoring_cfg["cross_platform_boost"],
            )
            scored_items.append(ScoredItem(
                raw_items=group,
                momentum_score=best_raw,
                normalized_score=best_norm,
                final_score=final,
                sources=sources,
                category="",
                llm_summary="",
                interest_score=0,
            ))

        min_score = scoring_cfg["min_momentum_score"]
        scored_items = [s for s in scored_items if s.momentum_score >= min_score]

        # 5. Diverse top-30 selection (round-robin across sources)
        top_items = select_diverse_top(scored_items, count=30)

        digest, deep_dives = run_llm_filter(
            top_items,
            digest_size=scoring_cfg["digest_size"],
            deep_dive_count=scoring_cfg["deep_dive_count"],
        )

        scored_dir = self.data_dir / "scored"
        scored_dir.mkdir(parents=True, exist_ok=True)
        ranked_path = scored_dir / "ranked.json"
        ranked_path.write_text(json.dumps([s.to_dict() for s in digest], indent=2))

        logger.info(f"Digest: {len(digest)} items, Deep dives: {len(deep_dives)}")
        return digest, deep_dives
```

- [ ] **Step 4: Run all pipeline tests**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: All pass

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add run.py tests/test_pipeline.py
git commit -m "feat: wire normalization and source diversity into scoring pipeline"
```

---

### Task 7: Enhance filter prompt with source-aware guidance

**Files:**
- Modify: `prompts/filter.md`

- [ ] **Step 1: Update the filter prompt**

Append source-aware guidance to `prompts/filter.md`, after the existing instructions and before `{items_json}`:

```markdown
Source-specific evaluation guidance:
- **GitHub repos**: Evaluate based on the repo description and what it does. New repos gaining stars quickly are more interesting than established popular repos. Filter out: minor forks, thin wrappers around existing tools, tutorial/educational repos, awesome-lists, and repos that are popular but not novel.
- **Reddit/HackerNews posts**: Evaluate based on the linked content, not the discussion engagement alone. High upvotes does not automatically mean high quality or novelty.
- **arXiv papers**: Evaluate based on novelty of approach and potential practical impact. Prefer papers with new techniques over incremental improvements.
- **HuggingFace models**: Evaluate based on capability, architecture novelty, or benchmark results. Filter out minor fine-tunes of existing models.
```

- [ ] **Step 2: Verify prompt file is valid**

Run: `python -c "from pathlib import Path; text = Path('prompts/filter.md').read_text(); assert '{items_json}' in text; print('OK: prompt template valid')"`
Expected: `OK: prompt template valid`

- [ ] **Step 3: Commit**

```bash
git add prompts/filter.md
git commit -m "feat: add source-aware evaluation guidance to LLM filter prompt"
```

---

### Task 8: Final verification — run full test suite

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Verify with the actual raw data from 2026-04-09**

Run a quick smoke test using the existing raw data:

```bash
python -c "
import json
from models import RawItem
from scoring.momentum import compute_momentum_score, normalize_by_source

# Load raw GitHub data
with open('data/2026-04-09/raw/github.json') as f:
    gh_data = json.load(f)

# Compute raw momentum with new formula
items = [RawItem.from_dict(d) for d in gh_data]
scores = {item.url: compute_momentum_score(item) for item in items}

# Show top 10 by star velocity
ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
print('Top 10 GitHub items by star velocity:')
for url, score in ranked[:10]:
    item = next(i for i in items if i.url == url)
    stars = item.metrics.get('stargazers_count', 0)
    age = item.metrics.get('age_days', 365)
    print(f'  velocity={score:.1f} ({stars} stars, {age:.0f} days) - {item.title[:60]}')

# Compare ranges
print(f'\\nGitHub momentum range: {ranked[-1][1]:.1f} - {ranked[0][1]:.1f}')

# Load Reddit for comparison
with open('data/2026-04-09/raw/reddit.json') as f:
    rd_data = json.load(f)
rd_items = [RawItem.from_dict(d) for d in rd_data]
rd_scores = {item.url: compute_momentum_score(item) for item in rd_items}
rd_ranked = sorted(rd_scores.items(), key=lambda x: x[1], reverse=True)
print(f'Reddit momentum range: {rd_ranked[-1][1]:.1f} - {rd_ranked[0][1]:.1f}')
"
```

This validates that GitHub star velocity scores are now in a meaningful range and the normalization would make them competitive.

- [ ] **Step 3: Create a final commit with all changes verified**

No additional commit needed — all changes were committed in prior tasks.
