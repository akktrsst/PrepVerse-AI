"""arXiv API (Atom). Metadata + abstracts only. arXiv asks for >= 3s between requests."""

import time
import xml.etree.ElementTree as ET

import httpx

from app.learn.models import Topic

from ..models import RawItem
from .common import parse_dt, strip_html

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}
_last_call = 0.0


def parse(atom_xml: str, topic_id: str) -> list[RawItem]:
    root = ET.fromstring(atom_xml)
    items = []
    for e in root.findall("a:entry", NS):
        url = (e.findtext("a:id", default="", namespaces=NS) or "").strip()
        title = strip_html(e.findtext("a:title", default="", namespaces=NS), 300)
        if not url or not title:
            continue
        authors = [a.findtext("a:name", default="", namespaces=NS) for a in e.findall("a:author", NS)]
        items.append(RawItem(
            type="paper",
            title=title,
            url=url.replace("http://", "https://"),
            source="arXiv",
            author=", ".join(authors[:3]) + (" et al." if len(authors) > 3 else ""),
            published_at=parse_dt(e.findtext("a:published", default=None, namespaces=NS)),
            text=strip_html(e.findtext("a:summary", default="", namespaces=NS), 2000),
            candidate_topics=[topic_id],
        ))
    return items


def fetch(client: httpx.Client, topic: Topic, max_results: int = 8) -> list[RawItem]:
    global _last_call
    wait = 3.0 - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    r = client.get(API, params={"search_query": topic.arxiv_query, "max_results": max_results,
                                "sortBy": "relevance", "sortOrder": "descending"})
    _last_call = time.monotonic()
    r.raise_for_status()
    return parse(r.text, topic.id)
