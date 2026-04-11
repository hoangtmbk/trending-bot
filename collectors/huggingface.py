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
                sort="trending_score",
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
