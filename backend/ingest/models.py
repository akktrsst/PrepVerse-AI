import hashlib
import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel

from app.learn.models import ResourceType


def normalize_url(url: str) -> str:
    """Stable identity for dedupe: lowercase host, no fragment, no trailing slash, arXiv version stripped."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    if parts.netloc.endswith("arxiv.org"):
        path = re.sub(r"v\d+$", "", path.replace("/pdf/", "/abs/"))
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, parts.query, ""))


def resource_id(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode()).hexdigest()[:24]


class RawItem(BaseModel):
    """A fetched item before LLM enrichment. `text` is only used for summarising, never stored."""

    type: ResourceType
    title: str
    url: str
    source: str
    author: str = ""
    published_at: datetime | None = None
    thumbnail: str | None = None
    metrics: dict[str, int] = {}
    text: str = ""
    candidate_topics: list[str] = []
    video_id: str | None = None

    @property
    def id(self) -> str:
        return resource_id(self.url)
