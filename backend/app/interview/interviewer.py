from ..llm import LLM
from ..prompts import render, untrusted
from .models import Exchange, FollowUpDecision, Level, PlannedQuestion


def format_thread(exchanges: list[Exchange]) -> str:
    """Render the answered part of a question thread for a prompt."""
    lines = []
    for e in exchanges:
        if e.answer is None:
            break
        lines.append(f"{'Follow-up' if e.is_followup else 'Interviewer'}: {e.question}")
        lines.append(f"Candidate: {untrusted('answer', e.answer, max_chars=6000)}")
    return "\n".join(lines)


def next_followup(llm: LLM, planned: PlannedQuestion, exchanges: list[Exchange], level: Level) -> str | None:
    """Ask the interviewer agent whether to dig deeper. Returns the follow-up or None to move on."""
    prompt = render(
        "interviewer_user",
        level=level,
        question=planned.question,
        key_points="\n".join(f"- {p}" for p in planned.key_points),
        thread=format_thread(exchanges),
        followups_asked=sum(e.is_followup for e in exchanges),
    )
    decision = llm.generate_structured(
        prompt,
        FollowUpDecision,
        tier="std",
        system=render("interviewer_system"),
        temperature=0.5,
        feature="interview.followup",
    )
    question = decision.followup_question.strip()
    return question if decision.ask_followup and question else None
