from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..deps import UsageLimiter, current_user, get_catalog, get_llm, get_refresh, get_store, get_usage
from ..interview.models import Level, Module
from ..learn.catalog import TopicCatalog
from ..learn.models import ResourceBase, ResourceType
from ..learn.refresh import STEP_LABELS, STEPS, RefreshService, RefreshStatus, get_status
from ..llm import LLM
from ..store import Store

router = APIRouter(prefix="/learn", tags=["learn"])


class TopicOut(BaseModel):
    id: str
    module: Module
    title: str
    description: str
    level: Level
    counts: dict[str, int]
    total: int


def _topic_out(topic, counts: dict[str, dict[str, int]]) -> TopicOut:
    c = counts.get(topic.id, {})
    return TopicOut(id=topic.id, module=topic.module, title=topic.title, description=topic.description,
                    level=topic.level, counts=c, total=sum(c.values()))


@router.get("/topics", response_model=list[TopicOut])
def topics(catalog: TopicCatalog = Depends(get_catalog), store: Store = Depends(get_store)):
    counts = store.topic_counts()
    return [_topic_out(t, counts) for t in catalog.topics]


@router.get("/topics/{topic_id}", response_model=TopicOut)
def topic(topic_id: str, catalog: TopicCatalog = Depends(get_catalog), store: Store = Depends(get_store)):
    t = catalog.get(topic_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "topic not found")
    return _topic_out(t, store.topic_counts())


@router.get("/topics/{topic_id}/resources", response_model=list[ResourceBase])
def topic_resources(
    topic_id: str,
    type: ResourceType | None = None,
    sort: Literal["score", "recent"] = "score",
    limit: int = Query(default=60, ge=1, le=200),
    catalog: TopicCatalog = Depends(get_catalog),
    store: Store = Depends(get_store),
):
    if not catalog.get(topic_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "topic not found")
    items = [r for r in store.list_resources(topic_id) if type is None or r.type == type]
    if sort == "recent":
        items.sort(key=lambda r: r.published_at.timestamp() if r.published_at else 0, reverse=True)
    else:
        items.sort(key=lambda r: r.score, reverse=True)
        if type is None:
            items = interleave_types(items)
    return [r.public() for r in items[:limit]]


def interleave_types(items: list) -> list:
    """Mix resource types in the "All" view (best video, best paper, best repo, ...) so one
    high-engagement type (e.g. repos with 50k stars) doesn't fill the whole first screen.
    Order within each type, and between rounds, stays by score."""
    queues: dict[str, list] = {}
    for r in items:
        queues.setdefault(r.type, []).append(r)
    out = []
    while queues:
        heads = sorted(queues, key=lambda t: queues[t][0].score, reverse=True)
        for t in heads:
            out.append(queues[t].pop(0))
            if not queues[t]:
                del queues[t]
    return out


@router.get("/resources/{resource_id}", response_model=ResourceBase)
def resource(resource_id: str, store: Store = Depends(get_store)):
    r = store.get_resource(resource_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    return r.public()


@router.get("/search", response_model=list[ResourceBase])
def search(
    q: str = Query(min_length=2, max_length=200),
    topic_id: str | None = None,
    limit: int = Query(default=12, ge=1, le=30),
    llm: LLM = Depends(get_llm),
    store: Store = Depends(get_store),
):
    """Semantic search. Embeddings are cheap, so this isn't charged against the daily cap."""
    vec = llm.embed([q], task_type="RETRIEVAL_QUERY")[0]
    return [r.public() for r in store.search_resources(vec, limit, topic_id=topic_id)]


class RefreshOut(RefreshStatus):
    steps: list[tuple[str, str]] = [(s, STEP_LABELS[s]) for s in STEPS]


def _require_topic(topic_id: str, catalog: TopicCatalog) -> None:
    if not catalog.get(topic_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "topic not found")


@router.get("/topics/{topic_id}/refresh", response_model=RefreshOut)
def refresh_status(topic_id: str, catalog: TopicCatalog = Depends(get_catalog), store: Store = Depends(get_store)):
    _require_topic(topic_id, catalog)
    return RefreshOut(**get_status(store, topic_id).model_dump())


@router.post("/topics/{topic_id}/refresh", response_model=RefreshOut)
def refresh(topic_id: str, user: str = Depends(current_user), usage: UsageLimiter = Depends(get_usage),
            catalog: TopicCatalog = Depends(get_catalog), service: RefreshService = Depends(get_refresh)):
    """Fetch resources for one topic now (instead of waiting for the daily job).

    Rate-limited per topic (cooldown) and charged against the user's daily AI budget.
    """
    _require_topic(topic_id, catalog)
    # ~3 LLM calls: enrichment batches + one video digest. Charged only if a run starts.
    status_ = service.request(topic_id, on_start=lambda: usage.charge(3))
    return RefreshOut(**status_.model_dump())
