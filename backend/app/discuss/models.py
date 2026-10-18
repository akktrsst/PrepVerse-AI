from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from ..learn.models import ResourceType

Persona = Literal["tutor", "socratic", "quickfire"]


class DiscussStart(BaseModel):
    topic_id: str | None = Field(default=None, max_length=80)
    resource_id: str | None = Field(default=None, max_length=80)
    persona: Persona = "tutor"


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: bool = False


class Citation(BaseModel):
    n: int
    resource_id: str
    title: str
    url: str
    type: ResourceType


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    citations: list[Citation] = []
    voice: bool = False


class DiscussSession(BaseModel):
    id: str
    user_id: str
    topic_id: str | None = None
    resource_id: str | None = None
    persona: Persona = "tutor"
    turns: list[Turn] = []
    summary: str = ""  # rolling summary of turns[:summarized_upto]
    summarized_upto: int = 0
    notes_generated: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---- Structured LLM output ----

class Definition(BaseModel):
    term: str
    meaning: str


class SessionNotes(BaseModel):
    takeaways: list[str] = Field(description="3-6 key takeaways from the discussion")
    definitions: list[Definition] = Field(description="Important terms that came up, with one-line meanings")
    review_questions: list[str] = Field(description="2-4 interview-style questions to self-test later")
