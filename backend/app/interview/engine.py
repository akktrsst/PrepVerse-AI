"""Mock interview state machine: Planner -> Interviewer (follow-ups) -> Evaluator -> Coach.

Cost shape per interview: 1 plan call, one Flash call per answer (follow-up
decision), then one Pro evaluation per answered question, run in parallel at
the end so the interview itself feels snappy.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor

from ..errors import StateError
from ..llm import LLM
from ..store import Store
from .coach import build_report
from .evaluator import evaluate
from .interviewer import next_followup
from .models import Exchange, InterviewConfig, QuestionState, Session
from .planner import plan_interview
from .seed import SeedBank

MAX_FOLLOWUPS = 2


class InterviewStateError(StateError):
    """The requested action isn't valid in the session's current state."""


class InterviewEngine:
    def __init__(self, llm: LLM, store: Store, seed: SeedBank):
        self.llm = llm
        self.store = store
        self.seed = seed

    def start(self, user_id: str, config: InterviewConfig) -> Session:
        planned = plan_interview(self.llm, config, self.seed)
        session = Session(
            id=uuid.uuid4().hex,
            user_id=user_id,
            config=config,
            questions=[QuestionState(planned=q, exchanges=[Exchange(question=q.question)]) for q in planned],
        )
        self.store.save_session(session)
        return session

    def answer(self, session: Session, text: str) -> Session:
        if session.status != "in_progress":
            raise InterviewStateError(f"session is {session.status}")
        state = session.questions[session.current]
        state.exchanges[-1].answer = text

        if state.followups_asked < MAX_FOLLOWUPS:
            followup = next_followup(self.llm, state.planned, state.exchanges, session.config.level)
            if followup:
                state.exchanges.append(Exchange(question=followup, is_followup=True))
                self.store.save_session(session)
                return session

        session.current += 1
        if session.current >= len(session.questions):
            session.status = "awaiting_report"
        self.store.save_session(session)
        return session

    def finish(self, session: Session) -> Session:
        """Evaluate answered questions and build the report. Can be called early."""
        if session.status == "completed":
            return session
        pending = [q for q in session.questions if q.answered and q.evaluation is None]
        if not any(q.answered for q in session.questions):
            raise InterviewStateError("answer at least one question before finishing")

        level = session.config.level
        with ThreadPoolExecutor(max_workers=4) as pool:
            for state, ev in zip(pending, pool.map(lambda q: evaluate(self.llm, q, level), pending)):
                state.evaluation = ev
        # Persist evaluations first so a coach failure doesn't waste the Pro calls.
        self.store.save_session(session)

        session.report = build_report(self.llm, session)
        session.status = "completed"
        self.store.save_session(session)
        return session
