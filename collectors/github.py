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

        seen = set()
        unique = []
        for item in items:
            if item.url not in seen:
                seen.add(item.url)
                unique.append(item)

        logger.info(f"GitHub collector found {len(unique)} repos")
        return unique
