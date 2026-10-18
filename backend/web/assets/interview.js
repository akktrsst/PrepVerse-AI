// Mock interview page: setup -> live interview -> report.
"use strict";

(() => {
  const { el, api, store, label, scoreTone } = PV;
  const $ = (id) => document.getElementById(id);

  const ROLES = [
    ["data_analyst", "Data Analyst", "SQL, stats, metrics"],
    ["data_scientist", "Data Scientist", "Stats, ML, experiments"],
    ["ml_engineer", "ML Engineer", "Models, MLOps, systems"],
    ["ai_engineer", "AI Engineer", "LLMs, RAG, evals"],
    ["agent_developer", "Agent Developer", "Tools, memory, MCP"],
  ];
  const LEVELS = [
    ["beginner", "Beginner", "Student / fresher"],
    ["intermediate", "Intermediate", "1–4 years"],
    ["advanced", "Advanced", "Senior / lead"],
  ];
  const MODULES = [
    ["data_science", "Data Science", "Stats, SQL, A/B tests"],
    ["genai_llms", "GenAI & LLMs", "RAG, fine-tuning"],
    ["ai_agents", "AI Agents", "Tools, MCP, memory"],
  ];

  const views = ["setup", "loading", "live", "report"];
  function show(name) {
    views.forEach((v) => $(`view-${v}`).classList.toggle("hidden", v !== name));
    window.scrollTo({ top: 0 });
  }

  // ---------- Setup ----------
  function optionGroup(host, name, items, type, checked) {
    host.replaceChildren(...items.map(([value, title, sub]) =>
      el("label", { class: "option" },
        el("input", { type, name, value, checked: checked.includes(value) }),
        el("span", {}, title, el("small", {}, sub)))));
  }

  function readForm() {
    const f = $("setup-form");
    const val = (name) => f.querySelector(`input[name="${name}"]:checked`)?.value;
    return {
      role: val("role"),
      level: val("level"),
      modules: [...f.querySelectorAll('input[name="modules"]:checked')].map((i) => i.value),
      company_type: $("company_type").value,
      num_questions: Number($("num_questions").value),
      resume: $("resume").value.trim() || null,
      job_description: $("job_description").value.trim() || null,
    };
  }

  function renderSummary() {
    const c = readForm();
    const row = (k, v) => el("div", { class: "kv" }, el("span", { class: "muted" }, k), el("strong", {}, v));
    $("summary").replaceChildren(
      row("Role", label(c.role)),
      row("Level", label(c.level)),
      row("Topics", c.modules.length ? c.modules.map(label).join(", ") : "None selected"),
      row("Questions", String(c.num_questions)),
      row("Tailored", c.resume || c.job_description ? "Yes" : "No"),
    );
  }

  function initSetup() {
    const params = new URLSearchParams(location.search);
    const presetModule = params.get("module");
    const last = store.get("pv.lastConfig", {});
    optionGroup($("role-options"), "role", ROLES, "radio", [last.role || "ai_engineer"]);
    optionGroup($("level-options"), "level", LEVELS, "radio", [last.level || "intermediate"]);
    optionGroup($("module-options"), "modules", MODULES, "checkbox",
      presetModule && MODULES.some(([m]) => m === presetModule) ? [presetModule]
        : last.modules?.length ? last.modules : MODULES.map(([m]) => m));
    if (last.company_type) $("company_type").value = last.company_type;
    if (last.num_questions) $("num_questions").value = String(last.num_questions);

    $("setup-form").addEventListener("change", renderSummary);
    $("setup-form").addEventListener("input", renderSummary);
    renderSummary();

    $("setup-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const config = readForm();
      const err = $("setup-error");
      if (!config.modules.length) {
        err.textContent = "Pick at least one topic.";
        err.classList.remove("hidden");
        return;
      }
      err.classList.add("hidden");
      store.set("pv.lastConfig", { ...config, resume: null, job_description: null });

      setLoading("Planning your interview…",
        config.resume || config.job_description
          ? "Reading your resume and job description to tailor questions."
          : "Picking questions that match your role and level.");
      show("loading");
      try {
        const turn = await api("/interview/start", { method: "POST", body: config });
        state.reset(turn.session_id, config);
        state.addQuestion(turn);
        history.replaceState(null, "", `?session=${turn.session_id}`);
        enterLive(turn);
      } catch (ex) {
        show("setup");
        err.textContent = ex.message;
        err.classList.remove("hidden");
      }
    });
  }

  function setLoading(title, text) {
    $("loading-title").textContent = title;
    $("loading-text").textContent = text;
  }

  // ---------- Session state (transcript kept locally so a reload can resume) ----------
  const state = {
    id: null, config: null, transcript: [], startedAt: Date.now(),
    key() { return `pv.session.${this.id}`; },
    reset(id, config) {
      Object.assign(this, { id, config, transcript: [], startedAt: Date.now() });
      store.set("pv.active", id);
      this.save();
    },
    load(id) {
      const saved = store.get(`pv.session.${id}`, null);
      if (!saved) return false;
      Object.assign(this, { id, ...saved });
      return true;
    },
    save() {
      store.set(this.key(), { config: this.config, transcript: this.transcript, startedAt: this.startedAt });
    },
    addQuestion(turn) {
      this.transcript.push({ kind: turn.is_followup ? "followup" : "question", text: turn.question,
        topic: turn.topic, n: turn.question_number, total: turn.total_questions });
      this.save();
    },
    addAnswer(text) { this.transcript.push({ kind: "answer", text }); this.save(); },
    clear() { store.del(this.key()); store.del("pv.active"); },
  };

  // ---------- Live ----------
  let timerHandle = null;
  let busy = false;

  function renderThread() {
    const nodes = [];
    for (const item of state.transcript) {
      if (item.kind === "question") {
        nodes.push(el("div", { class: "small muted", style: { marginTop: nodes.length ? "10px" : 0, fontWeight: 600 } },
          `Question ${item.n} of ${item.total}`, item.topic ? ` · ${item.topic}` : ""));
        nodes.push(el("div", { class: "bubble ai" }, el("span", { class: "who" }, "Interviewer"), item.text));
      } else if (item.kind === "followup") {
        nodes.push(el("div", { class: "bubble ai" }, el("span", { class: "who" }, "Follow-up"), item.text));
      } else {
        nodes.push(el("div", { class: "bubble me" }, el("span", { class: "who" }, "You"), item.text));
      }
    }
    $("thread").replaceChildren(...nodes);
  }

  function showTyping(on) {
    $("thread").querySelector(".typing-bubble")?.remove();
    if (on) {
      $("thread").append(el("div", { class: "bubble ai typing-bubble" },
        el("span", { class: "typing", "aria-label": "Interviewer is thinking" }, el("i"), el("i"), el("i"))));
    }
  }

  function updateProgress(turn) {
    const total = turn.total_questions;
    const done = Math.min(turn.question_number - 1, total);
    $("progress-label").textContent = turn.status === "in_progress"
      ? `Question ${turn.question_number} of ${total}${turn.is_followup ? " · follow-up" : ""}`
      : `All ${total} questions answered`;
    $("progress-bar").style.width = `${(done / total) * 100}%`;
  }

  function renderMeta() {
    const c = state.config;
    if (!c) { $("live-meta").replaceChildren(); return; }
    const row = (k, v) => el("div", { class: "kv" }, el("span", { class: "muted" }, k), el("strong", {}, v));
    $("live-meta").replaceChildren(row("Role", label(c.role)), row("Level", label(c.level)),
      row("Company", label(c.company_type)));
  }

  function tickTimer() {
    const s = Math.floor((Date.now() - state.startedAt) / 1000);
    $("timer").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }

  function enterLive(turn) {
    show("live");
    renderThread();
    renderMeta();
    updateProgress(turn);
    clearInterval(timerHandle);
    tickTimer();
    timerHandle = setInterval(tickTimer, 1000);
    $("answer").focus();
  }

  function setBusy(on) {
    busy = on;
    ["send-btn", "skip-btn", "end-btn"].forEach((id) => { $(id).disabled = on; });
    $("answer").disabled = on;
  }

  async function sendAnswer(text) {
    if (busy || !text.trim()) return;
    $("live-error").classList.add("hidden");
    state.addAnswer(text.trim());
    $("answer").value = "";
    updateCount();
    renderThread();
    showTyping(true);
    setBusy(true);
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
    try {
      const turn = await api(`/interview/${state.id}/answer`, { method: "POST", body: { answer: text.trim() } });
      showTyping(false);
      updateProgress(turn);
      if (turn.status === "in_progress") {
        state.addQuestion(turn);
        renderThread();
        setBusy(false);
        $("answer").focus();
        window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
      } else {
        setBusy(false);
        await finish();
      }
    } catch (ex) {
      // Roll back the optimistic answer so the user can resend it.
      state.transcript.pop();
      state.save();
      showTyping(false);
      renderThread();
      $("answer").value = text;
      updateCount();
      setBusy(false);
      $("live-error").textContent = ex.message;
      $("live-error").classList.remove("hidden");
    }
  }

  function updateCount() { $("char-count").textContent = `${$("answer").value.length} / 6000`; }

  function initLive() {
    $("answer").addEventListener("input", updateCount);
    $("answer").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendAnswer($("answer").value); }
    });
    $("answer-form").addEventListener("submit", (e) => { e.preventDefault(); sendAnswer($("answer").value); });
    $("skip-btn").addEventListener("click", () => sendAnswer("I don't know."));
    $("end-btn").addEventListener("click", () => {
      const answered = state.transcript.some((t) => t.kind === "answer");
      if (!answered) {
        PV.modal("Nothing to grade yet", "Answer at least one question to get a report.", [{ label: "OK", primary: true }]);
        return;
      }
      PV.modal("End the interview?", "Unanswered questions will be skipped. You'll get a report on everything you've answered so far.",
        [{ label: "Keep going" }, { label: "End & get report", primary: true, onClick: finish }]);
    });
  }

  // ---------- Finish & report ----------
  async function finish() {
    clearInterval(timerHandle);
    setLoading("Scoring your answers…", "Our evaluator is grading each answer against the rubric. This usually takes 15–40 seconds.");
    show("loading");
    try {
      const report = await api(`/interview/${state.id}/finish`, { method: "POST" });
      const entry = {
        id: state.id, date: new Date().toISOString(), role: state.config?.role, level: state.config?.level,
        modules: state.config?.modules, score: report.overall_score, weak_topics: report.weak_topics, report,
      };
      PV.saveToHistory(entry);
      state.clear();
      renderReport(report, entry);
    } catch (ex) {
      show("live");
      $("live-error").textContent = ex.message;
      $("live-error").classList.remove("hidden");
    }
  }

  const DIMS = [
    ["accuracy", "Accuracy"], ["depth", "Depth"], ["structure", "Structure"], ["communication", "Communication"],
  ];

  function scoreBar(name, value) {
    const pct = ((value - 1) / 4) * 100;
    const tone = scoreTone(pct);
    return el("div", { class: "bar-row" },
      el("div", { class: "top" }, el("span", {}, name), el("span", {}, `${Number(value).toFixed(1)} / 5`)),
      el("div", { class: "bar" }, el("div", { style: { width: `${Math.max(pct, 3)}%`, background: tone.col } })));
  }

  function list(items, empty) {
    if (!items?.length) return el("p", { class: "muted small" }, empty);
    return el("ul", { style: { paddingLeft: "20px", margin: 0 } }, items.map((i) => el("li", { style: { marginBottom: "6px" } }, i)));
  }

  function renderReport(report, meta) {
    const tone = scoreTone(report.overall_score);
    const ring = el("div", { class: "score-ring", style: { "--val": report.overall_score, "--col": tone.col } },
      el("div", {}, el("div", {}, el("strong", {}, String(report.overall_score)), el("span", { class: "small muted" }, "/ 100"))));
    ring.style.setProperty("--val", report.overall_score);
    ring.style.setProperty("--col", tone.col);

    const questionCards = report.questions.map((q, i) => {
      const avg = DIMS.reduce((s, [d]) => s + q.scores[d], 0) / DIMS.length;
      const t = scoreTone(((avg - 1) / 4) * 100);
      return el("details", { class: "qresult", open: i === 0 },
        el("summary", {},
          el("span", { class: `badge ${t.badge}` }, `Q${i + 1}`),
          el("span", {}, el("strong", {}, q.topic), el("span", { class: "small muted" }, ` · ${label(q.module)}`)),
          el("span", { class: "qscore", style: { color: t.col } }, `${avg.toFixed(1)} / 5`)),
        el("div", { class: "qbody" },
          el("p", { style: { fontWeight: 600 } }, q.question),
          el("div", { class: "mini-scores" }, DIMS.map(([d, n]) => el("span", { class: "badge badge-muted" }, `${n} ${q.scores[d]}/5`))),
          el("p", {}, q.feedback),
          q.missed_points.length ? el("div", { style: { marginBottom: "14px" } },
            el("strong", { class: "small" }, "What you missed"), list(q.missed_points)) : null,
          el("strong", { class: "small" }, "Model answer"),
          el("div", { class: "model-answer", style: { marginTop: "6px" } }, q.model_answer)));
    });

    $("view-report").replaceChildren(
      el("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: "16px", flexWrap: "wrap", marginBottom: "24px" } },
        el("div", {},
          el("span", { class: "eyebrow" }, "Interview report"),
          el("h1", { style: { fontSize: "clamp(1.8rem,4vw,2.4rem)", margin: 0 } },
            meta?.role ? `${label(meta.role)} · ${label(meta.level)}` : "Your results"),
          meta?.date ? el("p", { class: "muted small", style: { margin: "6px 0 0" } }, new Date(meta.date).toLocaleString()) : null),
        el("div", { style: { display: "flex", gap: "10px", flexWrap: "wrap" } },
          el("a", { class: "btn btn-ghost", href: "/dashboard/" }, "View dashboard"),
          el("a", { class: "btn btn-primary", href: "/interview/" }, "New interview"))),

      el("div", { class: "grid grid-3", style: { marginBottom: "20px" } },
        el("div", { class: "card center" },
          ring,
          el("p", { style: { margin: "14px 0 4px" } }, el("span", { class: `badge ${tone.badge}` }, tone.text)),
          el("p", { class: "small muted", style: { margin: 0 } },
            `${report.questions.length} graded${report.skipped_questions ? ` · ${report.skipped_questions} skipped` : ""}`)),
        el("div", { class: "card" },
          el("h3", {}, "Rubric breakdown"),
          DIMS.map(([d, n]) => scoreBar(n, report.rubric_averages[d]))),
        el("div", { class: "card" },
          el("h3", {}, "Weak topics"),
          report.weak_topics.length
            ? el("div", {}, report.weak_topics.map((t) => el("a", {
                class: "chip", href: `/learn/?q=${encodeURIComponent(t)}`, title: "Find learning resources",
              }, `📚 ${t}`)),
                el("p", { class: "small muted", style: { marginTop: "8px" } }, "Tap a topic to find resources, then discuss it with the AI tutor."))
            : el("p", { class: "muted small" }, "No major weak spots. Try a harder level next."))),

      el("div", { class: "card", style: { marginBottom: "20px" } },
        el("h3", {}, "Coach's summary"),
        el("p", {}, report.coach.summary),
        el("div", { class: "grid grid-3", style: { marginTop: "8px" } },
          el("div", {}, el("strong", {}, "Strengths"), list(report.coach.strengths, "Keep practicing to build standout strengths.")),
          el("div", {}, el("strong", {}, "Improve"), list(report.coach.improvement_areas, "Nothing major.")),
          el("div", {}, el("strong", {}, "Study plan"), list(report.coach.study_plan, "—")))),

      el("h2", { style: { fontSize: "1.4rem", margin: "32px 0 16px" } }, "Question by question"),
      ...questionCards,
    );
    show("report");
  }

  // ---------- Boot: resume an in-progress session or show a finished report ----------
  async function boot() {
    initSetup();
    initLive();
    const params = new URLSearchParams(location.search);
    const id = params.get("session") || store.get("pv.active", null);
    if (!id) return;

    setLoading("Loading your session…", "");
    show("loading");
    try {
      const turn = await api(`/interview/${id}`);
      if (turn.status === "completed" && turn.report) {
        const meta = PV.history().find((h) => h.id === id);
        renderReport(turn.report, meta);
        return;
      }
      if (!state.load(id)) state.reset(id, null);
      const last = state.transcript[state.transcript.length - 1];
      if (turn.status === "in_progress" && (!last || last.text !== turn.question)) state.addQuestion(turn);
      history.replaceState(null, "", `?session=${id}`);
      if (turn.status === "awaiting_report") { await finish(); return; }
      enterLive(turn);
    } catch (ex) {
      // Server restarted (in-memory store) or session not found: fall back to a saved report.
      const saved = PV.history().find((h) => h.id === id);
      if (saved) { renderReport(saved.report, saved); return; }
      store.del(`pv.session.${id}`);
      store.del("pv.active");
      history.replaceState(null, "", location.pathname);
      show("setup");
      if (ex.status === 404) PV.toast("That session has expired. Start a new one below.");
      else { $("setup-error").textContent = ex.message; $("setup-error").classList.remove("hidden"); }
    }
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
