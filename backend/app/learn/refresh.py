"""On-demand topic refresh: "Find resources now" on an empty (or stale) topic page.

The ingestion pipeline writes its progress to the store (`refresh:<topic>` meta
documents), so status is visible from any API instance, whether the work runs
in a local thread or as a Cloud Run Job execution.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol

from pydantic import BaseModel

from ..config import Settings
from ..errors import StateError
from ..store import Store

log = logging.getLogger(__name__)

RefreshState = Literal["idle", "queued", "running", "done", "failed"]

STEPS = ["queued", "rss", "youtube", "arxiv", "github", "hackernews", "summarise", "videos", "index", "done"]  # pipeline order
STEP_LABELS = {
    "queued": "Starting",
    "youtube": "Searching YouTube",
    "arxiv": "Searching arXiv papers",
    "github": "Searching GitHub repos",
    "hackernews": "Searching Hacker News",
    "rss": "Reading AI blogs",
    "summarise": "Summarising and ranking with AI",
    "videos": "Watching top videos for chapters",
    "index": "Indexing for search",
    "done": "Done",
}

COOLDOWN = timedelta(hours=6)       # a topic can be refreshed at most this often
STALE_RUN = timedelta(minutes=20)   # a "running" status older than this is treated as dead
ON_DEMAND_DEEP_VIDEOS = 1           # keep on-demand runs quick and cheap


class RefreshStatus(BaseModel):
    topic_id: str
    state: RefreshState = "idle"
    step: str = ""
    label: str = ""
    found: int = 0           # new resources saved by the last run
    message: str = ""
    started_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None
    next_allowed_at: datetime | None = None


def _key(topic_id: str) -> str:
    return f"refresh:{topic_id}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_status(store: Store, topic_id: str) -> RefreshStatus:
    data = store.get_meta(_key(topic_id))
    status = RefreshStatus.model_validate(data) if data else RefreshStatus(topic_id=topic_id)
    if status.state in ("queued", "running") and status.updated_at and _now() - status.updated_at > STALE_RUN:
        status = status.model_copy(update={"state": "failed", "message": "The previous run stopped responding."})
    if status.finished_at and status.state in ("done", "failed"):
        status.next_allowed_at = status.finished_at + COOLDOWN if status.state == "done" else None
    return status


def set_status(store: Store, topic_id: str, **changes) -> RefreshStatus:
    current = get_status(store, topic_id)
    step = changes.get("step", current.step)
    status = current.model_copy(update={**changes, "label": STEP_LABELS.get(step, step), "updated_at": _now()})
    store.set_meta(_key(topic_id), status.model_dump(mode="json"))
    return status


# ---- Runners ----

class Runner(Protocol):
    def start(self, topic_id: str) -> None: ...


class ThreadRunner:
    """Local dev: run the pipeline in a background thread of the API process."""

    def __init__(self, settings: Settings, llm, store: Store, catalog):
        self.settings, self.llm, self.store, self.catalog = settings, llm, store, catalog

    def start(self, topic_id: str) -> None:
        def work():
            from ingest.pipeline import Pipeline  # imported lazily: ingest deps are optional for the API

            try:
                Pipeline(self.settings, self.llm, self.store, self.catalog).run(
                    [topic_id], deep_videos=ON_DEMAND_DEEP_VIDEOS, track_status=True)
            except Exception as e:  # the pipeline records failures itself; this is a last resort
                log.exception("refresh failed for %s", topic_id)
                set_status(self.store, topic_id, state="failed", message=str(e)[:200], finished_at=_now())

        threading.Thread(target=work, name=f"refresh-{topic_id}", daemon=True).start()


class CloudRunJobRunner:
    """Production: start the `prepverse-ingest` Cloud Run Job for one topic.

    Cloud Run throttles CPU outside requests, so long work must not run in the API process.
    The service account needs roles/run.developer (run.jobs.runWithOverrides).
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def start(self, topic_id: str) -> None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        creds, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        project = self.settings.gcp_project or project
        url = (f"https://run.googleapis.com/v2/projects/{project}/locations/{self.settings.ingest_job_region}"
               f"/jobs/{self.settings.ingest_job_name}:run")
        body = {"overrides": {"containerOverrides": [{"args": [
            "-m", "ingest.run", "--topic", topic_id, "--deep-videos", str(ON_DEMAND_DEEP_VIDEOS)]}]}}
        resp = AuthorizedSession(creds).post(url, json=body, timeout=20)
        if resp.status_code >= 300:
            raise RuntimeError(f"could not start ingest job ({resp.status_code}): {resp.text[:200]}")


def build_runner(settings: Settings, llm, store: Store, catalog) -> Runner:
    if settings.ingest_job_name:
        return CloudRunJobRunner(settings)
    return ThreadRunner(settings, llm, store, catalog)


class RefreshService:
    def __init__(self, store: Store, runner: Runner):
        self.store, self.runner = store, runner
        self._lock = threading.Lock()

    def request(self, topic_id: str, on_start=None) -> RefreshStatus:
        """Start a refresh unless one is running or the topic was refreshed recently.

        `on_start` runs only when a new run will actually start (e.g. to charge usage);
        if it raises, nothing starts.
        """
        with self._lock:
            status = get_status(self.store, topic_id)
            if status.state in ("queued", "running"):
                return status
            if status.next_allowed_at and _now() < status.next_allowed_at:
                raise StateError("This topic was refreshed recently. Try again later.")
            if on_start:
                on_start()
            status = set_status(self.store, topic_id, state="queued", step="queued", found=0, message="",
                                started_at=_now(), finished_at=None)
        try:
            self.runner.start(topic_id)
        except Exception:
            log.exception("could not start refresh for %s", topic_id)
            return set_status(self.store, topic_id, state="failed", message="Couldn't start the crawler.",
                              finished_at=_now())
        return status
