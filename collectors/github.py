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
