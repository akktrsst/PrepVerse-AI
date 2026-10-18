"""YouTube Data API v3. Quota: search.list = 100 units, videos.list = 1 unit (10k/day free).

We store metadata + our own summary and embed videos via the official player.
"""

import re
from datetime import datetime, timedelta, timezone

import httpx

from app.learn.models import Topic

from ..models import RawItem
from .common import parse_dt, strip_html

API = "https://www.googleapis.com/youtube/v3"
MIN_SECONDS = 180  # skip Shorts and teasers
_DUR_RE = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def iso_duration_seconds(value: str) -> int:
    m = _DUR_RE.fullmatch(value or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def parse(videos_payload: dict, topic_id: str) -> list[RawItem]:
    """Parse a videos.list response (part=snippet,statistics,contentDetails)."""
    items = []
    for v in videos_payload.get("items", []):
        snip, stats = v.get("snippet", {}), v.get("statistics", {})
        seconds = iso_duration_seconds(v.get("contentDetails", {}).get("duration", ""))
        if seconds < MIN_SECONDS:
            continue
        thumbs = snip.get("thumbnails", {})
        thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
        items.append(RawItem(
            type="video",
            title=strip_html(snip.get("title"), 300),
            url=f"https://www.youtube.com/watch?v={v['id']}",
            source=snip.get("channelTitle", "YouTube"),
            author=snip.get("channelTitle", ""),
            published_at=parse_dt(snip.get("publishedAt")),
            thumbnail=thumb,
            metrics={"views": int(stats.get("viewCount", 0)), "likes": int(stats.get("likeCount", 0)),
                     "duration_s": seconds},
            text=strip_html(snip.get("description"), 1500),
            candidate_topics=[topic_id],
            video_id=v["id"],
        ))
    return items


def fetch(client: httpx.Client, api_key: str, topic: Topic, per_query: int = 8) -> list[RawItem]:
    if not api_key:
        return []
    after = (datetime.now(timezone.utc) - timedelta(days=730)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids: list[str] = []
    for q in topic.search_queries:
        r = client.get(f"{API}/search", params={
            "key": api_key, "part": "id", "type": "video", "q": q, "maxResults": per_query,
            "order": "relevance", "relevanceLanguage": "en", "videoEmbeddable": "true",
            "publishedAfter": after, "safeSearch": "strict",
        })
        r.raise_for_status()
        ids += [i["id"]["videoId"] for i in r.json().get("items", []) if i.get("id", {}).get("videoId")]
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    r = client.get(f"{API}/videos", params={
        "key": api_key, "part": "snippet,statistics,contentDetails", "id": ",".join(ids[:50]),
    })
    r.raise_for_status()
    return parse(r.json(), topic.id)
