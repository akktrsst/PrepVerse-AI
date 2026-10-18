from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from ..interview.models import Difficulty, Level, Module

ResourceType = Literal["video", "paper", "blog", "repo", "discussion"]
RESOURCE_TYPES: tuple[ResourceType, ...] = ("video", "paper", "blog", "repo", "discussion")


class Topic(BaseModel):
    id: str
    module: Module
    title: str
    description: str
    level: Level
    search_queries: list[str]
    arxiv_query: str
    github_query: str
    keywords: list[str] = []  # for matching RSS / HN items to topics


class Chapter(BaseModel):
    time: str = Field(description="Timestamp like 12:40")
    title: str


class ResourceBase(BaseModel):
    """What the API returns. Summaries and links only: never full articles or transcripts."""

    id: str
    topic_ids: list[str]
    type: ResourceType
    title: str
    url: str
    source: str
    author: str = ""
    published_at: datetime | None = None
    thumbnail: str | None = None
    metrics: dict[str, int] = {}
    summary: str
    key_points: list[str] = []
    difficulty: Difficulty = "medium"
    why_it_matters: str = ""
    chapters: list[Chapter] = []
    score: float = 0.0
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Resource(ResourceBase):
    embedding: list[float] = []

    def public(self) -> ResourceBase:
        return ResourceBase.model_validate(self.model_dump(exclude={"embedding"}))


# ---- Structured LLM outputs ----

class TopicRelevance(BaseModel):
    topic_id: str
    relevance: int = Field(description="1-5; 5 = core learning material for this topic")


class ResourceEnrichment(BaseModel):
    index: int = Field(description="The [n] index of the item in the input list")
    relevance: list[TopicRelevance]
    summary: str = Field(description="2-3 sentence plain-language summary")
    key_points: list[str] = Field(description="3-5 short takeaways")
    difficulty: Difficulty
    why_it_matters: str = Field(description="One sentence: why this matters for interviews")


class EnrichmentBatch(BaseModel):
    items: list[ResourceEnrichment]


class VideoDigest(BaseModel):
    summary: str
    key_points: list[str]
    chapters: list[Chapter]
