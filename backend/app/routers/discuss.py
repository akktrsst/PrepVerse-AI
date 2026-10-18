import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..deps import UsageLimiter, current_user, get_discuss, get_store, get_usage
from ..discuss.engine import DiscussEngine
from ..discuss.models import DiscussSession, DiscussStart, MessageIn, Persona, Turn
from ..learn.models import ResourceBase
from ..notes.models import Note
from ..store import Store

router = APIRouter(prefix="/discuss", tags=["discuss"])


class SessionOut(BaseModel):
    id: str
    topic_id: str | None
    topic_title: str
    resource: ResourceBase | None
    persona: Persona
    turns: list[Turn]
    notes_generated: bool


def _out(session: DiscussSession, engine: DiscussEngine, store: Store) -> SessionOut:
    resource = store.get_resource(session.resource_id) if session.resource_id else None
    return SessionOut(
        id=session.id, topic_id=session.topic_id, topic_title=engine.topic_title(session),
        resource=resource.public() if resource else None, persona=session.persona,
        turns=session.turns, notes_generated=session.notes_generated,
    )


def _load(session_id: str, user: str, store: Store) -> DiscussSession:
    session = store.get_discuss(session_id)
    if not session or session.user_id != user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return session


@router.post("/sessions", response_model=SessionOut)
def start(body: DiscussStart, user: str = Depends(current_user),
          engine: DiscussEngine = Depends(get_discuss), store: Store = Depends(get_store)):
    return _out(engine.start(user, body), engine, store)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get(session_id: str, user: str = Depends(current_user),
        engine: DiscussEngine = Depends(get_discuss), store: Store = Depends(get_store)):
    return _out(_load(session_id, user, store), engine, store)


@router.post("/sessions/{session_id}/messages")
def message(session_id: str, body: MessageIn, user: str = Depends(current_user),
            usage: UsageLimiter = Depends(get_usage), engine: DiscussEngine = Depends(get_discuss),
            store: Store = Depends(get_store)):
    """Server-Sent Events: `delta` {text}*, then `citations` {citations} + `done`, or `error` {detail}."""
    session = _load(session_id, user, store)
    usage.charge(1)

    def events():
        for event, data in engine.reply(session, body.text, body.voice):
            yield f"event: {event}\ndata: {json.dumps(data)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/sessions/{session_id}/end", response_model=list[Note])
def end(session_id: str, user: str = Depends(current_user), usage: UsageLimiter = Depends(get_usage),
        engine: DiscussEngine = Depends(get_discuss), store: Store = Depends(get_store)):
    """Generate structured study notes from the conversation and save them to the notebook."""
    session = _load(session_id, user, store)
    usage.charge(1)
    return engine.make_notes(session)
