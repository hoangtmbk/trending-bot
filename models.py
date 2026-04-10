from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


@dataclass
class RawItem:
    title: str
    url: str
    source: str
    description: str
    metrics: dict
    timestamp: str

    @classmethod
    def from_dict(cls, d: dict) -> RawItem:
        return cls(
            title=d["title"],
            url=d["url"],
            source=d["source"],
            description=d["description"],
            metrics=d["metrics"],
            timestamp=d["timestamp"],
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScoredItem:
    raw_items: list[RawItem]
    momentum_score: float
    final_score: float
    sources: list[str]
    category: str
    llm_summary: str
    interest_score: int
    normalized_score: float = 0.0

    @property
    def title(self) -> str:
        return self.raw_items[0].title

    @property
    def url(self) -> str:
        return self.raw_items[0].url

    @property
    def description(self) -> str:
        return self.raw_items[0].description

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "description": self.description,
            "momentum_score": self.momentum_score,
            "normalized_score": self.normalized_score,
            "final_score": self.final_score,
            "sources": self.sources,
            "category": self.category,
            "llm_summary": self.llm_summary,
            "interest_score": self.interest_score,
            "raw_items": [r.to_dict() for r in self.raw_items],
        }


@dataclass
class AnalysisReport:
    slug: str
    title: str
    what_it_is: str
    why_trending: str
    pain_point: str
    gap_analysis: str
    competitors: list[str]
    app_idea: str
    feasibility: dict

    def to_dict(self) -> dict:
        return asdict(self)

    def to_markdown(self) -> str:
        competitors_str = ", ".join(self.competitors) if self.competitors else "None found"
        feasibility_lines = "\n".join(f"- **{k.title()}:** {v}" for k, v in self.feasibility.items())
        return f"""# {self.title}

## What It Is
{self.what_it_is}

## Why It's Trending
{self.why_trending}

## Pain Point
{self.pain_point}

## Gap Analysis
{self.gap_analysis}

## Competitors
{competitors_str}

## Proposed Solution
{self.app_idea}

## Feasibility
{feasibility_lines}
"""
