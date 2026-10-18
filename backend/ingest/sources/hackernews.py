"""Hacker News via the Algolia API. We index the discussion thread and summarise its top comments."""

from datetime import datetime, timedelta, timezone

import httpx

from app.learn.models import Topic

from ..models import RawItem
from .common import parse_dt, strip_html

SEARCH = "https://hn.algolia.com/api/v1/search"
ITEM = "https://hn.algolia.com/api/v1/items/{id}"
MIN_POINTS = 50


def parse(payload: dict, topic_id: str) -> list[RawItem]:
    items = []
    for h in payload.get("hits", []):
        if not h.get("title") or (h.get("points") or 0) < MIN_POINTS:
            continue
        link = h.get("url") or ""
        items.append(RawItem(
            type="discussion",
            title=strip_html(h["title"], 300),
            url=f"https://news.ycombinator.com/item?id={h['objectID']}",
            source="Hacker News",
            author=h.get("author", ""),
            published_at=parse_dt(h.get("created_at")),
            metrics={"points": int(h.get("points") or 0), "comments": int(h.get("num_comments") or 0)},
            text=strip_html(f"Linked article: {link}. {h.get('story_text') or ''}", 800),
            candidate_topics=[topic_id],
        ))
    return items


def top_comments(item_payload: dict, n: int = 5, chars: int = 300) -> str:
    kids = [c for c in item_payload.get("children", []) if c.get("text")]
    kids.sort(key=lambda c: len(c.get("children", [])), reverse=True)  # most-replied first
    return " | ".join(strip_html(c["text"], chars) for c in kids[:n])


def fetch(client: httpx.Client, topic: Topic, per_topic: int = 6) -> list[RawItem]:
    since = int((datetime.now(timezone.utc) - timedelta(days=730)).timestamp())
    r = client.get(SEARCH, params={
        "query": topic.title.replace("&", " "), "tags": "story", "hitsPerPage": per_topic,
        "numericFilters": f"points>{MIN_POINTS},created_at_i>{since}",
    })
    r.raise_for_status()
    items = parse(r.json(), topic.id)
    for item in items:
        try:
            hn_id = item.url.rsplit("=", 1)[1]
            c = client.get(ITEM.format(id=hn_id))
            c.raise_for_status()
            item.text = f"{item.text} Top comments: {top_comments(c.json())}"[:2000]
        except httpx.HTTPError:
            pass
    return items
