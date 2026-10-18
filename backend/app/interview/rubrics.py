"""Scoring rubric. Kept short and fixed so the evaluator system prompt is a
stable prefix (cheaper with context caching, more consistent scores)."""

RUBRIC = {
    "accuracy": {
        "weight": 0.35,
        "anchors": "1 = wrong or major misconceptions; 3 = mostly correct, minor errors; 5 = fully correct and precise",
    },
    "depth": {
        "weight": 0.30,
        "anchors": "1 = surface-level buzzwords; 3 = explains how, not why; 5 = trade-offs, edge cases, real-world nuance",
    },
    "structure": {
        "weight": 0.15,
        "anchors": "1 = rambling; 3 = some order; 5 = clear framework (definition -> mechanism -> trade-offs -> example)",
    },
    "communication": {
        "weight": 0.20,
        "anchors": "1 = hard to follow; 3 = understandable; 5 = concise, confident, uses examples well",
    },
}

DIMENSIONS = tuple(RUBRIC)

# A topic is "weak" when accuracy or depth falls to this score or below.
WEAK_THRESHOLD = 2


def rubric_text() -> str:
    return "\n".join(f"- {name} (1-5): {r['anchors']}" for name, r in RUBRIC.items())


def clamp(score: int) -> int:
    return max(1, min(5, int(score)))


def weighted_score(scores: dict[str, float]) -> int:
    """Map weighted 1-5 rubric scores to 0-100."""
    avg = sum(RUBRIC[d]["weight"] * scores[d] for d in DIMENSIONS)
    return round((avg - 1) / 4 * 100)
