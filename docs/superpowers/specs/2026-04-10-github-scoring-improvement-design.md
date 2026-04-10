# Fix GitHub Trending Collection & Cross-Source Scoring

**Date:** 2026-04-10
**Status:** Draft

## Problem Statement

The trending-bot dashboard shows zero GitHub items despite collecting 197 repos. Two root causes:

1. **Broken GitHub momentum formula:** `stars / max(stars, 100)` caps at 1.0 for any repo with 100+ stars. Reddit/HN scores reach 50-100+. GitHub items never make the top-30 cutoff for LLM filtering.

2. **Collector finds popular repos, not trending repos:** The query `topic:X pushed:>7d stars:>10 sort:stars` returns well-known established repos (tensorflow, pytorch, langchain) — not newly trending ones.

Secondary issues:
- GitHub item titles are bare repo slugs (`openclaw/openclaw`) giving the LLM filter no context for novelty/relevance evaluation.
- No source diversity guarantee — a single dominant source can fill all 30 LLM filter slots.
- Filter prompt has no source-aware evaluation guidance.

## Design

### 1. GitHub Collector: Two-Strategy Collection

Replace the single search query with two complementary strategies per topic:

**Strategy A — "Rising Stars" (new repos gaining traction):**
```
topic:{topic} created:>{7_days_ago} stars:>{min_stars_new}
sort: stars, desc
per_page: 30
```
- Catches brand-new repos accumulating stars quickly
- Default `min_stars_new`: 20 (configurable in config.yaml)
- A 3-day-old repo with 200 stars is genuinely trending

**Strategy B — "Breakout Updates" (established repos with recent pushes):**
```
topic:{topic} pushed:>{2_days_ago} stars:>{min_stars_established}
sort: stars, desc
per_page: 30
```
- Catches established repos with active development
- Default `min_stars_established`: 500 (configurable)
- Scored by star velocity (stars/age) so recent projects rank higher than ancient popular ones

**Title enrichment:**
- Title format: `"{description}"` when description exists, falling back to `full_name`
- Store `full_name` separately in metrics for deep-dive reference

**New metric — `age_days`:**
- Computed from `created_at` timestamp
- `max(age_days, 1)` to avoid division by zero

**Config additions to `config.yaml`:**
```yaml
sources:
  github:
    enabled: true
    min_stars_new_repo: 20
    min_stars_established: 500
    topics: [ai, llm, machine-learning, ...]
```

### 2. GitHub Momentum Formula: Star Velocity

Replace the broken formula in `scoring/momentum.py`:

**Before:**
```python
stars = m.get("stargazers_count", 0)
return stars / max(stars, 100)  # always ~1.0
```

**After:**
```python
stars = m.get("stargazers_count", 0)
age_days = m.get("age_days", 365)
return stars / max(age_days, 1)
```

This produces meaningful differentiation:
- 3-day-old repo, 500 stars → momentum 167
- 30-day-old repo, 5000 stars → momentum 167
- 5-year-old repo, 100K stars → momentum 55
- 7-day-old repo, 50 stars → momentum 7

### 3. Percentile Normalization Across Sources

After computing raw momentum for all items, normalize within each source to a 0-100 scale.

**Pipeline order change in `run.py`:**
The current order is: deduplicate → score → rank. The new order is:

1. Compute raw momentum for each `RawItem` (before dedup)
2. Normalize within each source (percentile rank) → attach normalized score to each RawItem via a `url→score` dict
3. Deduplicate (merge groups)
4. For each group: `best_normalized = max(normalized[item.url] for item in group)`
5. Compute `final_score` from `best_normalized * freshness_decay * cross_platform_boost`

This avoids the ambiguity of which source a merged cross-source item "belongs to" — each raw item is normalized within its own source before merging.

**New function `normalize_by_source()` in `scoring/momentum.py`:**

```python
def normalize_by_source(
    raw_items: list[RawItem],
    scores: dict[str, float],  # url -> raw momentum
) -> dict[str, float]:  # url -> normalized 0-100
    by_source = defaultdict(list)
    for item in raw_items:
        by_source[item.source].append(item)

    normalized = {}
    for src, items in by_source.items():
        items.sort(key=lambda x: scores.get(x.url, 0))
        n = len(items)
        for i, item in enumerate(items):
            percentile = (i / max(n - 1, 1)) * 100
            # Keep best percentile if URL appears in multiple source groups
            if item.url not in normalized or percentile > normalized[item.url]:
                normalized[item.url] = percentile
    return normalized
```

This ensures:
- Top Reddit post and top GitHub repo both score ~100
- Median from each source scores ~50
- Sources compete fairly regardless of their raw score ranges
- Cross-source items get their best percentile from whichever source ranked them highest

**Impact on ScoredItem model:**
- Add `normalized_score: float` field (defaults to 0.0)
- `final_score` now uses `normalized_score` instead of raw `momentum_score`

### 4. Source Diversity in Top-30 Selection

Replace the simple `sorted[:30]` with round-robin interleaving:

```python
def select_diverse_top(items, count=30):
    by_source = defaultdict(list)
    for item in items:
        primary_source = item.sources[0]
        by_source[primary_source].append(item)
    
    # Sort each source's items by final_score descending
    for src in by_source:
        by_source[src].sort(key=lambda x: x.final_score, reverse=True)
    
    selected = []
    pointers = {src: 0 for src in by_source}
    
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

This guarantees each source gets fair representation in the LLM filter input.

### 5. Filter Prompt Enhancement

Add source-aware evaluation context to `prompts/filter.md`:

```markdown
Source-specific evaluation guidance:
- **GitHub repos**: Evaluate based on the repo description and what it does. 
  New repos gaining stars quickly are more interesting than established popular repos. 
  Filter out: minor forks, thin wrappers around existing tools, tutorial/educational repos, 
  awesome-lists, and repos that are popular but not novel.
- **Reddit/HackerNews posts**: Evaluate based on the linked content, not the discussion. 
  High engagement alone does not mean high quality.
- **arXiv papers**: Evaluate based on novelty of approach and potential practical impact.
- **HuggingFace models**: Evaluate based on capability, architecture novelty, or benchmark results.
```

## Files Changed

| File | Change Type | Description |
|------|------------|-------------|
| `collectors/github.py` | Major rewrite | Two-strategy collection, title enrichment, age_days metric |
| `scoring/momentum.py` | Modify | Fix GitHub formula; add `normalize_scores()` function |
| `models.py` | Modify | Add `normalized_score` field to `ScoredItem` |
| `run.py` | Modify | Add normalization step; add `select_diverse_top()` for round-robin selection |
| `prompts/filter.md` | Modify | Add source-aware evaluation guidance |
| `config.yaml` | Modify | Add `min_stars_new_repo`, `min_stars_established` settings |
| `tests/test_momentum.py` | Modify | Update tests for new GitHub formula and normalization |
| `tests/test_github_collector.py` | Modify | Update tests for two-strategy collection |

## What Does NOT Change

- Other collectors (Reddit, HN, arXiv, HuggingFace, Twitter) — untouched
- LLM filter logic (`scoring/llm_filter.py`) — same novel + ai_relevant gates
- Deep dive analysis pipeline — untouched
- Report generation and dashboard templates — untouched
- Delivery (Telegram, HTTP) — untouched
- `RawItem` model — untouched (age_days goes in existing `metrics` dict)

## Verification

After implementation:
1. Run the collector with mock/real data and confirm GitHub items have meaningful momentum scores (not all 1.0)
2. Run the full scoring pipeline and confirm GitHub items appear in the top-30
3. Check that the final dashboard includes a mix of sources
4. Existing tests still pass
