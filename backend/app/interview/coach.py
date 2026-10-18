import json
from statistics import mean

from ..llm import LLM
from ..prompts import render
from .models import CoachNotes, QuestionResult, Report, RubricScores, Session
from .rubrics import DIMENSIONS, WEAK_THRESHOLD, weighted_score


def build_report(llm: LLM, session: Session) -> Report:
    """Aggregate scores deterministically, then let the coach agent write the narrative."""
    evaluated = [q for q in session.questions if q.evaluation]
    results = [
        QuestionResult(
            topic=q.planned.topic,
            module=q.planned.module,
            question=q.planned.question,
            scores=RubricScores(**{d: getattr(q.evaluation, d) for d in DIMENSIONS}),
            feedback=q.evaluation.feedback,
            missed_points=q.evaluation.missed_points,
            model_answer=q.evaluation.model_answer,
        )
        for q in evaluated
    ]
    averages = {d: round(mean(getattr(r.scores, d) for r in results), 2) for d in DIMENSIONS}
    # Deterministic so the Watch-mode recommender can rely on it.
    weak_topics = list(dict.fromkeys(
        r.topic for r in results if min(r.scores.accuracy, r.scores.depth) <= WEAK_THRESHOLD
    ))

    coach = llm.generate_structured(
        render(
            "coach_user",
            role=session.config.role,
            level=session.config.level,
            results=json.dumps(
                [{"topic": r.topic, "scores": r.scores.model_dump(), "missed_points": r.missed_points}
                 for r in results],
                indent=1,
            ),
            weak_topics=", ".join(weak_topics) or "none",
        ),
        CoachNotes,
        tier="std",
        system=render("coach_system"),
        temperature=0.5,
        feature="interview.coach",
    )
    return Report(
        overall_score=weighted_score(averages),
        rubric_averages=RubricScores(**averages),
        weak_topics=weak_topics,
        questions=results,
        skipped_questions=len(session.questions) - len(evaluated),
        coach=coach,
    )
