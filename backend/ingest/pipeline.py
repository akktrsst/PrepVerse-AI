"""fetch -> dedupe -> enrich (Flash-Lite, batched) -> filter -> rank -> deep video digests (Flash) -> embed -> store."""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from google.genai import types

from app.config import Settings
from app.learn.catalog import TopicCatalog
from app.learn.models import Chapter, EnrichmentBatch, Resource, Topic, VideoDigest
from app.llm import LLM, LLMError
from app.prompts import render, untrusted
from app.store import Store

from . import ranking
from .models import RawItem
from .sources import arxiv, github, hackernews, rss, youtube
from .sources.common import http_client

log = logging.getLogger("ingest")

SOURCES = ("youtube", "arxiv", "github", "hackernews", "rss")
# Feeds and HN carry more announcements/news than tutorials, so they need a stronger match.
MIN_RELEVANCE = {"video": 3, "paper": 3, "repo": 3, "blog": 4, "discussion": 4}
ENRICH_BATCH = 10
EMBED_BATCH = 20
MAX_DEEP_VIDEO_SECONDS = 45 * 60  # longer videos keep the metadata summary (cost cap)


@dataclass
class RunStats:
    fetched: int = 0
    new: int = 0
    kept: int = 0
    deep_videos: int = 0
    failures: list[str] = field(default_factory=list)


def fmt_seconds(s: int) -> str:
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def parse_timestamp(ts: str) -> int | None:
    if not re.fullmatch(r"\d{1,2}(:\d{2}){1,2}", ts.strip()):
        return None
    total = 0
    for part in ts.strip().split(":"):
        total = total * 60 + int(part)
    return total


def valid_chapters(chapters: list[Chapter], duration_s: int) -> list[Chapter]:
    """Drop hallucinated chapters: unparseable or past the end of the video."""
    out, seen = [], set()
    for c in chapters:
        t = parse_timestamp(c.time)
        if t is None or t >= duration_s or t in seen:
            continue
        seen.add(t)
        out.append(Chapter(time=fmt_seconds(t), title=c.title.strip()[:120]))
    return sorted(out, key=lambda c: parse_timestamp(c.time))


class Pipeline:
    def __init__(self, settings: Settings, llm: LLM, store: Store, catalog: TopicCatalog,
                 client: httpx.Client | None = None):
        self.settings, self.llm, self.store, self.catalog = settings, llm, store, catalog
        self.client = client or http_client()
        self._tracked: set[str] = set()  # topics whose progress is written to the store

    # ---- 1. Fetch ----
    def collect(self, topics: list[Topic], sources: tuple[str, ...], stats: RunStats) -> list[RawItem]:
        items: list[RawItem] = []

        def safe(name: str, fn):
            source = name.split(":")[0].replace("hn", "hackernews")
            for t in topics:
                self._progress(t.id, source)
            try:
                got = fn()
                log.info("fetched %-24s %3d items", name, len(got))
                return got
            except Exception as e:  # one failing source never fails the run
                log.warning("source failed: %s (%s)", name, e)
                stats.failures.append(name)
                return []

        for t in topics:
            if "youtube" in sources:
                items += safe(f"youtube:{t.id}", lambda: youtube.fetch(self.client, self.settings.youtube_api_key, t))
            if "arxiv" in sources:
                items += safe(f"arxiv:{t.id}", lambda: arxiv.fetch(self.client, t))
            if "github" in sources:
                items += safe(f"github:{t.id}", lambda: github.fetch(self.client, self.settings.github_token, t))
            if "hackernews" in sources:
                items += safe(f"hn:{t.id}", lambda: hackernews.fetch(self.client, t))
        if "rss" in sources:
            for t in topics:
                self._progress(t.id, "rss")
            selected = {t.id for t in topics}
            feed_items, failed = rss.fetch(self.client, self.catalog)
            stats.failures += [f"rss:{f}" for f in failed]
            for i in feed_items:
                i.candidate_topics = [c for c in i.candidate_topics if c in selected]
            items += [i for i in feed_items if i.candidate_topics]
        return items

    # ---- 2. Dedupe ----
    def dedupe(self, items: list[RawItem]) -> list[RawItem]:
        merged: dict[str, RawItem] = {}
        for i in items:
            extra = self.catalog.match(f"{i.title} {i.text[:500]}")
            if i.id in merged:
                m = merged[i.id]
                m.candidate_topics = list(dict.fromkeys(m.candidate_topics + i.candidate_topics + extra))
            else:
                i.candidate_topics = list(dict.fromkeys(i.candidate_topics + extra))
                merged[i.id] = i
        existing = self.store.existing_resource_ids(list(merged))
        return [i for i in merged.values() if i.id not in existing]

    # ---- 3-5. Enrich, filter, rank ----
    def _enrich_batch(self, batch: list[RawItem]) -> list[Resource]:
        topic_ids = sorted({t for i in batch for t in i.candidate_topics})
        topics_txt = "\n".join(f"- {tid}: {self.catalog.get(tid).title}: {self.catalog.get(tid).description}"
                               for tid in topic_ids)
        items_txt = "\n\n".join(
            f"[{n}] ({i.type}) {i.title} | source: {i.source} | candidate topics: {', '.join(i.candidate_topics)}\n{i.text}"
            for n, i in enumerate(batch)
        )
        out = self.llm.generate_structured(
            render("ingest_enrich_user", topics=topics_txt, items=untrusted("items", items_txt, max_chars=30000)),
            EnrichmentBatch, tier="lite", system=render("ingest_enrich_system"),
            temperature=0.2, feature="ingest.enrich",
        )
        resources = []
        for e in out.items:
            if not 0 <= e.index < len(batch):
                continue
            raw = batch[e.index]
            rel = {r.topic_id: r.relevance for r in e.relevance if r.topic_id in raw.candidate_topics}
            keep = sorted((t for t, v in rel.items() if v >= MIN_RELEVANCE[raw.type]), key=lambda t: -rel[t])
            if not keep:
                continue
            resources.append(Resource(
                id=raw.id, topic_ids=keep, type=raw.type, title=raw.title, url=raw.url, source=raw.source,
                author=raw.author, published_at=raw.published_at, thumbnail=raw.thumbnail, metrics=raw.metrics,
                summary=e.summary.strip(), key_points=[p.strip() for p in e.key_points if p.strip()][:5],
                difficulty=e.difficulty, why_it_matters=e.why_it_matters.strip(),
                score=ranking.score(raw.type, rel[keep[0]], raw.metrics, raw.published_at),
                fetched_at=datetime.now(timezone.utc),
            ))
        return resources

    def enrich(self, items: list[RawItem], stats: RunStats) -> list[Resource]:
        resources = []
        for start in range(0, len(items), ENRICH_BATCH):
            batch = items[start:start + ENRICH_BATCH]
            try:
                resources += self._enrich_batch(batch)
            except LLMError as e:
                log.warning("enrich batch failed (%d items): %s", len(batch), e)
                stats.failures.append(f"enrich:{start}")
        return resources

    # ---- 6. Deep video digests ----
    def deepen_videos(self, resources: list[Resource], per_topic: int, stats: RunStats) -> None:
        if per_topic <= 0:
            return
        chosen: dict[str, Resource] = {}
        for tid in {t for r in resources for t in r.topic_ids}:
            videos = sorted((r for r in resources if r.type == "video" and r.topic_ids[0] == tid
                             and 0 < r.metrics.get("duration_s", 0) <= MAX_DEEP_VIDEO_SECONDS),
                            key=lambda r: r.score, reverse=True)
            for v in videos[:per_topic]:
                chosen[v.id] = v
        for v in chosen.values():
            duration = v.metrics["duration_s"]
            try:
                d = self.llm.generate_structured(
                    [types.Part.from_uri(file_uri=v.url, mime_type="video/*"),
                     render("ingest_video_digest", title=v.title, duration=fmt_seconds(duration))],
                    VideoDigest, tier="std", temperature=0.2, feature="ingest.video", low_media_resolution=True,
                )
            except LLMError as e:
                log.warning("video digest failed for %s: %s", v.url, e)
                continue
            v.summary = d.summary.strip() or v.summary
            v.key_points = [p.strip() for p in d.key_points if p.strip()][:6] or v.key_points
            v.chapters = valid_chapters(d.chapters, duration)
            stats.deep_videos += 1

    # ---- 7. Embed ----
    def embed(self, resources: list[Resource]) -> None:
        for start in range(0, len(resources), EMBED_BATCH):
            batch = resources[start:start + EMBED_BATCH]
            texts = [f"{r.title}\n{r.summary}\n" + "\n".join(r.key_points) for r in batch]
            for r, vec in zip(batch, self.llm.embed(texts)):
                r.embedding = vec

    # ---- Progress (shown on the topic page during on-demand refreshes) ----
    def _progress(self, topic_id: str, step: str, **changes) -> None:
        if topic_id in self._tracked:
            from app.learn.refresh import set_status
            set_status(self.store, topic_id, state=changes.pop("state", "running"), step=step, **changes)

    # ---- Run ----
    def run(self, topic_ids: list[str] | None = None, sources: tuple[str, ...] = SOURCES,
            dry_run: bool = False, deep_videos: int = 3,
            track_status: bool = False) -> tuple[RunStats, list[Resource]]:
        """Process topic by topic and save after each, so an interrupted run keeps its progress.

        With track_status, per-topic progress is written to the store for the UI.
        """
        stats = RunStats()
        topics = [t for t in self.catalog.topics if not topic_ids or t.id in topic_ids]
        per_topic_sources = tuple(s for s in sources if s != "rss")
        self._tracked = {t.id for t in topics} if track_status and not dry_run else set()

        # Feeds are fetched once; each feed item is processed with its first matching topic.
        feed_items: dict[str, list[RawItem]] = {}
        if "rss" in sources:
            for item in self.collect(topics, ("rss",), stats):
                feed_items.setdefault(item.candidate_topics[0], []).append(item)

        all_resources: list[Resource] = []
        current = None
        try:
            for t in topics:
                current = t.id
                raw = self.collect([t], per_topic_sources, stats) + feed_items.get(t.id, [])
                stats.fetched += len(raw)
                fresh = self.dedupe(raw)
                stats.new += len(fresh)
                self._progress(t.id, "summarise")
                resources = self.enrich(fresh, stats)
                stats.kept += len(resources)
                log.info("topic=%s fetched=%d new=%d kept=%d", t.id, len(raw), len(fresh), len(resources))
                if not dry_run and resources:
                    self._progress(t.id, "videos")
                    self.deepen_videos(resources, deep_videos, stats)
                    self._progress(t.id, "index")
                    self.embed(resources)
                    self.store.upsert_resources(resources)
                    self.store.refresh_topic_counts()
                found = sum(t.id in r.topic_ids for r in resources)  # some items only fit other topics
                self._progress(t.id, "done", state="done", found=found,
                               finished_at=datetime.now(timezone.utc),
                               message="" if found else "No new resources found this time.")
                all_resources += resources
        except Exception as e:
            if current:
                self._progress(current, "done", state="failed", finished_at=datetime.now(timezone.utc),
                               message="Something went wrong while fetching. Please try again later.")
            raise e
        finally:
            if not dry_run:
                self.store.refresh_topic_counts()
        return stats, sorted(all_resources, key=lambda r: r.score, reverse=True)
