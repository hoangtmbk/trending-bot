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
