from __future__ import annotations
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from models import RawItem

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    source_name: str = ""

    @abstractmethod
    def collect(self) -> list[RawItem]:
        ...

    def save(self, items: list[RawItem], data_dir: Path) -> Path:
        raw_dir = data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        out_path = raw_dir / f"{self.source_name}.json"
        with open(out_path, "w") as f:
            json.dump([item.to_dict() for item in items], f, indent=2)
        logger.info(f"Saved {len(items)} items to {out_path}")
        return out_path

    def run(self, data_dir: Path) -> list[RawItem]:
        items = self.collect()
        self.save(items, data_dir)
        return items
