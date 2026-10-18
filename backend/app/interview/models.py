from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["data_analyst", "data_scientist", "ml_engineer", "ai_engineer", "agent_developer"]
Level = Literal["beginner", "intermediate", "advanced"]
CompanyType = Literal["startup", "faang", "service", "product"]
Module = Literal["data_science", "genai_llms", "ai_agents"]  # MVP modules
QuestionKind = Literal["concept", "system_design", "case_study", "behavioral"]
Difficulty = Literal["easy", "medium", "hard"]
SessionStatus = Literal["in_progress", "awaiting_report", "completed"]


# ---- Request ----

class InterviewConfig(BaseModel):
    role: Role
    level: Level = "intermediate"
    company_type: CompanyType = "product"
    modules: list[Module] = Field(default=["data_science", "genai_llms", "ai_agents"], min_length=1)
    num_questions: int = Field(default=6, ge=3, le=8)
    resume: str | None = Field(default=None, max_length=8000)
    job_description: str | None = Field(default=None, max_length=8000)


# ---- Structured LLM outputs (kept simple: Gemini response_schema subset) ----

class PlannedQuestion(BaseModel):
    module: Module
    topic: str = Field(description="Short topic label, e.g. 'RAG chunking'")
    kind: QuestionKind
    difficulty: Difficulty
    question: str
    key_points: list[str] = Field(description="3-6 points a strong answer covers; hidden from the candidate")


class InterviewPlan(BaseModel):
    questions: list[PlannedQuestion]


class FollowUpDecision(BaseModel):
    ask_followup: bool
    followup_question: str = Field(description="Empty string when ask_followup is false")


class AnswerEvaluation(BaseModel):
    accuracy: int = Field(description="1-5")
    depth: int = Field(description="1-5")
    structure: int = Field(description="1-5")
    communication: int = Field(description="1-5")
    covered_points: list[str]
    missed_points: list[str]
    feedback: str = Field(description="2-4 sentences addressed to the candidate")
    model_answer: str = Field(description="A concise strong answer, under 200 words")


class CoachNotes(BaseModel):
    summary: str
    strengths: list[str]
    improvement_areas: list[str]
    study_plan: list[str] = Field(description="3-5 concrete next steps")


# ---- Session state ----

class Exchange(BaseModel):
    question: str
    answer: str | None = None
    is_followup: bool = False


class QuestionState(BaseModel):
    planned: PlannedQuestion
    exchanges: list[Exchange]
    evaluation: AnswerEvaluation | None = None

    @property
    def answered(self) -> bool:
        return self.exchanges[0].answer is not None

    @property
    def followups_asked(self) -> int:
        return sum(e.is_followup for e in self.exchanges)


class RubricScores(BaseModel):
    accuracy: float
    depth: float
    structure: float
    communication: float


class QuestionResult(BaseModel):
    topic: str
    module: Module
    question: str
    scores: RubricScores
    feedback: str
    missed_points: list[str]
    model_answer: str


class Report(BaseModel):
    overall_score: int = Field(description="0-100 readiness score for this session")
    rubric_averages: RubricScores
    weak_topics: list[str]
    questions: list[QuestionResult]
    skipped_questions: int
    coach: CoachNotes


class Session(BaseModel):
    id: str
    user_id: str
    config: InterviewConfig
    status: SessionStatus = "in_progress"
    questions: list[QuestionState]
    current: int = 0
    report: Report | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
