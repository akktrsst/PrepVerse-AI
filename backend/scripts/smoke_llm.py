"""Week-1 check: one real call per model tier + one embedding, against your GCP project.

    cd backend && python -m scripts.smoke_llm
"""

from app.config import get_settings
from app.llm import LLM


def main() -> None:
    llm = LLM(get_settings())
    for tier in ("lite", "std", "pro"):
        out = llm.generate("Define overfitting in one sentence.", tier=tier, feature="smoke")
        print(f"[{tier}] {llm.models[tier]}: {out.strip()[:120]}")
    vec = llm.embed(["retrieval augmented generation"])[0]
    print(f"[embed] dim={len(vec)}")


if __name__ == "__main__":
    main()
