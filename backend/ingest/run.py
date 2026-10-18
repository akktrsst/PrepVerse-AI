"""Daily ingestion job.

    python -m ingest.run                         # all topics, all sources
    python -m ingest.run --topic rag --dry-run   # preview ranked results, write nothing
    python -m ingest.run --sources arxiv,rss --deep-videos 0
"""

import argparse
import logging
import sys

from app.config import get_settings
from app.learn.catalog import TopicCatalog
from app.llm import LLM
from app.store import build_store

from .pipeline import SOURCES, Pipeline


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fetch and enrich learning resources.")
    p.add_argument("--topic", action="append", help="topic id (repeatable); default: all")
    p.add_argument("--sources", default=",".join(SOURCES), help=f"comma list from {SOURCES}")
    p.add_argument("--dry-run", action="store_true", help="enrich and print, don't embed or store")
    p.add_argument("--deep-videos", type=int, default=3, help="video digests per topic (0 to skip)")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    catalog = TopicCatalog.load()
    unknown = [t for t in args.topic or [] if not catalog.get(t)]
    if unknown:
        p.error(f"unknown topic(s): {', '.join(unknown)}. Known: {', '.join(t.id for t in catalog.topics)}")
    sources = tuple(s for s in args.sources.split(",") if s in SOURCES)
    if "youtube" in sources and not settings.youtube_api_key:
        logging.warning("YOUTUBE_API_KEY not set: skipping YouTube")
        sources = tuple(s for s in sources if s != "youtube")

    pipeline = Pipeline(settings, LLM(settings), build_store(settings), catalog)
    # Single-topic runs come from the "Find resources now" button: report progress to the UI.
    track = bool(args.topic) and len(args.topic) == 1
    stats, resources = pipeline.run(args.topic, sources, args.dry_run, args.deep_videos, track_status=track)

    print(f"\nfetched={stats.fetched} new={stats.new} kept={stats.kept} "
          f"deep_videos={stats.deep_videos} failures={stats.failures or 'none'}")
    for r in sorted(resources, key=lambda r: r.score, reverse=True)[:25]:
        print(f"  {r.score:.2f}  {r.type:<10} {','.join(r.topic_ids):<28} {r.title[:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
