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
