import json

from ..llm import LLM, LLMError
from ..prompts import render, untrusted
from .models import InterviewConfig, InterviewPlan, PlannedQuestion
from .seed import SeedBank


def plan_interview(llm: LLM, config: InterviewConfig, seed: SeedBank) -> list[PlannedQuestion]:
    candidates = seed.sample(config.modules, k=12)
    tailored = bool(config.resume or config.job_description)
    prompt = render(
        "planner_user",
        role=config.role,
        level=config.level,
        company_type=config.company_type,
        modules=", ".join(config.modules),
        num_questions=config.num_questions,
        seed_questions=json.dumps([q.model_dump() for q in candidates], indent=1),
        resume=untrusted("resume", config.resume),
        job_description=untrusted("job_description", config.job_description),
    )
    plan = llm.generate_structured(
        prompt,
        InterviewPlan,
        # Resume/JD tailoring needs stronger reasoning; generic plans don't.
        tier="pro" if tailored else "std",
        system=render("planner_system"),
        temperature=0.7,
        feature="interview.plan",
    )
    questions = [q for q in plan.questions if q.module in config.modules and q.question.strip()]
    if not questions:
        raise LLMError("interview.plan: model returned no usable questions")
    return questions[: config.num_questions]
