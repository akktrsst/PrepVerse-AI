"""Reviewed seed question bank (backend/seed/*.json). The planner adapts these
rather than inventing everything, which keeps questions grounded."""

import json
import random
from pathlib import Path

from .models import Module, PlannedQuestion

SEED_DIR = Path(__file__).resolve().parents[2] / "seed" / "questions"


class SeedBank:
    def __init__(self, questions: list[PlannedQuestion]):
        self.questions = questions

    @classmethod
    def load(cls, directory: Path = SEED_DIR) -> "SeedBank":
        questions = []
        for path in sorted(directory.glob("*.json")):
            questions += [PlannedQuestion.model_validate(q) for q in json.loads(path.read_text())]
        return cls(questions)

    def sample(self, modules: list[Module], k: int, rng: random.Random | None = None) -> list[PlannedQuestion]:
        pool = [q for q in self.questions if q.module in modules]
        return (rng or random).sample(pool, min(k, len(pool)))
