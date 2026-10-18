from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..deps import UsageLimiter, current_user, get_engine, get_store, get_usage
from ..interview.engine import InterviewEngine
from ..interview.models import InterviewConfig, Report, Session, SessionStatus
from ..store import Store

router = APIRouter(prefix="/interview", tags=["interview"])


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=6000)


class TurnOut(BaseModel):
    """What the client sees. Key points and evaluations stay server-side until the report."""

    session_id: str
    status: SessionStatus
    question_number: int  # 1-based; equals total_questions + 1 once all are answered
    total_questions: int
    topic: str | None
    question: str | None
    is_followup: bool
    report: Report | None = None


def _turn(session: Session) -> TurnOut:
    current = session.questions[session.current] if session.status == "in_progress" else None
    return TurnOut(
        session_id=session.id,
        status=session.status,
        question_number=session.current + 1,
        total_questions=len(session.questions),
        topic=current.planned.topic if current else None,
        question=current.exchanges[-1].question if current else None,
        is_followup=current.exchanges[-1].is_followup if current else False,
        report=session.report,
    )


def _load(session_id: str, user: str, store: Store) -> Session:
    session = store.get_session(session_id)
    if not session or session.user_id != user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return session


@router.post("/start", response_model=TurnOut)
def start(
    config: InterviewConfig,
    user: str = Depends(current_user),
    usage: UsageLimiter = Depends(get_usage),
    engine: InterviewEngine = Depends(get_engine),
):
    usage.charge(1)
    return _turn(engine.start(user, config))


@router.get("/{session_id}", response_model=TurnOut)
def get(session_id: str, user: str = Depends(current_user), store: Store = Depends(get_store)):
    return _turn(_load(session_id, user, store))


@router.post("/{session_id}/answer", response_model=TurnOut)
def answer(
    session_id: str,
    body: AnswerIn,
    user: str = Depends(current_user),
    usage: UsageLimiter = Depends(get_usage),
    engine: InterviewEngine = Depends(get_engine),
    store: Store = Depends(get_store),
):
    session = _load(session_id, user, store)
    usage.charge(1)
    return _turn(engine.answer(session, body.answer))


@router.post("/{session_id}/finish", response_model=Report)
def finish(
    session_id: str,
    user: str = Depends(current_user),
    usage: UsageLimiter = Depends(get_usage),
    engine: InterviewEngine = Depends(get_engine),
    store: Store = Depends(get_store),
):
    session = _load(session_id, user, store)
    if session.status != "completed":
        # One Pro evaluation per unevaluated answer, plus the coach.
        usage.charge(sum(q.answered and q.evaluation is None for q in session.questions) + 1)
    return engine.finish(session).report
