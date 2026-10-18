"""Topic catalogue (backend/seed/topics.json). Static config, like the seed question bank."""

import json
import re
from pathlib import Path

from .models import Topic

TOPICS_FILE = Path(__file__).resolve().parents[2] / "seed" / "topics.json"


class TopicCatalog:
    def __init__(self, topics: list[Topic]):
        self.topics = topics
        self._by_id = {t.id: t for t in topics}
        # Keywords match at a word start ("rag" must not match "storage"); a
        # keyword may be a prefix ("fine-tun" matches "fine-tuning").
        self._patterns = {
            t.id: re.compile("|".join(rf"(?<![a-z0-9]){re.escape(k.lower())}" for k in t.keywords))
            for t in topics if t.keywords
        }

    @classmethod
    def load(cls, path: Path = TOPICS_FILE) -> "TopicCatalog":
        return cls([Topic.model_validate(t) for t in json.loads(path.read_text())])

    def get(self, topic_id: str | None) -> Topic | None:
        return self._by_id.get(topic_id) if topic_id else None

    def match(self, text: str) -> list[str]:
        """Topic ids whose keywords appear in the text (cheap pre-filter before the LLM)."""
        low = text.lower()
        return [tid for tid, pat in self._patterns.items() if pat.search(low)]
