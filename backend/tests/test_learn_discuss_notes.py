import json
from datetime import datetime, timezone

import pytest

from app.learn.models import Resource
from app.store import FileStore, MemoryStore

from .fakes import FakeLLM, fake_embedding, make_client


def res(id_, title, type_="video", topics=("rag",), score=0.5, year=2025):
    summary = f"{title} explained"
    return Resource(id=id_, topic_ids=list(topics), type=type_, title=title, url=f"https://example.com/{id_}",
                    source="Example", summary=summary, key_points=["kp"], score=score,
                    published_at=datetime(year, 1, 1, tzinfo=timezone.utc),
                    embedding=fake_embedding(f"{title} {summary}"))


@pytest.fixture
def store():
    s = MemoryStore()
    s.upsert_resources([
        res("r1", "Hybrid search with BM25 and rerankers", score=0.9, year=2024),
        res("r2", "Chunking strategies for retrieval", type_="blog", score=0.6, year=2026),
        res("r3", "LoRA fine-tuning walkthrough", topics=("fine-tuning",), score=0.8),
    ])
    return s


def sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


# ---------------- Learn ----------------

def test_topics_and_resources(store):
    c = make_client(store=store)
    topics = {t["id"]: t for t in c.get("/api/learn/topics").json()}
    assert len(topics) == 15
    assert topics["rag"]["counts"] == {"video": 1, "blog": 1} and topics["rag"]["total"] == 2

    best = c.get("/api/learn/topics/rag/resources").json()
    assert [r["id"] for r in best] == ["r1", "r2"]
    assert "embedding" not in best[0]
    assert [r["id"] for r in c.get("/api/learn/topics/rag/resources?sort=recent").json()] == ["r2", "r1"]
    assert [r["id"] for r in c.get("/api/learn/topics/rag/resources?type=blog").json()] == ["r2"]
    assert c.get("/api/learn/topics/nope/resources").status_code == 404
    assert c.get("/api/learn/resources/r3").json()["title"] == "LoRA fine-tuning walkthrough"


def test_all_view_interleaves_types():
    from app.routers.learn import interleave_types

    items = [res("v1", "a", score=0.9), res("v2", "b", score=0.8), res("r1", "c", type_="repo", score=0.95),
             res("r2", "d", type_="repo", score=0.94), res("p1", "e", type_="paper", score=0.5)]
    items.sort(key=lambda r: r.score, reverse=True)
    assert [r.id for r in interleave_types(items)] == ["r1", "v1", "p1", "r2", "v2"]


def test_semantic_search_ranks_by_similarity(store):
    c = make_client(store=store)
    hits = c.get("/api/learn/search", params={"q": "lora fine-tuning"}).json()
    assert hits[0]["id"] == "r3"
    scoped = c.get("/api/learn/search", params={"q": "lora fine-tuning", "topic_id": "rag"}).json()
    assert "r3" not in [h["id"] for h in scoped]


# ---------------- Discuss ----------------

def test_discuss_streams_grounded_reply_with_citations(store):
    llm = FakeLLM(reply="Use hybrid search [1] and rerank. Also see [9].")
    c = make_client(llm=llm, store=store)
    s = c.post("/api/discuss/sessions", json={"topic_id": "rag"}).json()
    assert s["topic_title"] == "Retrieval-Augmented Generation" and s["turns"] == []

    r = c.post(f"/api/discuss/sessions/{s['id']}/messages", json={"text": "How do I improve retrieval?"})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = sse(r.text)
    assert [e for e, _ in events if e != "delta"] == ["citations", "done"]
    assert "".join(d["text"] for e, d in events if e == "delta").strip() == "Use hybrid search [1] and rerank. Also see [9]."
    cites = dict(events)["citations"]["citations"]
    assert len(cites) == 1 and cites[0]["n"] == 1  # [9] doesn't exist -> not cited

    feature, prompt, system = next(p for p in llm.prompts if p[0] == "discuss.reply")
    assert "<untrusted_sources>" in prompt and "Hybrid search with BM25" in prompt
    assert "<untrusted_message>" in prompt and "VOICE MODE" not in system

    saved = c.get(f"/api/discuss/sessions/{s['id']}").json()
    assert [t["role"] for t in saved["turns"]] == ["user", "assistant"]
    assert saved["turns"][1]["citations"][0]["resource_id"] == cites[0]["resource_id"]


def test_voice_mode_and_pinned_resource(store):
    llm = FakeLLM()
    c = make_client(llm=llm, store=store)
    s = c.post("/api/discuss/sessions", json={"resource_id": "r3", "persona": "socratic"}).json()
    assert s["topic_id"] == "fine-tuning" and s["resource"]["id"] == "r3"
    c.post(f"/api/discuss/sessions/{s['id']}/messages", json={"text": "explain", "voice": True})
    _, prompt, system = next(p for p in llm.prompts if p[0] == "discuss.reply")
    assert "VOICE MODE" in system and "Socratic" in system
    assert prompt.index("[1] (video) LoRA fine-tuning walkthrough") >= 0  # pinned resource is source [1]


def test_history_is_summarised_when_long(store):
    llm = FakeLLM()
    c = make_client(llm=llm, store=store)
    sid = c.post("/api/discuss/sessions", json={"topic_id": "rag"}).json()["id"]
    for i in range(8):  # summarising kicks in once >12 messages are stored
        c.post(f"/api/discuss/sessions/{sid}/messages", json={"text": f"question {i}"})
    assert ("discuss.summarize", "lite") in llm.calls
    last_prompt = [p for p in llm.prompts if p[0] == "discuss.reply"][-1][1]
    assert "Earlier the learner discussed chunking" in last_prompt
    assert "question 0" not in last_prompt and "question 7" in last_prompt


def test_stream_error_is_reported_and_not_saved(store):
    llm = FakeLLM()
    llm.fail_stream = True
    c = make_client(llm=llm, store=store)
    sid = c.post("/api/discuss/sessions", json={"topic_id": "rag"}).json()["id"]
    events = sse(c.post(f"/api/discuss/sessions/{sid}/messages", json={"text": "hi"}).text)
    assert events[-1][0] == "error"
    assert c.get(f"/api/discuss/sessions/{sid}").json()["turns"] == []


def test_end_session_creates_ai_notes_and_replaces_them(store):
    c = make_client(store=store)
    sid = c.post("/api/discuss/sessions", json={"topic_id": "rag"}).json()["id"]
    assert c.post(f"/api/discuss/sessions/{sid}/end").status_code == 409  # nothing discussed yet
    c.post(f"/api/discuss/sessions/{sid}/messages", json={"text": "hi"})
    notes = c.post(f"/api/discuss/sessions/{sid}/end").json()
    assert sorted(n["section"] for n in notes) == ["definition", "review_question", "takeaway"]
    assert all(n["kind"] == "ai_note" and n["topic_id"] == "rag" for n in notes)
    c.post(f"/api/discuss/sessions/{sid}/end")
    assert len(c.get("/api/notes").json()) == 3  # regenerated, not duplicated


def test_discuss_validation(store):
    c = make_client(store=store)
    assert c.post("/api/discuss/sessions", json={"topic_id": "nope"}).status_code == 404
    assert c.post("/api/discuss/sessions", json={"resource_id": "nope"}).status_code == 404
    assert c.get("/api/discuss/sessions/missing").status_code == 404


def test_discuss_messages_count_against_daily_limit(store):
    c = make_client(store=store, limit=1)
    sid = c.post("/api/discuss/sessions", json={"topic_id": "rag"}).json()["id"]
    assert c.post(f"/api/discuss/sessions/{sid}/messages", json={"text": "a"}).status_code == 200
    assert c.post(f"/api/discuss/sessions/{sid}/messages", json={"text": "b"}).status_code == 429


# ---------------- Notes ----------------

def test_notes_crud_and_source_enrichment(store):
    c = make_client(store=store)
    n = c.post("/api/notes", json={"quote": "Rerankers re-score chunks", "text": "remember this",
                               "color": "green", "resource_id": "r1"}).json()
    assert n["topic_id"] == "rag" and n["source_title"] == "Hybrid search with BM25 and rerankers"
    assert c.post("/api/notes", json={"quote": " ", "text": ""}).status_code == 422
    assert c.post("/api/notes", json={"quote": "x", "color": "purple"}).status_code == 422

    upd = c.patch(f"/api/notes/{n['id']}", json={"text": "edited", "color": "pink"}).json()
    assert upd["text"] == "edited" and upd["color"] == "pink" and upd["quote"] == n["quote"]

    c.post("/api/notes", json={"kind": "manual", "text": "general thought"})
    assert len(c.get("/api/notes").json()) == 2
    assert [x["id"] for x in c.get("/api/notes", params={"topic_id": "rag"}).json()] == [n["id"]]
    assert len(c.get("/api/notes", params={"kind": "manual"}).json()) == 1

    assert c.delete(f"/api/notes/{n['id']}").status_code == 204
    assert c.patch(f"/api/notes/{n['id']}", json={"text": "x"}).status_code == 404


def test_markdown_export(store):
    c = make_client(store=store)
    c.post("/api/notes", json={"quote": "Hybrid search wins", "text": "my comment", "resource_id": "r1"})
    sid = c.post("/api/discuss/sessions", json={"topic_id": "rag"}).json()["id"]
    c.post(f"/api/discuss/sessions/{sid}/messages", json={"text": "hi"})
    c.post(f"/api/discuss/sessions/{sid}/end")
    c.post("/api/notes", json={"quote": "from the chat", "session_id": sid})
    r = c.get("/api/notes/export.md")
    assert r.headers["content-type"].startswith("text/markdown")
    md = r.text
    assert "## Retrieval-Augmented Generation" in md
    assert "> Hybrid search wins" in md and "my comment" in md
    assert "[Hybrid search with BM25 and rerankers](https://example.com/r1)" in md
    assert f"(http://testserver/discuss/?session={sid})" in md  # relative links made absolute
    assert "**Definitions**" in md and "- **Reranker**: Re-scores retrieved chunks." in md


def test_notes_are_private_per_user(store, monkeypatch):
    from app import deps

    c = make_client(store=store, auth_disabled=False)
    monkeypatch.setattr(deps, "_verify_firebase_token", lambda token, project: token)  # token == uid
    alice = {"Authorization": "Bearer alice"}
    bob = {"Authorization": "Bearer bob"}
    n = c.post("/api/notes", json={"quote": "secret"}, headers=alice).json()
    assert c.get("/api/notes", headers=bob).json() == []
    assert c.delete(f"/api/notes/{n['id']}", headers=bob).status_code == 404
    assert c.get("/api/notes").status_code == 401
    sid = c.post("/api/discuss/sessions", json={"topic_id": "rag"}, headers=alice).json()["id"]
    assert c.get(f"/api/discuss/sessions/{sid}", headers=bob).status_code == 404


def test_public_config(store):
    c = make_client(store=store)
    assert c.get("/api/config/public").json() == {"auth_disabled": True, "firebase": None}


def test_file_store_persists_and_sees_other_process_writes(tmp_path):
    path = tmp_path / "store.json"
    api_side = FileStore(path)
    ingest_side = FileStore(path)
    ingest_side.upsert_resources([res("r9", "Agent memory patterns", topics=("agent-memory",))])
    assert api_side.get_resource("r9").title == "Agent memory patterns"  # reloaded on change
    api_side.add_usage("u", "2026-10-18", 2)
    assert FileStore(path).add_usage("u", "2026-10-18", 1) == 3
