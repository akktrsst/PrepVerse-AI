"""Grounded study discussion (text or voice). One streamed Flash call per message.

Retrieval: the pinned resource (if any) + vector search over the topic's
resources. History: the last HISTORY_MESSAGES verbatim, older turns folded into
a rolling Flash-Lite summary so prompts stay small.
"""

import re
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

from ..errors import NotFoundError, StateError
from ..learn.catalog import TopicCatalog
from ..learn.models import Resource
from ..llm import LLM, LLMError
from ..notes.models import Note
from ..prompts import render, untrusted
from ..store import Store
from .models import Citation, DiscussSession, DiscussStart, SessionNotes, Turn

HISTORY_MESSAGES = 8      # kept verbatim in the prompt
SUMMARIZE_AFTER = 12      # unsummarized messages before older ones get folded in
MAX_SOURCES = 5

_CITE_RE = re.compile(r"\[(\d{1,2})\]")


class DiscussEngine:
    def __init__(self, llm: LLM, store: Store, catalog: TopicCatalog):
        self.llm, self.store, self.catalog = llm, store, catalog

    # ---- Sessions ----
    def start(self, user_id: str, req: DiscussStart) -> DiscussSession:
        topic_id = req.topic_id
        if topic_id and not self.catalog.get(topic_id):
            raise NotFoundError("topic not found")
        if req.resource_id:
            resource = self.store.get_resource(req.resource_id)
            if not resource:
                raise NotFoundError("resource not found")
            topic_id = topic_id or (resource.topic_ids[0] if resource.topic_ids else None)
        session = DiscussSession(
            id=uuid.uuid4().hex, user_id=user_id, topic_id=topic_id,
            resource_id=req.resource_id, persona=req.persona,
        )
        self.store.save_discuss(session)
        return session

    def topic_title(self, session: DiscussSession) -> str:
        topic = self.catalog.get(session.topic_id)
        return topic.title if topic else "AI, ML and Data Science interview prep"

    # ---- Retrieval ----
    def retrieve(self, session: DiscussSession, query: str) -> list[Resource]:
        sources: list[Resource] = []
        if session.resource_id and (pinned := self.store.get_resource(session.resource_id)):
            sources.append(pinned.model_copy(update={"embedding": []}))
        try:
            vec = self.llm.embed([query], task_type="RETRIEVAL_QUERY")[0]
            hits = self.store.search_resources(vec, MAX_SOURCES, topic_id=session.topic_id)
        except LLMError:
            hits = []
        if not hits and session.topic_id:  # no embeddings yet: fall back to best-ranked
            hits = sorted(self.store.list_resources(session.topic_id), key=lambda r: r.score, reverse=True)
        seen = {r.id for r in sources}
        sources += [r for r in hits if r.id not in seen]
        return sources[:MAX_SOURCES]

    # ---- Prompt building ----
    @staticmethod
    def _format_sources(sources: list[Resource]) -> str:
        if not sources:
            return "(no sources available for this topic yet)"
        blocks = []
        for n, r in enumerate(sources, 1):
            points = "; ".join(r.key_points[:4])
            blocks.append(f"[{n}] ({r.type}) {r.title} — {r.source}\nSummary: {r.summary}\nKey points: {points}")
        return "\n\n".join(blocks)

    @staticmethod
    def _format_turns(turns: list[Turn]) -> str:
        if not turns:
            return "(start of conversation)"
        return "\n".join(f"{'Learner' if t.role == 'user' else 'You'}: {t.text}" for t in turns)

    def _compact(self, session: DiscussSession) -> None:
        """Fold older messages into the rolling summary once history gets long."""
        pending = session.turns[session.summarized_upto:]
        if len(pending) <= SUMMARIZE_AFTER:
            return
        fold_to = len(session.turns) - HISTORY_MESSAGES
        session.summary = self.llm.generate(
            render("discuss_summarize", summary=session.summary or "(none)",
                   history=untrusted("conversation", self._format_turns(session.turns[session.summarized_upto:fold_to]))),
            tier="lite", temperature=0.2, feature="discuss.summarize",
        ).strip()
        session.summarized_upto = fold_to

    def _system(self, session: DiscussSession, voice: bool) -> str:
        return render(
            "discuss_base_system",
            topic=self.topic_title(session),
            persona=render(f"discuss_persona_{session.persona}"),
            voice_style=render("discuss_voice_style") if voice else "",
        )

    # ---- Reply (streamed) ----
    def reply(self, session: DiscussSession, text: str, voice: bool) -> Iterator[tuple[str, dict]]:
        """Yield (event, data) pairs: delta*, then citations + done, or error."""
        sources = self.retrieve(session, text)
        try:
            self._compact(session)
        except LLMError:
            pass  # a failed summary shouldn't block the reply
        # Everything not yet summarized (at most SUMMARIZE_AFTER messages after _compact).
        recent = session.turns[session.summarized_upto:]
        prompt = render(
            "discuss_user",
            sources=untrusted("sources", self._format_sources(sources), max_chars=12000),
            summary=session.summary or "(none)",
            history=untrusted("conversation", self._format_turns(recent)),
            message=untrusted("message", text, max_chars=4000),
        )

        chunks: list[str] = []
        try:
            for chunk in self.llm.stream(prompt, tier="std", system=self._system(session, voice),
                                         temperature=0.6, feature="discuss.reply"):
                chunks.append(chunk)
                yield "delta", {"text": chunk}
        except LLMError:
            yield "error", {"detail": "The AI service had a hiccup. Please try again."}
            return

        answer = "".join(chunks).strip()
        cited = sorted({int(n) for n in _CITE_RE.findall(answer) if 1 <= int(n) <= len(sources)})
        citations = [
            Citation(n=n, resource_id=sources[n - 1].id, title=sources[n - 1].title,
                     url=sources[n - 1].url, type=sources[n - 1].type)
            for n in cited
        ]
        session.turns += [Turn(role="user", text=text, voice=voice),
                          Turn(role="assistant", text=answer, citations=citations, voice=voice)]
        self.store.save_discuss(session)
        yield "citations", {"citations": [c.model_dump() for c in citations]}
        yield "done", {"turns": len(session.turns)}

    # ---- Session notes ----
    def make_notes(self, session: DiscussSession) -> list[Note]:
        """Generate structured study notes for the whole session, replacing earlier ones."""
        if not any(t.role == "assistant" for t in session.turns):
            raise StateError("discuss something first, then generate notes")
        conversation = "\n\n".join(
            f"{'Learner' if t.role == 'user' else 'Tutor'}: {t.text}" for t in session.turns[-30:]
        )
        notes = self.llm.generate_structured(
            render("discuss_notes_user", topic=self.topic_title(session),
                   conversation=untrusted("conversation", conversation, max_chars=20000)),
            SessionNotes, tier="std", system=render("discuss_notes_system"),
            temperature=0.3, feature="discuss.notes",
        )

        for old in self.store.list_notes(session.user_id):
            if old.session_id == session.id and old.kind == "ai_note":
                self.store.delete_note(old.id)

        title = f"Discussion: {self.topic_title(session)}"
        now = datetime.now(timezone.utc)
        base = dict(user_id=session.user_id, kind="ai_note", topic_id=session.topic_id,
                    resource_id=session.resource_id, session_id=session.id,
                    source_title=title, created_at=now, updated_at=now)
        out = (
            [Note(id=uuid.uuid4().hex, section="takeaway", text=t, color="green", **base) for t in notes.takeaways]
            + [Note(id=uuid.uuid4().hex, section="definition", quote=d.term, text=d.meaning, color="blue", **base)
               for d in notes.definitions]
            + [Note(id=uuid.uuid4().hex, section="review_question", text=q, color="pink", **base)
               for q in notes.review_questions]
        )
        for n in out:
            self.store.save_note(n)
        session.notes_generated = True
        self.store.save_discuss(session)
        return out
