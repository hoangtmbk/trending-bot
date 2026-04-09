from __future__ import annotations
import logging
from datetime import datetime, timezone
import requests
from collectors.base import BaseCollector
from models import RawItem

logger = logging.getLogger(__name__)

DEFAULT_SUBREDDITS = [
    "MachineLearning", "LocalLLaMA", "artificial",
    "ChatGPT", "singularity", "StableDiffusion",
]


class RedditCollector(BaseCollector):
    """Reddit collector using PRAW (requires API credentials)."""
    source_name = "reddit"

    def __init__(self, client_id: str, client_secret: str, user_agent: str,
                 subreddits: list[str] | None = None):
        import praw
        self.reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        self.subreddits = subreddits or DEFAULT_SUBREDDITS

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


class RedditPublicCollector(BaseCollector):
    """Fallback Reddit collector using public JSON API (no credentials needed)."""
    source_name = "reddit"

    def __init__(self, user_agent: str = "trending-bot/1.0",
                 subreddits: list[str] | None = None):
        self.user_agent = user_agent
        self.subreddits = subreddits or DEFAULT_SUBREDDITS

    def collect(self) -> list[RawItem]:
        items = []
        headers = {"User-Agent": self.user_agent}
        for sub_name in self.subreddits:
            try:
                url = f"https://www.reddit.com/r/{sub_name}/hot.json?limit=25"
                resp = requests.get(url, headers=headers, timeout=10)
                resp.raise_for_status()
                posts = resp.json().get("data", {}).get("children", [])
                for post in posts:
                    d = post["data"]
                    item = RawItem(
                        title=d["title"],
                        url=f"https://reddit.com{d['permalink']}",
                        source=self.source_name,
                        description=(d.get("selftext") or "")[:500],
                        metrics={
                            "score": d.get("score", 0),
                            "upvote_ratio": d.get("upvote_ratio", 0),
                            "num_comments": d.get("num_comments", 0),
                            "total_awards": d.get("total_awards_received", 0),
                            "num_crossposts": d.get("num_crossposts", 0),
                            "subreddit": sub_name,
                        },
                        timestamp=datetime.fromtimestamp(
                            d["created_utc"], tz=timezone.utc
                        ).isoformat(),
                    )
                    items.append(item)
            except Exception as e:
                logger.error(f"Reddit public API error for r/{sub_name}: {e}")

        logger.info(f"Reddit public collector found {len(items)} posts")
        return items
