"""Persistence for sessions, resources, notes and usage counters.

MemoryStore is for local dev and tests; FirestoreStore is for Cloud Run
(serverless, no idle cost).
"""

import json
import math
import os
import threading
from collections import Counter
from pathlib import Path
from typing import Protocol

from .config import Settings
from .discuss.models import DiscussSession
from .interview.models import Session
from .learn.models import Resource
from .notes.models import Note


class Store(Protocol):
    # Interview
    def get_session(self, session_id: str) -> Session | None: ...
    def save_session(self, session: Session) -> None: ...
    def add_usage(self, user_id: str, day: str, n: int) -> int:
        """Add n calls to the user's counter for `day` and return the new total."""
        ...

    # Learn
    def upsert_resources(self, resources: list[Resource]) -> None: ...
    def get_resource(self, resource_id: str) -> Resource | None: ...
    def existing_resource_ids(self, ids: list[str]) -> set[str]: ...
    def list_resources(self, topic_id: str) -> list[Resource]:
        """All resources tagged with the topic (embeddings omitted)."""
        ...
    def search_resources(self, vector: list[float], k: int, topic_id: str | None = None) -> list[Resource]: ...
    def topic_counts(self) -> dict[str, dict[str, int]]:
        """{topic_id: {resource_type: count}}"""
        ...
    def refresh_topic_counts(self) -> None: ...

    # Notes
    def list_notes(self, user_id: str) -> list[Note]: ...
    def get_note(self, note_id: str) -> Note | None: ...
    def save_note(self, note: Note) -> None: ...
    def delete_note(self, note_id: str) -> None: ...

    # Discuss
    def get_discuss(self, session_id: str) -> DiscussSession | None: ...
    def save_discuss(self, session: DiscussSession) -> None: ...

    # Small JSON documents (e.g. per-topic refresh status), shared across processes/instances.
    def get_meta(self, key: str) -> dict | None: ...
    def set_meta(self, key: str, value: dict) -> None: ...


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class MemoryStore:
    def __init__(self):
        self._sessions: dict[str, dict] = {}
        self._usage: dict[tuple[str, str], int] = {}
        self._resources: dict[str, Resource] = {}
        self._notes: dict[str, dict] = {}
        self._discuss: dict[str, dict] = {}
        self._meta: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ---- Interview ----
    def get_session(self, session_id: str) -> Session | None:
        data = self._sessions.get(session_id)
        return Session.model_validate(data) if data else None

    def save_session(self, session: Session) -> None:
        self._sessions[session.id] = session.model_dump(mode="json")

    def add_usage(self, user_id: str, day: str, n: int) -> int:
        with self._lock:
            key = (user_id, day)
            self._usage[key] = self._usage.get(key, 0) + n
            return self._usage[key]

    # ---- Learn ----
    def upsert_resources(self, resources: list[Resource]) -> None:
        for r in resources:
            self._resources[r.id] = r.model_copy(deep=True)

    def get_resource(self, resource_id: str) -> Resource | None:
        r = self._resources.get(resource_id)
        return r.model_copy(deep=True) if r else None

    def existing_resource_ids(self, ids: list[str]) -> set[str]:
        return {i for i in ids if i in self._resources}

    def list_resources(self, topic_id: str) -> list[Resource]:
        return [r.model_copy(update={"embedding": []}) for r in self._resources.values() if topic_id in r.topic_ids]

    def search_resources(self, vector: list[float], k: int, topic_id: str | None = None) -> list[Resource]:
        pool = [r for r in self._resources.values() if r.embedding and (topic_id is None or topic_id in r.topic_ids)]
        pool.sort(key=lambda r: cosine(vector, r.embedding), reverse=True)
        return [r.model_copy(update={"embedding": []}) for r in pool[:k]]

    def topic_counts(self) -> dict[str, dict[str, int]]:
        counts: dict[str, Counter] = {}
        for r in self._resources.values():
            for t in r.topic_ids:
                counts.setdefault(t, Counter())[r.type] += 1
        return {t: dict(c) for t, c in counts.items()}

    def refresh_topic_counts(self) -> None:
        pass  # computed live

    # ---- Notes ----
    def list_notes(self, user_id: str) -> list[Note]:
        return [Note.model_validate(n) for n in self._notes.values() if n["user_id"] == user_id]

    def get_note(self, note_id: str) -> Note | None:
        data = self._notes.get(note_id)
        return Note.model_validate(data) if data else None

    def save_note(self, note: Note) -> None:
        self._notes[note.id] = note.model_dump(mode="json")

    def delete_note(self, note_id: str) -> None:
        self._notes.pop(note_id, None)

    # ---- Discuss ----
    def get_discuss(self, session_id: str) -> DiscussSession | None:
        data = self._discuss.get(session_id)
        return DiscussSession.model_validate(data) if data else None

    def save_discuss(self, session: DiscussSession) -> None:
        self._discuss[session.id] = session.model_dump(mode="json")

    # ---- Meta ----
    def get_meta(self, key: str) -> dict | None:
        value = self._meta.get(key)
        return dict(value) if value is not None else None

    def set_meta(self, key: str, value: dict) -> None:
        self._meta[key] = dict(value)


# Resource fields minus the embedding, for projections that skip the vector.
_RESOURCE_FIELDS = [f for f in Resource.model_fields if f != "embedding"]


class FirestoreStore:
    def __init__(self, project: str | None = None):
        from google.cloud import firestore
        from google.cloud.firestore_v1.base_query import FieldFilter
        from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
        from google.cloud.firestore_v1.vector import Vector

        self._fs = firestore
        self._Filter, self._Distance, self._Vector = FieldFilter, DistanceMeasure, Vector
        self._db = firestore.Client(project=project or None)

    def _col(self, name: str):
        return self._db.collection(name)

    # ---- Interview ----
    def get_session(self, session_id: str) -> Session | None:
        snap = self._col("interview_sessions").document(session_id).get()
        return Session.model_validate(snap.to_dict()) if snap.exists else None

    def save_session(self, session: Session) -> None:
        self._col("interview_sessions").document(session.id).set(session.model_dump(mode="json"))

    def add_usage(self, user_id: str, day: str, n: int) -> int:
        ref = self._col("usage").document(f"{user_id}_{day}")

        @self._fs.transactional
        def bump(tx) -> int:
            snap = ref.get(transaction=tx)
            total = (snap.get("count") if snap.exists else 0) + n
            tx.set(ref, {"user_id": user_id, "day": day, "count": total})
            return total

        return bump(self._db.transaction())

    # ---- Learn ----
    def _to_resource(self, data: dict) -> Resource:
        if "embedding" in data and data["embedding"] is not None:
            data["embedding"] = list(data["embedding"])
        return Resource.model_validate(data)

    def upsert_resources(self, resources: list[Resource]) -> None:
        for i in range(0, len(resources), 400):  # Firestore batch limit is 500
            batch = self._db.batch()
            for r in resources[i:i + 400]:
                data = r.model_dump(mode="json")
                data["embedding"] = self._Vector(r.embedding) if r.embedding else None
                batch.set(self._col("resources").document(r.id), data)
            batch.commit()

    def get_resource(self, resource_id: str) -> Resource | None:
        snap = self._col("resources").document(resource_id).get()
        return self._to_resource(snap.to_dict()) if snap.exists else None

    def existing_resource_ids(self, ids: list[str]) -> set[str]:
        refs = [self._col("resources").document(i) for i in ids]
        return {s.id for s in self._db.get_all(refs, field_paths=["id"]) if s.exists}

    def list_resources(self, topic_id: str) -> list[Resource]:
        q = (self._col("resources")
             .where(filter=self._Filter("topic_ids", "array_contains", topic_id))
             .select(_RESOURCE_FIELDS))
        return [self._to_resource(s.to_dict()) for s in q.stream()]

    def search_resources(self, vector: list[float], k: int, topic_id: str | None = None) -> list[Resource]:
        q = self._col("resources")
        if topic_id:
            q = q.where(filter=self._Filter("topic_ids", "array_contains", topic_id))
        hits = q.find_nearest(
            vector_field="embedding", query_vector=self._Vector(vector),
            limit=k, distance_measure=self._Distance.COSINE,
        ).get()
        return [self._to_resource({**s.to_dict(), "embedding": []}) for s in hits]

    def topic_counts(self) -> dict[str, dict[str, int]]:
        snap = self._col("meta").document("topic_counts").get()
        return snap.to_dict().get("counts", {}) if snap.exists else {}

    def refresh_topic_counts(self) -> None:
        counts: dict[str, Counter] = {}
        for s in self._col("resources").select(["topic_ids", "type"]).stream():
            d = s.to_dict()
            for t in d.get("topic_ids", []):
                counts.setdefault(t, Counter())[d["type"]] += 1
        self._col("meta").document("topic_counts").set({"counts": {t: dict(c) for t, c in counts.items()}})

    # ---- Notes ----
    def list_notes(self, user_id: str) -> list[Note]:
        q = self._col("notes").where(filter=self._Filter("user_id", "==", user_id))
        return [Note.model_validate(s.to_dict()) for s in q.stream()]

    def get_note(self, note_id: str) -> Note | None:
        snap = self._col("notes").document(note_id).get()
        return Note.model_validate(snap.to_dict()) if snap.exists else None

    def save_note(self, note: Note) -> None:
        self._col("notes").document(note.id).set(note.model_dump(mode="json"))

    def delete_note(self, note_id: str) -> None:
        self._col("notes").document(note_id).delete()

    # ---- Discuss ----
    def get_discuss(self, session_id: str) -> DiscussSession | None:
        snap = self._col("discuss_sessions").document(session_id).get()
        return DiscussSession.model_validate(snap.to_dict()) if snap.exists else None

    def save_discuss(self, session: DiscussSession) -> None:
        self._col("discuss_sessions").document(session.id).set(session.model_dump(mode="json"))

    # ---- Meta ----
    def get_meta(self, key: str) -> dict | None:
        snap = self._col("meta").document(key).get()
        return snap.to_dict() if snap.exists else None

    def set_meta(self, key: str, value: dict) -> None:
        self._col("meta").document(key).set(value)


class FileStore(MemoryStore):
    """Local-dev persistence: MemoryStore state mirrored to a JSON file.

    Reloads when another process (e.g. `python -m ingest.run`) changed the file,
    so the API server sees freshly ingested resources without a restart.
    Not for production: use FirestoreStore.
    """

    def __init__(self, path: Path):
        super().__init__()
        self._path = path
        self._mtime: float | None = None
        self._io = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        data = json.loads(self._path.read_text() or "{}")
        self._sessions = data.get("sessions", {})
        self._usage = {tuple(k.split("|", 1)): v for k, v in data.get("usage", {}).items()}
        self._resources = {k: Resource.model_validate(v) for k, v in data.get("resources", {}).items()}
        self._notes = data.get("notes", {})
        self._discuss = data.get("discuss", {})
        self._meta = data.get("meta", {})
        self._mtime = self._path.stat().st_mtime

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "sessions": self._sessions,
            "usage": {f"{u}|{d}": v for (u, d), v in self._usage.items()},
            "resources": {k: r.model_dump(mode="json") for k, r in self._resources.items()},
            "notes": self._notes,
            "discuss": self._discuss,
            "meta": self._meta,
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, self._path)
        self._mtime = self._path.stat().st_mtime

    def _refresh(self) -> None:
        if self._path.exists() and self._path.stat().st_mtime != self._mtime:
            self._load()


def _file_store_method(name: str, writes: bool):
    base = getattr(MemoryStore, name)

    def method(self, *args, **kwargs):
        with self._io:
            self._refresh()
            result = base(self, *args, **kwargs)
            if writes:
                self._save()
            return result

    method.__name__ = name
    return method


for _name in ("save_session", "add_usage", "upsert_resources", "save_note", "delete_note", "save_discuss", "set_meta"):
    setattr(FileStore, _name, _file_store_method(_name, writes=True))
for _name in ("get_meta", "get_session", "get_resource", "existing_resource_ids", "list_resources", "search_resources",
              "topic_counts", "list_notes", "get_note", "get_discuss"):
    setattr(FileStore, _name, _file_store_method(_name, writes=False))


BACKEND_DIR = Path(__file__).resolve().parents[1]


def build_store(settings: Settings) -> Store:
    if settings.store_backend == "firestore":
        return FirestoreStore(settings.gcp_project)
    if settings.store_backend == "file":
        path = Path(settings.local_data_path)
        return FileStore(path if path.is_absolute() else BACKEND_DIR / path)
    return MemoryStore()
