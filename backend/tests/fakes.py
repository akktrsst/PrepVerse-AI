"""Offline stand-ins for app.llm.LLM, shared by all tests."""

import re
import zlib

from fastapi.testclient import TestClient

from app.config import Settings
from app.discuss.models import Definition, SessionNotes
from app.interview.models import AnswerEvaluation, CoachNotes, FollowUpDecision, InterviewPlan
from app.interview.seed import SeedBank
from app.learn.models import Chapter, EnrichmentBatch, ResourceEnrichment, TopicRelevance, VideoDigest
from app.main import create_app
from app.store import MemoryStore

DIM = 32


def fake_embedding(text: str) -> list[float]:
    """Deterministic bag-of-words vector so cosine similarity tracks word overlap."""
    vec = [0.0] * DIM
    for word in re.findall(r"[a-z]+", text.lower()):
        vec[zlib.crc32(word.encode()) % DIM] += 1.0
    return vec


class FakeLLM:
    """Scripted stand-in for app.llm.LLM. Records every call."""

    def __init__(self, followups: list[str | None] | None = None, eval_scores: int = 4,
                 reply: str = "RAG retrieves documents first [1]. Then the model answers.",
                 relevance: int = 4):
        self.followups = list(followups or [])
        self.eval_scores = eval_scores
        self.reply = reply
        self.relevance = relevance
        self.calls: list[tuple[str, str]] = []  # (feature, tier)
        self.prompts: list[tuple[str, object, str | None]] = []  # (feature, prompt, system)
        self.fail_stream = False

    def _record(self, feature, tier, prompt=None, system=None):
        self.calls.append((feature, tier))
        self.prompts.append((feature, prompt, system))

    def generate(self, prompt, *, tier="std", system=None, feature="unknown", **_):
        self._record(feature, tier, prompt, system)
        return "Earlier the learner discussed chunking and embeddings."

    def stream(self, prompt, *, tier="std", system=None, feature="unknown", **_):
        from app.llm import LLMError

        self._record(feature, tier, prompt, system)
        if self.fail_stream:
            raise LLMError("boom")
        for word in self.reply.split(" "):
            yield word + " "

    def embed(self, texts, task_type="RETRIEVAL_DOCUMENT"):
        self.calls.append(("embed", task_type))
        return [fake_embedding(t) for t in texts]

    def generate_structured(self, prompt, schema, *, tier="std", system=None, feature="unknown", **_):
        self._record(feature, tier, prompt, system)
        if schema is InterviewPlan:
            return InterviewPlan(questions=SeedBank.load().questions[:4])
        if schema is FollowUpDecision:
            q = self.followups.pop(0) if self.followups else None
            return FollowUpDecision(ask_followup=q is not None, followup_question=q or "")
        if schema is AnswerEvaluation:
            s = self.eval_scores
            return AnswerEvaluation(
                accuracy=s, depth=s, structure=s, communication=9,  # 9 -> clamped to 5
                covered_points=["a"], missed_points=["b"], feedback="ok", model_answer="m",
            )
        if schema is CoachNotes:
            return CoachNotes(summary="s", strengths=[], improvement_areas=["x"], study_plan=["y"])
        if schema is EnrichmentBatch:
            # Rate every item's candidate topics, read back from the prompt.
            items = re.findall(r"\[(\d+)\] \((\w+)\) (.*?) \| source: .*? \| candidate topics: ([^\n]+)", str(prompt))
            return EnrichmentBatch(items=[
                ResourceEnrichment(
                    index=int(n), relevance=[TopicRelevance(topic_id=t.strip(), relevance=self.relevance)
                                             for t in topics.split(",")],
                    summary=f"Summary of {title}", key_points=["point one", "point two"],
                    difficulty="medium", why_it_matters="Common interview topic.",
                ) for n, _type, title, topics in items
            ])
        if schema is VideoDigest:
            return VideoDigest(summary="Deep video summary", key_points=["k1", "k2"], chapters=[
                Chapter(time="0:00", title="Intro"), Chapter(time="5:30", title="Core idea"),
                Chapter(time="1:13:50", title="Hallucinated chapter"),
            ])
        if schema is SessionNotes:
            return SessionNotes(takeaways=["RAG grounds answers in retrieved text."],
                                definitions=[Definition(term="Reranker", meaning="Re-scores retrieved chunks.")],
                                review_questions=["How would you evaluate retrieval?"])
        raise AssertionError(schema)


def make_client(llm=None, limit=50, store=None, auth_disabled=True):
    settings = Settings(auth_disabled=auth_disabled, max_daily_llm_calls_per_user=limit, _env_file=None)
    return TestClient(create_app(settings=settings, llm=llm or FakeLLM(), store=store or MemoryStore()))
