from collections import defaultdict

from ..learn.catalog import TopicCatalog
from .models import Note

SECTION_TITLES = {"takeaway": "Key takeaways", "definition": "Definitions", "review_question": "Review questions"}


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.strip().splitlines())


def notes_to_markdown(notes: list[Note], catalog: TopicCatalog, base_url: str = "") -> str:
    """Notebook export grouped by topic; highlights first, then AI session notes.

    Site-relative source links are made absolute with base_url so they work outside the app.
    """
    by_topic: dict[str | None, list[Note]] = defaultdict(list)
    for n in sorted(notes, key=lambda n: n.created_at):
        by_topic[n.topic_id].append(n)

    def topic_name(tid: str | None) -> str:
        t = catalog.get(tid)
        return t.title if t else "General"

    out = ["# PrepVerse notes", ""]
    for tid in sorted(by_topic, key=topic_name):
        out += [f"## {topic_name(tid)}", ""]
        own = [n for n in by_topic[tid] if n.kind != "ai_note"]
        for n in own:
            if n.quote:
                out.append(_quote(n.quote))
                out.append("")
            if n.text:
                out.append(n.text.strip())
                out.append("")
            if n.source_title:
                url = n.source_url
                if url and url.startswith("/"):
                    url = base_url.rstrip("/") + url
                src = f"[{n.source_title}]({url})" if url else n.source_title
                out.append(f"*Source: {src}*")
                out.append("")

        sessions: dict[str, list[Note]] = defaultdict(list)
        for n in by_topic[tid]:
            if n.kind == "ai_note":
                sessions[n.session_id or ""].append(n)
        for items in sessions.values():
            out += [f"### {items[0].source_title or 'Discussion notes'} ({items[0].created_at:%Y-%m-%d})", ""]
            for section, title in SECTION_TITLES.items():
                rows = [n for n in items if n.section == section]
                if not rows:
                    continue
                out += [f"**{title}**", ""]
                for n in rows:
                    out.append(f"- **{n.quote}**: {n.text}" if section == "definition" else f"- {n.text}")
                out.append("")
    return "\n".join(out).rstrip() + "\n"
