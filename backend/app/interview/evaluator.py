from ..llm import LLM
from ..prompts import render
from .interviewer import format_thread
from .models import AnswerEvaluation, Level, QuestionState
from .rubrics import clamp, rubric_text


def evaluate(llm: LLM, state: QuestionState, level: Level) -> AnswerEvaluation:
    """Score the whole question thread (main answer + follow-ups) against the rubric."""
    planned = state.planned
    prompt = render(
        "evaluator_user",
        level=level,
        kind=planned.kind,
        difficulty=planned.difficulty,
        question=planned.question,
        key_points="\n".join(f"- {p}" for p in planned.key_points),
        thread=format_thread(state.exchanges),
    )
    ev = llm.generate_structured(
        prompt,
        AnswerEvaluation,
        tier="pro",
        system=render("evaluator_system", rubric=rubric_text()),
        temperature=0.2,
        feature="interview.evaluate",
    )
    return ev.model_copy(update={
        "accuracy": clamp(ev.accuracy),
        "depth": clamp(ev.depth),
        "structure": clamp(ev.structure),
        "communication": clamp(ev.communication),
    })
