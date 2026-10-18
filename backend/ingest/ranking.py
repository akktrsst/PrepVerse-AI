"""Resource score in [0, 1]: relevance dominates; recency, engagement and source quality break ties."""

import math
from datetime import datetime, timezone

from app.learn.models import ResourceType

WEIGHTS = {"relevance": 0.45, "engagement": 0.25, "recency": 0.20, "source": 0.10}

# log10 value that counts as "maxed out" engagement for each type.
_ENGAGEMENT_SCALE: dict[ResourceType, tuple[str, float]] = {
    "video": ("views", 6.0),        # 1M views
    "repo": ("stars", 4.7),         # ~50k stars
    "discussion": ("points", 3.0),  # 1000 points
}
# Types without public engagement numbers get a neutral baseline.
_BASELINE = {"paper": 0.5, "blog": 0.6}
_CURATED_TYPES = {"blog"}  # feeds are hand-picked in seed/feeds.json


def engagement(type_: ResourceType, metrics: dict[str, int]) -> float:
    if type_ in _BASELINE:
        return _BASELINE[type_]
    key, scale = _ENGAGEMENT_SCALE[type_]
    return min(1.0, math.log10(metrics.get(key, 0) + 1) / scale)


def recency(published_at: datetime | None, now: datetime | None = None, half_life_days: float = 365.0) -> float:
    if not published_at:
        return 0.3
    age = ((now or datetime.now(timezone.utc)) - published_at).days
    return 0.5 ** (max(age, 0) / half_life_days)


def score(type_: ResourceType, relevance: int, metrics: dict[str, int], published_at: datetime | None,
          now: datetime | None = None) -> float:
    parts = {
        "relevance": (max(1, min(5, relevance)) - 1) / 4,
        "engagement": engagement(type_, metrics),
        "recency": recency(published_at, now),
        "source": 1.0 if type_ in _CURATED_TYPES else 0.5,
    }
    return round(sum(WEIGHTS[k] * v for k, v in parts.items()), 4)
