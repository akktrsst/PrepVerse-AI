import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings
from app.learn.catalog import TopicCatalog
from app.learn.models import Chapter
from app.store import MemoryStore
from ingest import ranking
from ingest.models import RawItem, normalize_url, resource_id
from ingest.pipeline import Pipeline, valid_chapters
from ingest.sources import arxiv, github, hackernews, rss, youtube

from .fakes import FakeLLM

FIX = Path(__file__).parent / "fixtures"
CATALOG = TopicCatalog.load()


def test_youtube_parser_skips_shorts_and_reads_metrics():
    items = youtube.parse(json.loads((FIX / "youtube_videos.json").read_text()), "rag")
    assert [i.video_id for i in items] == ["abc123XYZ01"]
    v = items[0]
    assert v.type == "video" and v.metrics == {"views": 250000, "likes": 9000, "duration_s": 750}
    assert v.url == "https://www.youtube.com/watch?v=abc123XYZ01"
    assert "&amp;" not in v.text and v.candidate_topics == ["rag"]
    assert youtube.iso_duration_seconds("PT1H2M3S") == 3723


def test_arxiv_parser():
    [p] = arxiv.parse((FIX / "arxiv.xml").read_text(), "rag")
    assert p.type == "paper" and p.source == "arXiv"
    assert p.title == "Retrieval-Augmented Generation for Large Language Models: A Survey"
    assert p.author == "Yunfan Gao, Yun Xiong, Xinyu Gao et al."
    assert p.url.startswith("https://arxiv.org/abs/")


def test_rss_parser_matches_topics_and_drops_old_or_unrelated():
    items = rss.parse((FIX / "feed.xml").read_text(), "Example", CATALOG, max_age_days=3650 * 3)
    titles = {i.title: i for i in items}
    assert "Our company picnic photos" not in titles  # no topic keywords
    assert "rag" in titles["Building better RAG with rerankers"].candidate_topics
    assert titles["Building better RAG with rerankers"].text.startswith("How a cross-encoder")  # HTML stripped
    recent = rss.parse((FIX / "feed.xml").read_text(), "Example", CATALOG, max_age_days=365 * 3)
    assert "An old post about attention" not in {i.title for i in recent}


def test_github_and_hn_parsers_apply_thresholds():
    repos = github.parse(json.loads((FIX / "github.json").read_text()), "rag")
    assert [r.title for r in repos] == ["acme/rag-kit"] and repos[0].metrics["stars"] == 12000
    threads = hackernews.parse(json.loads((FIX / "hn.json").read_text()), "rag")
    assert [t.url for t in threads] == ["https://news.ycombinator.com/item?id=4242"]
    assert threads[0].metrics == {"points": 320, "comments": 140}
    assert hackernews.top_comments({"children": [{"text": "<p>Use recall@k</p>", "children": [1, 2]},
                                                 {"text": "meh", "children": []}]}, n=1) == "Use recall@k"


def test_url_normalisation_dedupes_variants():
    assert normalize_url("https://arxiv.org/pdf/2312.10997v5") == normalize_url("https://arxiv.org/abs/2312.10997")
    assert resource_id("https://Blog.example.com/post/#intro") == resource_id("https://blog.example.com/post")


def test_ranking_prefers_relevance_then_engagement():
    now = datetime.now(timezone.utc)
    core = ranking.score("video", 5, {"views": 10_000}, now, now)
    loose = ranking.score("video", 3, {"views": 10_000_000}, now, now)
    assert core > loose
    assert ranking.score("repo", 4, {"stars": 50_000}, now, now) > ranking.score("repo", 4, {"stars": 200}, now, now)
    assert ranking.score("paper", 4, {}, now - timedelta(days=1500), now) < ranking.score("paper", 4, {}, now, now)
    assert 0 <= core <= 1


def test_valid_chapters_drops_hallucinated_timestamps():
    chapters = [Chapter(time="0:00", title="Intro"), Chapter(time="1:13:50", title="Too late"),
                Chapter(time="5:30", title="Core"), Chapter(time="oops", title="Bad"), Chapter(time="00:00", title="Dup")]
    assert [c.time for c in valid_chapters(chapters, duration_s=750)] == ["0:00", "5:30"]


class StubPipeline(Pipeline):
    """Serves fixture items instead of hitting the network."""

    def __init__(self, items, **kw):
        super().__init__(Settings(_env_file=None), kw.pop("llm"), kw.pop("store"), CATALOG, client=object())
        self._items = items

    def collect(self, topics, sources, stats):
        wanted = {t.id for t in topics}
        return [i.model_copy(deep=True) for i in self._items
                if ("rss" in sources) == (i.type == "blog") and set(i.candidate_topics) & wanted]


def _items():
    vid = youtube.parse(json.loads((FIX / "youtube_videos.json").read_text()), "rag")
    return vid + arxiv.parse((FIX / "arxiv.xml").read_text(), "rag") + [
        RawItem(type="blog", title="RAG rerankers", url="https://blog.example.com/rag", source="Blog",
                text="rerankers for rag", candidate_topics=["rag"]),
    ]


def test_pipeline_enriches_ranks_embeds_and_stores():
    store, llm = MemoryStore(), FakeLLM(relevance=4)
    stats, resources = StubPipeline(_items(), llm=llm, store=store).run(["rag"])
    assert stats.new == 3 and stats.kept == 3 and stats.deep_videos == 1
    video = store.get_resource(resource_id("https://www.youtube.com/watch?v=abc123XYZ01"))
    assert video.summary == "Deep video summary"
    assert [c.time for c in video.chapters] == ["0:00", "5:30"]  # hallucinated 1:13:50 dropped
    assert all(len(store.get_resource(r.id).embedding) > 0 for r in resources)
    assert store.topic_counts()["rag"] == {"video": 1, "paper": 1, "blog": 1}
    assert ("ingest.enrich", "lite") in llm.calls

    # A second run finds nothing new (dedupe against the store) and spends no LLM calls.
    llm2 = FakeLLM()
    stats2, _ = StubPipeline(_items(), llm=llm2, store=store).run(["rag"])
    assert stats2.new == 0 and not [c for c in llm2.calls if c[0].startswith("ingest")]


def test_pipeline_relevance_threshold_is_stricter_for_blogs():
    store = MemoryStore()
    stats, resources = StubPipeline(_items(), llm=FakeLLM(relevance=3), store=store).run(["rag"], deep_videos=0)
    assert {r.type for r in resources} == {"video", "paper"}  # blog needs >= 4


def test_dry_run_writes_nothing():
    store = MemoryStore()
    stats, resources = StubPipeline(_items(), llm=FakeLLM(), store=store).run(["rag"], dry_run=True)
    assert len(resources) == 3 and store.topic_counts() == {}
