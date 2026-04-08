from models import RawItem
from scoring.dedup import deduplicate


def _item(title, url, source, **metrics):
    return RawItem(title=title, url=url, source=source,
                   description="", metrics=metrics, timestamp="2026-04-08T00:00:00Z")


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
