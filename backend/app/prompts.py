"""Prompts live in app/prompts/*.md so they can be versioned and diffed.

They use $placeholders (string.Template) so JSON examples don't need escaping.
"""

import re
from functools import cache
from pathlib import Path
from string import Template

PROMPT_DIR = Path(__file__).parent / "prompts"


@cache
def _load(name: str) -> Template:
    return Template((PROMPT_DIR / f"{name}.md").read_text())


def render(name: str, **values: object) -> str:
    return _load(name).substitute(**{k: str(v) for k, v in values.items()})


_TAG_RE = re.compile(r"</?\s*untrusted[^>]*>", re.IGNORECASE)


def untrusted(label: str, text: str | None, max_chars: int = 8000) -> str:
    """Wrap user-supplied text (resume, JD, answers) so the model treats it as data.

    Strips any attempt to close the wrapper tag early.
    """
    if not text or not text.strip():
        return f"<untrusted_{label}>(none provided)</untrusted_{label}>"
    clean = _TAG_RE.sub("", text)[:max_chars]
    return f"<untrusted_{label}>\n{clean}\n</untrusted_{label}>"
