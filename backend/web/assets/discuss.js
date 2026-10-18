// Discuss page: grounded tutor chat over text or voice, with highlights and session notes.
"use strict";

(() => {
  const { el, api, stream, label, toast } = PV;
  const $ = (id) => document.getElementById(id);

  const PERSONAS = [
    ["tutor", "Tutor", "Explains simply, with analogies"],
    ["socratic", "Socratic", "Guides you with questions"],
    ["quickfire", "Quiz me", "Rapid interview questions"],
  ];
  const TYPE_ICON = { video: "▶", paper: "📄", blog: "✍", repo: "⌥", discussion: "💬" };

  let session = null;
  let busy = false;
  let voice = null;
  let voiceMode = false; // last message came from the mic -> speak the reply

  // ---------- Minimal, safe markdown -> DOM (no innerHTML) ----------
  function inline(text) {
    const out = [];
    const re = /(\*\*[^*]+\*\*|`[^`]+`|\[\d{1,2}\])/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) out.push(text.slice(last, m.index));
      const tok = m[0];
      if (tok.startsWith("**")) out.push(el("strong", {}, tok.slice(2, -2)));
      else if (tok.startsWith("`")) out.push(el("code", {}, tok.slice(1, -1)));
      else out.push(el("span", { class: "cite-ref" }, tok));
      last = m.index + tok.length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }

  function renderMarkdown(text) {
    const nodes = [];
    const blocks = text.split(/```/);
    blocks.forEach((block, i) => {
      if (i % 2 === 1) {
        nodes.push(el("pre", { class: "model-answer", style: { whiteSpace: "pre-wrap", fontSize: ".85rem" } },
          block.replace(/^\w*\n/, "")));
        return;
      }
      for (const para of block.split(/\n{2,}/)) {
        const lines = para.split("\n").filter((l) => l.trim());
        if (!lines.length) continue;
        if (lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l))) {
          const ordered = /^\s*\d/.test(lines[0]);
          nodes.push(el(ordered ? "ol" : "ul", { style: { margin: "4px 0 8px", paddingLeft: "20px" } },
            lines.map((l) => el("li", {}, inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ""))))));
        } else {
          const heading = lines[0].match(/^#{1,4}\s+(.*)/);
          if (heading) nodes.push(el("strong", { style: { display: "block", marginTop: "6px" } }, inline(heading[1])));
          const rest = heading ? lines.slice(1) : lines;
          if (rest.length) nodes.push(el("p", { style: { margin: "0 0 8px" } }, inline(rest.join(" "))));
        }
      }
    });
    return nodes;
  }

  // ---------- Chat rendering ----------
  function citationChips(citations) {
    if (!citations?.length) return null;
    return el("div", { class: "cites" }, citations.map((c) => el("a", {
      class: "cite", href: c.url, target: "_blank", rel: "noopener", title: c.title,
      // Videos open in the in-page player instead of leaving the conversation.
      onclick: c.type === "video" && PV.learn ? (e) => {
        e.preventDefault();
        PV.learn.watch({ ...c, id: c.resource_id, topic_ids: [session.topic_id].filter(Boolean) });
      } : null,
    }, el("b", {}, `[${c.n}]`), `${TYPE_ICON[c.type] || ""} `, el("span", {}, c.title))));
  }

  function assistantBubble(text, citations) {
    const body = el("div", { "data-highlightable": "", "data-session": session.id, "data-topic": session.topic_id || "" },
      text ? renderMarkdown(text) : el("span", { class: "typing" }, el("i"), el("i"), el("i")));
    return el("div", { class: "bubble ai", style: { whiteSpace: "normal" } },
      el("span", { class: "who" }, "AI tutor"), body, citationChips(citations));
  }

  function userBubble(text, viaVoice) {
    return el("div", { class: "bubble me" }, el("span", { class: "who" }, viaVoice ? "You · 🎙" : "You"), text);
  }

  function renderChat() {
    const chat = $("chat");
    chat.replaceChildren(...session.turns.map((t) =>
      t.role === "user" ? userBubble(t.text, t.voice) : assistantBubble(t.text, t.citations)));
    if (!session.turns.length) chat.append(starter());
  }

  function starter() {
    const topic = session.topic_title;
    const res = session.resource;
    const prompts = res
      ? [`Summarise "${res.title}" in simple terms`, "What are the key ideas I should remember?", "How could an interviewer ask about this?"]
      : [`Explain ${topic} like I'm new to it`, `What do interviewers usually ask about ${topic}?`, "Quiz me with one question"];
    return el("div", { class: "card", style: { textAlign: "center" } },
      el("div", { class: "icon-tile", style: { margin: "0 auto 10px" } }, "🎙"),
      el("h3", {}, res ? "Discuss this resource" : `Let's talk about ${topic}`),
      el("p", { class: "muted small" }, "Tap the mic and speak, or type below. Answers are grounded in the Learn Hub resources and cite them."),
      el("div", {}, prompts.map((p) => el("button", { class: "chip", style: { cursor: "pointer" }, onclick: () => send(p, false) }, p))));
  }

  function scrollDown() { window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }); }

  // ---------- Sending ----------
  async function send(text, viaVoice) {
    text = text.trim();
    if (!text || busy) return;
    busy = true;
    voiceMode = viaVoice;
    setComposerBusy(true);
    $("chat-error").classList.add("hidden");
    if (!session.turns.length) $("chat").replaceChildren();

    const chat = $("chat");
    chat.append(userBubble(text, viaVoice));
    let bubble = assistantBubble("", null);
    chat.append(bubble);
    scrollDown();

    let answer = "";
    let citations = [];
    let failed = null;
    if (viaVoice) voice.beginReply();
    try {
      await stream(`/discuss/sessions/${session.id}/messages`, { text, voice: viaVoice }, (event, data) => {
        if (event === "delta") {
          answer += data.text;
          const fresh = assistantBubble(answer, null);
          bubble.replaceWith(fresh);
          bubble = fresh;
          if (viaVoice) voice.feed(data.text);
        } else if (event === "citations") {
          citations = data.citations;
        } else if (event === "error") {
          failed = data.detail;
        }
      });
    } catch (e) {
      failed = e.message;
    }

    if (failed || !answer) {
      bubble.remove();
      chat.lastElementChild?.remove(); // the user's bubble: the server didn't store this turn
      $("chat-error").textContent = failed || "No reply received. Please try again.";
      $("chat-error").classList.remove("hidden");
      if (!viaVoice) $("msg").value = text;
      voice?.reset();
      if (!session.turns.length) renderChat();
    } else {
      const done = assistantBubble(answer, citations);
      bubble.replaceWith(done);
      session.turns.push({ role: "user", text, voice: viaVoice }, { role: "assistant", text: answer, citations, voice: viaVoice });
      if (viaVoice) voice.endReply();
      $("end-btn").disabled = false;
    }
    busy = false;
    setComposerBusy(false);
    scrollDown();
  }

  function setComposerBusy(on) {
    $("send-btn").disabled = on;
    $("msg").disabled = on;
  }

  // ---------- Voice panel ----------
  const STATUS = {
    idle: ["Tap to speak", false],
    listening: ["Listening… pause when you're done", false],
    thinking: ["Thinking…", true],
    speaking: ["Speaking… tap to interrupt", false],
  };

  function initVoice() {
    voice = new PV.VoiceController({
      onState: (s) => {
        const [text, disabled] = STATUS[s];
        const mic = $("mic-btn");
        mic.classList.toggle("listening", s === "listening");
        mic.disabled = disabled;
        mic.textContent = s === "listening" ? "■" : s === "speaking" ? "⏸" : "🎙";
        mic.setAttribute("aria-label", s === "listening" ? "Stop listening" : s === "speaking" ? "Stop speaking" : "Start speaking");
        $("voice-status").replaceChildren(s === "speaking"
          ? el("span", { style: { display: "inline-flex", gap: "8px", alignItems: "center" } },
              el("span", { class: "wave" }, el("i"), el("i"), el("i"), el("i"), el("i")), text)
          : text);
      },
      onInterim: (t) => { $("interim").textContent = t; },
      onFinal: (t) => send(t, true),
      onError: (msg) => toast(msg, 4500),
    });

    if (!voice.supported.stt) {
      $("mic-btn").disabled = true;
      $("voice-status").textContent = "Voice input works best in Chrome or Edge";
    } else {
      voice.setState("idle");
    }

    $("mic-btn").addEventListener("click", () => {
      if (voice.state === "listening") voice.stopListening();
      else if (voice.state === "speaking") voice.stopSpeaking();
      else {
        if (!PV.store.get("pv.voice.privacyAck", false)) {
          PV.store.set("pv.voice.privacyAck", true);
          toast("Your browser converts speech to text. In Chrome, audio is processed by Google.", 5000);
        }
        voice.listen();
      }
    });
    document.addEventListener("keydown", (e) => {
      // Space = push-to-talk / barge-in, unless the user is typing.
      if (e.code !== "Space" || e.repeat || ["TEXTAREA", "INPUT", "SELECT", "BUTTON"].includes(document.activeElement?.tagName)) return;
      e.preventDefault();
      $("mic-btn").click();
    });

    const hf = $("hands-free");
    hf.checked = voice.handsFree;
    hf.addEventListener("change", () => { voice.handsFree = hf.checked; PV.store.set("pv.voice.handsFree", hf.checked); });

    const mute = $("mute");
    mute.addEventListener("change", () => { voice.muted = mute.checked; if (mute.checked) voice.stopSpeaking(); });

    const lang = $("voice-lang");
    lang.value = voice.lang;
    lang.addEventListener("change", () => { voice.lang = lang.value; PV.store.set("pv.voice.lang", lang.value); fillVoices(); });

    const rate = $("voice-rate");
    rate.value = String(voice.rate);
    rate.addEventListener("change", () => { voice.rate = Number(rate.value); PV.store.set("pv.voice.rate", voice.rate); });

    const sel = $("voice-name");
    function fillVoices() {
      const voices = voice.voices();
      sel.replaceChildren(el("option", { value: "" }, "Default voice"),
        ...voices.map((v) => el("option", { value: v.name, selected: v.name === voice.voiceName }, `${v.name}${v.localService ? "" : " (online)"}`)));
    }
    sel.addEventListener("change", () => { voice.voiceName = sel.value || null; PV.store.set("pv.voice.name", voice.voiceName); });
    if (voice.supported.tts) {
      fillVoices();
      speechSynthesis.addEventListener?.("voiceschanged", fillVoices);
    }
    window.addEventListener("pagehide", () => voice.reset());
  }

  // ---------- Session lifecycle ----------
  function renderContext() {
    const r = session.resource;
    $("context").replaceChildren(
      el("span", { class: "context-chip", title: r ? r.title : session.topic_title },
        r ? `${TYPE_ICON[r.type] || ""} ` : "📚 ", el("span", {}, r ? r.title : session.topic_title)),
      session.topic_id ? el("a", { class: "small", href: `/learn/topic/?id=${encodeURIComponent(session.topic_id)}`, style: { marginLeft: "10px" } }, "Browse resources →") : null);
    $("persona").replaceChildren(...PERSONAS.map(([id, name, sub]) => el("button", {
      class: id === session.persona ? "on" : null, title: sub,
      onclick: () => switchPersona(id),
    }, name)));
    $("end-btn").disabled = !session.turns.some((t) => t.role === "assistant");
  }

  async function openSession(s) {
    session = s;
    history.replaceState(null, "", `?session=${s.id}`);
    PV.store.set(`pv.discuss.last.${s.topic_id || "general"}`, s.id);
    renderContext();
    renderChat();
  }

  async function startSession({ topic_id, resource_id, persona }) {
    return api("/discuss/sessions", { method: "POST", body: { topic_id, resource_id, persona: persona || "tutor" } });
  }

  async function switchPersona(persona) {
    if (persona === session.persona || busy) return;
    voice?.reset();
    const s = await startSession({ topic_id: session.topic_id, resource_id: session.resource?.id, persona });
    openSession(s);
    toast(`New ${PERSONAS.find((p) => p[0] === persona)[1]} session started`);
  }

  async function endAndNotes() {
    const btn = $("end-btn");
    btn.disabled = true;
    btn.textContent = "Writing your notes…";
    voice?.reset();
    try {
      const notes = await api(`/discuss/sessions/${session.id}/end`, { method: "POST" });
      const section = (key, title) => {
        const rows = notes.filter((n) => n.section === key);
        return rows.length ? el("div", {}, el("h4", {}, title), el("ul", {}, rows.map((n) =>
          el("li", {}, key === "definition" ? [el("strong", {}, n.quote), `: ${n.text}`] : n.text)))) : null;
      };
      PV.modal("Notes saved to your notebook",
        el("div", { class: "session-notes", style: { maxHeight: "55vh", overflowY: "auto" } },
          section("takeaway", "Key takeaways"), section("definition", "Definitions"), section("review_question", "Review questions")),
        [{ label: "Keep discussing" },
         { label: "Open notebook", primary: true, href: `/notes/${session.topic_id ? `?topic=${encodeURIComponent(session.topic_id)}` : ""}` }]);
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "End & make notes";
    }
  }

  async function chooseTopic() {
    const topics = await api("/learn/topics");
    const MODS = ["data_science", "genai_llms", "ai_agents"];
    $("main-area").replaceChildren(el("div", { class: "page-head" },
      el("span", { class: "eyebrow" }, "Discuss"),
      el("h1", { style: { fontSize: "clamp(1.8rem,4vw,2.4rem)" } }, "What do you want to talk about?"),
      el("p", { class: "muted" }, "Pick a topic. You can talk by voice or type, and the AI tutor cites real resources.")),
      ...MODS.map((m) => el("div", { style: { marginBottom: "24px" } },
        el("h3", {}, label(m)),
        el("div", { class: "grid grid-3" }, topics.filter((t) => t.module === m).map((t) => el("a", {
          class: "card topic-card", href: `/discuss/?topic=${encodeURIComponent(t.id)}`,
        }, el("strong", {}, t.title), el("p", { class: "muted small", style: { margin: "6px 0 0" } }, t.description)))))));
  }

  async function boot() {
    if (!(await PV.requireAuth($("main-area"), "Discuss"))) return;
    const params = new URLSearchParams(location.search);
    try {
      let s = null;
      if (params.get("session")) {
        try { s = await api(`/discuss/sessions/${encodeURIComponent(params.get("session"))}`); }
        catch (e) { if (e.status !== 404) throw e; toast("That session has expired, starting a new one."); }
      }
      if (!s && (params.get("topic") || params.get("resource"))) {
        s = await startSession({ topic_id: params.get("topic"), resource_id: params.get("resource") });
      }
      if (!s) { await chooseTopic(); return; }
      $("discuss-ui").classList.remove("hidden");
      initVoice();
      $("end-btn").addEventListener("click", endAndNotes);
      $("composer").addEventListener("submit", (e) => { e.preventDefault(); const t = $("msg").value; $("msg").value = ""; send(t, false); });
      $("msg").addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("composer").requestSubmit(); }
      });
      openSession(s);
    } catch (e) {
      $("main-area").replaceChildren(el("div", { class: "alert" }, e.message));
    }
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
