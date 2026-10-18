"""Curated blog feeds (seed/feeds.json). Fetched once per run; items are matched to
topics by keyword before the LLM decides final relevance."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import httpx

from app.learn.catalog import TopicCatalog

from ..models import RawItem
from .common import strip_html

FEEDS_FILE = Path(__file__).resolve().parents[2] / "seed" / "feeds.json"


def load_feeds(path: Path = FEEDS_FILE) -> list[dict]:
    return json.loads(path.read_text())


def _published(entry) -> datetime | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*t[:6], tzinfo=timezone.utc) if t else None


def parse(feed_xml: str, feed_name: str, catalog: TopicCatalog, max_age_days: int = 365,
          max_items: int = 25) -> list[RawItem]:
    """Newest topic-matching entries first, at most max_items per feed."""
    parsed = feedparser.parse(feed_xml)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    items = []
    for e in parsed.entries:
        url, title = e.get("link"), strip_html(e.get("title"), 300)
        if not url or not title:
            continue
        published = _published(e)
        if published and published < cutoff:
            continue
        content = e.get("summary") or (e.get("content") or [{}])[0].get("value", "")
        text = strip_html(content, 2000)
        topics = catalog.match(f"{title} {text[:800]}")
        if not topics:
            continue
        items.append(RawItem(type="blog", title=title, url=url, source=feed_name,
                             author=strip_html(e.get("author"), 120), published_at=published,
                             text=text, candidate_topics=topics))
    items.sort(key=lambda i: i.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[:max_items]


def fetch(client: httpx.Client, catalog: TopicCatalog, feeds: list[dict] | None = None) -> tuple[list[RawItem], list[str]]:
    """Returns (items, failed feed names). One bad feed never fails the run."""
    items, failed = [], []
    for feed in feeds or load_feeds():
        try:
            r = client.get(feed["url"])
            r.raise_for_status()
            items += parse(r.text, feed["name"], catalog, max_age_days=feed.get("max_age_days", 365))
        except Exception:
            failed.append(feed["name"])
    return items, failed
