import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse

from ..deps import current_user, get_catalog, get_store
from ..learn.catalog import TopicCatalog
from ..notes.export import notes_to_markdown
from ..notes.models import Note, NoteIn, NoteKind, NotePatch
from ..store import Store

router = APIRouter(prefix="/notes", tags=["notes"])

MAX_NOTES_PER_USER = 5000  # abuse guard, not a plan limit


def _load(note_id: str, user: str, store: Store) -> Note:
    note = store.get_note(note_id)
    if not note or note.user_id != user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "note not found")
    return note


def _filtered(store: Store, user: str, topic_id: str | None, kind: NoteKind | None) -> list[Note]:
    notes = [n for n in store.list_notes(user)
             if (topic_id is None or n.topic_id == topic_id) and (kind is None or n.kind == kind)]
    return sorted(notes, key=lambda n: n.created_at, reverse=True)


@router.get("", response_model=list[Note])
def list_notes(topic_id: str | None = None, kind: NoteKind | None = None,
               user: str = Depends(current_user), store: Store = Depends(get_store)):
    return _filtered(store, user, topic_id, kind)


@router.post("", response_model=Note, status_code=status.HTTP_201_CREATED)
def create_note(body: NoteIn, user: str = Depends(current_user), store: Store = Depends(get_store),
                catalog: TopicCatalog = Depends(get_catalog)):
    if not body.quote.strip() and not body.text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "a note needs a quote or text")
    if len(store.list_notes(user)) >= MAX_NOTES_PER_USER:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "note limit reached")

    topic_id, source_title, source_url = body.topic_id, None, None
    if body.resource_id and (r := store.get_resource(body.resource_id)):
        source_title, source_url = r.title, r.url
        topic_id = topic_id or (r.topic_ids[0] if r.topic_ids else None)
    elif body.session_id and (s := store.get_discuss(body.session_id)) and s.user_id == user:
        topic = catalog.get(s.topic_id)
        source_title = f"Discussion: {topic.title}" if topic else "Discussion"
        source_url = f"/discuss/?session={s.id}"
        topic_id = topic_id or s.topic_id
    if topic_id and not catalog.get(topic_id):
        topic_id = None

    note = Note(id=uuid.uuid4().hex, user_id=user, source_title=source_title, source_url=source_url,
                **{**body.model_dump(), "topic_id": topic_id})
    store.save_note(note)
    return note


@router.patch("/{note_id}", response_model=Note)
def update_note(note_id: str, body: NotePatch, user: str = Depends(current_user), store: Store = Depends(get_store)):
    note = _load(note_id, user, store)
    changes = body.model_dump(exclude_none=True)
    note = note.model_copy(update={**changes, "updated_at": datetime.now(timezone.utc)})
    store.save_note(note)
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: str, user: str = Depends(current_user), store: Store = Depends(get_store)):
    _load(note_id, user, store)
    store.delete_note(note_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/export.md", response_class=PlainTextResponse)
def export_markdown(request: Request, topic_id: str | None = None, user: str = Depends(current_user),
                    store: Store = Depends(get_store), catalog: TopicCatalog = Depends(get_catalog)):
    md = notes_to_markdown(_filtered(store, user, topic_id, None), catalog, base_url=str(request.base_url))
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="prepverse-notes.md"'})
