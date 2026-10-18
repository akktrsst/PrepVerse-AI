from datetime import datetime, timedelta, timezone

from app.learn.refresh import RefreshService, get_status, set_status
from app.store import MemoryStore

from .fakes import FakeLLM, make_client
from .test_ingest import StubPipeline, _items


class RecordingRunner:
    def __init__(self, fail=False):
        self.started, self.fail = [], fail

    def start(self, topic_id):
        if self.fail:
            raise RuntimeError("no job")
        self.started.append(topic_id)


def client_with(runner, store=None, limit=50):
    store = store or MemoryStore()
    c = make_client(store=store, limit=limit)
    c.app.state.refresh = RefreshService(store, runner)
    return c, store


def test_refresh_lifecycle_with_progress_and_cooldown():
    runner = RecordingRunner()
    c, store = client_with(runner, limit=4)
    assert c.get("/api/learn/topics/rag/refresh").json()["state"] == "idle"

    st = c.post("/api/learn/topics/rag/refresh").json()
    assert st["state"] == "queued" and runner.started == ["rag"]
    assert [k for k, _ in st["steps"]][:3] == ["queued", "rss", "youtube"]
    # Already running: no second run and no second charge (limit 4 would be exceeded).
    assert c.post("/api/learn/topics/rag/refresh").json()["state"] == "queued" and runner.started == ["rag"]

    # The pipeline (here on fixtures) reports progress and completion into the store.
    StubPipeline(_items(), llm=FakeLLM(), store=store).run(["rag"], track_status=True)
    done = c.get("/api/learn/topics/rag/refresh").json()
    assert done["state"] == "done" and done["found"] == 3 and done["step"] == "done"
    assert done["next_allowed_at"] is not None
    assert c.get("/api/learn/topics/rag").json()["total"] == 3

    # Cooldown: refused, and not charged.
    r = c.post("/api/learn/topics/rag/refresh")
    assert r.status_code == 409 and runner.started == ["rag"]


def test_refresh_charges_only_when_started_and_respects_daily_limit():
    runner = RecordingRunner()
    c, _ = client_with(runner, limit=2)  # a refresh costs 3
    assert c.post("/api/learn/topics/rag/refresh").status_code == 429
    assert runner.started == [] and c.get("/api/learn/topics/rag/refresh").json()["state"] == "idle"


def test_runner_failure_and_stale_runs_become_failed():
    c, store = client_with(RecordingRunner(fail=True))
    assert c.post("/api/learn/topics/rag/refresh").json()["state"] == "failed"

    set_status(store, "mcp", state="running", step="arxiv")
    old = store.get_meta("refresh:mcp")
    old["updated_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    store.set_meta("refresh:mcp", old)
    assert get_status(store, "mcp").state == "failed"
    # A failed run can be retried immediately (no cooldown).
    c.app.state.refresh = RefreshService(store, RecordingRunner())
    assert c.post("/api/learn/topics/mcp/refresh").json()["state"] == "queued"


def test_pipeline_records_failure():
    store = MemoryStore()

    class Exploding(StubPipeline):
        def enrich(self, items, stats):
            raise RuntimeError("boom")

    try:
        Exploding(_items(), llm=FakeLLM(), store=store).run(["rag"], track_status=True)
    except RuntimeError:
        pass
    assert get_status(store, "rag").state == "failed"


def test_refresh_unknown_topic_and_auth():
    c, _ = client_with(RecordingRunner())
    assert c.post("/api/learn/topics/nope/refresh").status_code == 404
    from app.config import Settings
    from app.main import create_app
    from fastapi.testclient import TestClient

    secured = TestClient(create_app(settings=Settings(auth_disabled=False, _env_file=None), llm=FakeLLM(), store=MemoryStore()))
    assert secured.post("/api/learn/topics/rag/refresh").status_code == 401
    assert secured.get("/api/learn/topics/rag/refresh").status_code == 200  # status is public
