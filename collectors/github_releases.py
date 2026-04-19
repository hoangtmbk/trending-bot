from __future__ import annotations
import logging
import os
from datetime import datetime, timezone

import requests

from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)


class GitHubReleasesCollector(BaseCollector):
    """Polls /repos/{owner}/{repo}/releases for a watched-repo list.

    Different from the discovery-oriented github scout: here we care about
    *releases* for specific repos we already know matter (vLLM, llama.cpp,
    etc.), not which repos are trending overall.
    """
    source_name = "github_release"

    def __init__(self, repos: list[str], per_repo: int = 3):
        self.repos = repos
        self.per_repo = per_repo

    def collect(self) -> list[RawItem]:
        token = os.environ.get("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        items: list[RawItem] = []
        for repo in self.repos:
            try:
                resp = requests.get(
                    f"https://api.github.com/repos/{repo}/releases",
                    params={"per_page": self.per_repo},
                    headers=headers,
                    timeout=15,
                )
                if resp.status_code != 200:
                    logger.warning(f"GitHub releases {repo}: HTTP {resp.status_code}")
                    continue
                releases = resp.json()
            except Exception as e:
                logger.warning(f"GitHub releases {repo} failed: {e}")
                continue

            for rel in releases:
                if rel.get("draft") or rel.get("prerelease"):
                    continue
                tag = rel.get("tag_name") or rel.get("name")
                url = rel.get("html_url")
                if not tag or not url:
                    continue
                published = rel.get("published_at") or ""
                try:
                    ts = datetime.fromisoformat(published.replace("Z", "+00:00")).isoformat() \
                        if published else datetime.now(timezone.utc).isoformat()
                except (ValueError, AttributeError):
                    ts = datetime.now(timezone.utc).isoformat()

                items.append(RawItem(
                    title=f"{repo} {tag}",
                    url=url,
                    source=self.source_name,
                    description=(rel.get("body") or "")[:500],
                    metrics={
                        "repo": repo,
                        "tag": tag,
                        "release_id": rel.get("id"),
                    },
                    timestamp=ts,
                ))

        logger.info(f"GitHub releases: {len(items)} across {len(self.repos)} repos")
        return items
