from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

NoteKind = Literal["highlight", "ai_note", "manual"]
NoteColor = Literal["yellow", "green", "blue", "pink"]
NoteSection = Literal["takeaway", "definition", "review_question"]


class NoteIn(BaseModel):
    kind: Literal["highlight", "manual"] = "highlight"
    topic_id: str | None = Field(default=None, max_length=80)
    resource_id: str | None = Field(default=None, max_length=80)
    session_id: str | None = Field(default=None, max_length=80)
    quote: str = Field(default="", max_length=2000)
    text: str = Field(default="", max_length=4000)
    color: NoteColor = "yellow"
    tags: list[str] = Field(default=[], max_length=10)


class NotePatch(BaseModel):
    text: str | None = Field(default=None, max_length=4000)
    color: NoteColor | None = None
    tags: list[str] | None = Field(default=None, max_length=10)


class Note(BaseModel):
    id: str
    user_id: str
    kind: NoteKind
    topic_id: str | None = None
    resource_id: str | None = None
    session_id: str | None = None
    section: NoteSection | None = None  # ai_note only
    quote: str = ""
    text: str = ""
    color: NoteColor = "yellow"
    tags: list[str] = []
    source_title: str | None = None
    source_url: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
