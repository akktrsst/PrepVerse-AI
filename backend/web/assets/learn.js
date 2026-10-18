// Learn Hub: topic browser (/learn/) and topic page (/learn/topic/?id=).
"use strict";

(() => {
  const { el, api, label } = PV;
  const $ = (id) => document.getElementById(id);

  const TYPES = {
    video: { icon: "▶", name: "Videos", one: "Video" },
    paper: { icon: "📄", name: "Papers", one: "Paper" },
    blog: { icon: "✍", name: "Blogs", one: "Blog" },
    repo: { icon: "⌥", name: "Repos", one: "Repo" },
    discussion: { icon: "💬", name: "Discussions", one: "Discussion" },
  };
  const DIFF = { easy: ["badge-good", "Beginner"], medium: ["badge-warn", "Intermediate"], hard: ["badge-bad", "Advanced"] };

  const compact = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}k` : String(n));
  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short" }) : "");
  const fmtDur = (s) => { const m = Math.floor(s / 60); return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}` : `${m}:${String(s % 60).padStart(2, "0")}`; };
  const toSeconds = (ts) => ts.split(":").reduce((a, p) => a * 60 + Number(p), 0);
  /** `code` and **bold** from model text, as safe DOM nodes. */
  function rich(text) {
    const out = [];
    const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
    let last = 0, m;
    while ((m = re.exec(text || ""))) {
      if (m.index > last) out.push(text.slice(last, m.index));
      out.push(m[0].startsWith("**") ? el("strong", {}, m[0].slice(2, -2)) : el("code", {}, m[0].slice(1, -1)));
      last = m.index + m[0].length;
    }
    if (last < (text || "").length) out.push(text.slice(last));
    return out;
  }
  const videoId = (url) => { try { return new URL(url).searchParams.get("v"); } catch { return null; } };

  function metric(r) {
    const m = r.metrics || {};
    if (r.type === "video" && m.views) return `👁 ${compact(m.views)} views`;
    if (r.type === "repo" && m.stars) return `★ ${compact(m.stars)}`;
    if (r.type === "discussion" && m.points) return `▲ ${compact(m.points)} · ${compact(m.comments || 0)} comments`;
    return null;
  }

  function watch(r, startSeconds = 0) {
    const id = videoId(r.url);
    if (!id) { window.open(r.url, "_blank", "noopener"); return; }
    const src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?autoplay=1&rel=0&start=${Math.floor(startSeconds)}`;
    const close = () => backdrop.remove();
    const backdrop = el("div", { class: "modal-backdrop", onclick: (e) => e.target === backdrop && close() },
      el("div", { class: "card modal wide", role: "dialog", "aria-modal": "true", "aria-label": r.title },
        el("div", { style: { display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start", marginBottom: "12px" } },
          el("h3", { style: { margin: 0 } }, r.title),
          el("button", { class: "icon-btn", "aria-label": "Close", onclick: close }, "✕")),
        el("div", { class: "video-wrap" },
          el("iframe", { src, title: r.title, allow: "autoplay; encrypted-media; picture-in-picture", allowfullscreen: true })),
        el("div", { class: "res-actions", style: { marginTop: "14px" } },
          el("a", { class: "btn btn-primary", href: discussHref(r) }, "🎙 Discuss this video"),
          el("a", { class: "btn btn-ghost", href: r.url, target: "_blank", rel: "noopener" }, "Open on YouTube ↗"))));
    const esc = (e) => { if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); } };
    document.addEventListener("keydown", esc);
    document.body.append(backdrop);
  }

  const discussHref = (r) => `/discuss/?resource=${encodeURIComponent(r.id)}${r.topic_ids?.[0] ? `&topic=${encodeURIComponent(r.topic_ids[0])}` : ""}`;

  function resourceCard(r, topicId) {
    const t = TYPES[r.type];
    const [diffCls, diffText] = DIFF[r.difficulty] || DIFF.medium;
    const isVideo = r.type === "video" && r.thumbnail;
    const thumb = isVideo ? el("button", { class: "res-thumb", "aria-label": `Watch ${r.title}`, onclick: () => watch(r) },
      el("img", { src: r.thumbnail, alt: "", loading: "lazy" }),
      el("span", { class: "play" }, "▶"),
      r.metrics?.duration_s ? el("span", { class: "dur" }, fmtDur(r.metrics.duration_s)) : null) : null;

    return el("article", { class: `card res-card${thumb ? "" : " no-thumb"}` },
      thumb,
      el("div", { "data-highlightable": "", "data-resource": r.id, "data-topic": topicId || r.topic_ids?.[0] || "" },
        el("div", { class: "res-meta" },
          el("span", { class: "badge badge-muted" }, `${t.icon} ${t.one}`),
          el("span", {}, [r.source, r.author && r.author !== r.source ? r.author : null, fmtDate(r.published_at)].filter(Boolean).join(" · ")),
          metric(r) ? el("span", {}, `· ${metric(r)}`) : null,
          el("span", { class: `badge ${diffCls}` }, diffText)),
        el("h3", { class: "res-title" }, el("a", { href: r.url, target: "_blank", rel: "noopener" }, r.title)),
        el("p", { class: "res-summary" }, rich(r.summary)),
        r.chapters?.length ? el("div", { class: "chapters", "aria-label": "Chapters" },
          r.chapters.map((c) => el("button", { onclick: () => watch(r, toSeconds(c.time)), title: `Jump to ${c.time}` },
            el("b", {}, c.time), c.title))) : null,
        r.key_points?.length ? el("ul", { class: "res-points" }, r.key_points.map((p) => el("li", {}, rich(p)))) : null,
        r.why_it_matters ? el("div", { class: "why" }, el("strong", {}, "Why it matters for interviews: "), rich(r.why_it_matters)) : null,
        el("div", { class: "res-actions" },
          isVideo ? el("button", { class: "btn btn-primary", onclick: () => watch(r) }, "▶ Watch")
            : el("a", { class: "btn btn-primary", href: r.url, target: "_blank", rel: "noopener" }, "Open ↗"),
          el("a", { class: "btn btn-ghost", href: discussHref(r) }, "🎙 Discuss this"))));
  }

  function emptyState(title, text) {
    return el("div", { class: "card empty" }, el("div", { class: "icon-tile", style: { margin: "0 auto 14px" } }, "📚"),
      el("h3", {}, title), el("p", { class: "muted", style: { margin: 0 } }, text));
  }

  // ---------- /learn/ ----------
  async function bootIndex() {
    const grid = $("topic-grid");
    let topics = [];
    let module = new URLSearchParams(location.search).get("module") || "all";
    const MODS = [["all", "All topics"], ["data_science", "Data Science"], ["genai_llms", "GenAI & LLMs"], ["ai_agents", "AI Agents"]];

    function renderTabs() {
      $("module-tabs").replaceChildren(...MODS.map(([m, name]) => el("button", {
        class: `tab${m === module ? " on" : ""}`, onclick: () => { module = m; renderTabs(); renderGrid(); },
      }, name)));
    }
    function renderGrid() {
      const shown = topics.filter((t) => module === "all" || t.module === module);
      grid.replaceChildren(...shown.map((t) => el("a", { class: "card topic-card", href: `/learn/topic/?id=${encodeURIComponent(t.id)}` },
        el("div", { style: { display: "flex", gap: "8px", marginBottom: "10px", flexWrap: "wrap" } },
          el("span", { class: "badge" }, label(t.module)), el("span", { class: "badge badge-muted" }, label(t.level))),
        el("h3", {}, t.title),
        el("p", { class: "muted small", style: { margin: 0 } }, t.description),
        el("div", { class: "type-counts" }, t.total
          ? Object.keys(TYPES).filter((k) => t.counts[k]).map((k) => el("span", {}, `${TYPES[k].icon} ${t.counts[k]}`))
          : el("span", { style: { color: "var(--accent)", fontWeight: 600 } }, "Not indexed yet · Find resources →")))));
    }

    renderTabs();
    try {
      topics = await api("/learn/topics");
      renderGrid();
    } catch (e) {
      grid.replaceChildren(emptyState("Couldn't load topics", e.message));
    }

    $("search-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const q = $("search-q").value.trim();
      const out = $("search-results");
      if (q.length < 2) { out.replaceChildren(); $("browse").classList.remove("hidden"); return; }
      out.replaceChildren(el("p", { class: "muted" }, "Searching…"));
      try {
        const hits = await api(`/learn/search?q=${encodeURIComponent(q)}`);
        $("browse").classList.add("hidden");
        out.replaceChildren(
          el("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" } },
            el("h2", { style: { fontSize: "1.3rem", margin: 0 } }, `Results for “${q}”`),
            el("button", { class: "btn btn-ghost", onclick: () => { $("search-q").value = ""; out.replaceChildren(); $("browse").classList.remove("hidden"); } }, "Clear")),
          hits.length ? el("div", { class: "stack" }, hits.map((r) => resourceCard(r)))
            : emptyState("No matches yet", "Try a broader term, or browse the topics."));
      } catch (err) {
        out.replaceChildren(el("div", { class: "alert" }, err.message));
      }
    });
    const q = new URLSearchParams(location.search).get("q");
    if (q) { $("search-q").value = q; $("search-form").requestSubmit(); }
  }

  // ---------- /learn/topic/?id= ----------
  async function bootTopic() {
    const id = new URLSearchParams(location.search).get("id");
    const head = $("topic-head");
    const list = $("resource-list");
    let topic, resources = [], type = "all", sort = "score";

    try {
      topic = await api(`/learn/topics/${encodeURIComponent(id || "")}`);
    } catch (e) {
      head.replaceChildren(emptyState("Topic not found", "Pick a topic from the Learn Hub."),
        el("p", { class: "center", style: { marginTop: "16px" } }, el("a", { class: "btn btn-primary", href: "/learn/" }, "Back to Learn Hub")));
      return;
    }
    document.title = `${topic.title} · PrepVerse`;
    head.replaceChildren(
      el("a", { href: `/learn/?module=${topic.module}`, class: "small" }, `← ${label(topic.module)}`),
      el("h1", { style: { fontSize: "clamp(1.8rem,4vw,2.5rem)", margin: "10px 0 8px" } }, topic.title),
      el("p", { class: "muted", style: { maxWidth: "720px" } }, topic.description),
      el("div", { class: "res-actions", style: { marginTop: "16px" } },
        el("a", { class: "btn btn-primary", href: `/discuss/?topic=${encodeURIComponent(topic.id)}` }, "🎙 Discuss this topic"),
        el("a", { class: "btn btn-ghost", href: `/interview/?module=${topic.module}` }, "Practice interview"),
        el("a", { class: "btn btn-ghost", href: `/notes/?topic=${encodeURIComponent(topic.id)}` }, "My notes")));

    const refreshHost = el("div");
    head.append(refreshHost);
    let pollTimer = null;

    function renderTabs() {
      const all = ["all", ...Object.keys(TYPES).filter((k) => topic.counts[k])];
      $("type-tabs").replaceChildren(...(topic.total ? all.map((k) => el("button", {
        class: `tab${k === type ? " on" : ""}`, onclick: () => { type = k; renderTabs(); load(); },
      }, k === "all" ? "All" : `${TYPES[k].icon} ${TYPES[k].name}`,
        el("span", { class: "count" }, String(k === "all" ? topic.total : topic.counts[k])))) : []));
      $("toolbar").classList.toggle("hidden", !topic.total);
    }

    async function load() {
      if (!topic.total) return;
      list.replaceChildren(el("p", { class: "muted" }, "Loading…"));
      const qs = new URLSearchParams({ sort, limit: "100" });
      if (type !== "all") qs.set("type", type);
      try {
        resources = await api(`/learn/topics/${encodeURIComponent(topic.id)}/resources?${qs}`);
        list.replaceChildren(...resources.map((r) => resourceCard(r, topic.id)));
      } catch (e) {
        list.replaceChildren(el("div", { class: "alert" }, e.message));
      }
    }

    // ---- On-demand refresh ("Find resources now") ----
    const SOURCES = ["▶ YouTube", "📄 arXiv", "✍ AI blogs", "⌥ GitHub", "💬 Hacker News"];
    const ago = (iso) => {
      const m = Math.round((Date.now() - new Date(iso)) / 60000);
      return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`;
    };

    async function startRefresh(btn) {
      await PV.auth.ready;
      if (PV.auth.enabled && !PV.auth.user) {
        PV.modal("Sign in to fetch resources", "Fetching uses our AI to read and summarise new material, so it's tied to your account's daily budget.",
          [{ label: "Not now" }, { label: "Continue with Google", primary: true, onClick: () => PV.auth.signIn().catch((e) => PV.toast(e.message)) }]);
        return;
      }
      if (btn) btn.disabled = true;
      try {
        const st = await api(`/learn/topics/${encodeURIComponent(topic.id)}/refresh`, { method: "POST" });
        showStatus(st);
      } catch (e) {
        PV.toast(e.message, 4500);
        if (btn) btn.disabled = false;
      }
    }

    function progressCard(st) {
      const steps = st.steps.filter(([k]) => k !== "queued" && k !== "done");
      const idx = steps.findIndex(([k]) => k === st.step);
      const started = st.started_at ? Math.max(0, Math.round((Date.now() - new Date(st.started_at)) / 1000)) : 0;
      return el("div", { class: "card refresh-card", "aria-live": "polite" },
        el("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: "12px", flexWrap: "wrap" } },
          el("h3", { style: { margin: 0 } }, "Finding the best resources…"),
          el("span", { class: "small muted" }, `${Math.floor(started / 60)}:${String(started % 60).padStart(2, "0")} · usually 1–3 min`)),
        el("div", { class: "progress", style: { margin: "14px 0 16px" } },
          el("div", { style: { width: `${Math.max(5, ((idx + 1) / (steps.length + 1)) * 100)}%` } })),
        el("ol", { class: "steps" }, steps.map(([k, label], i) => el("li", {
          class: i < idx || (idx === -1 && st.step === "done") ? "done" : i === idx ? "now" : "",
        }, label))),
        el("p", { class: "small muted", style: { margin: "14px 0 0" } },
          "You can leave this page. It keeps going, and the resources will be here when you come back."));
    }

    function showStatus(st) {
      clearTimeout(pollTimer);
      const running = st.state === "queued" || st.state === "running";
      if (running) {
        refreshHost.replaceChildren();
        list.replaceChildren(progressCard(st));
        pollTimer = setTimeout(poll, 2000);
        return;
      }
      if (st.state === "done" && st.finished_at && Date.now() - new Date(st.finished_at) < 15000) {
        PV.toast(st.found ? `Found ${st.found} new resource${st.found === 1 ? "" : "s"}` : st.message || "No new resources this time");
      }
      renderRefreshControl(st);
      if (!topic.total) list.replaceChildren(emptyCard(st));
    }

    async function poll() {
      try {
        const st = await api(`/learn/topics/${encodeURIComponent(topic.id)}/refresh`);
        if (st.state === "done") {
          topic = await api(`/learn/topics/${encodeURIComponent(topic.id)}`);
          renderTabs();
          await load();
        }
        showStatus(st);
      } catch {
        pollTimer = setTimeout(poll, 4000);
      }
    }

    function renderRefreshControl(st) {
      if (!topic.total) { refreshHost.replaceChildren(); return; }
      const cooling = st.next_allowed_at && new Date(st.next_allowed_at) > new Date();
      const btn = el("button", {
        class: "btn btn-ghost", disabled: cooling,
        title: cooling ? `Refreshed recently. Next refresh available ${new Date(st.next_allowed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "Search all sources for new material now",
        onclick: (e) => startRefresh(e.currentTarget),
        style: { padding: "6px 12px", fontSize: ".82rem" },
      }, "↻ Check for new");
      refreshHost.replaceChildren(el("div", { class: "small muted", style: { display: "flex", gap: "10px", alignItems: "center", marginTop: "14px", flexWrap: "wrap" } },
        `${topic.total} resources from ${Object.keys(topic.counts).length} source types`,
        st.finished_at ? ` · updated ${ago(st.finished_at)}` : " · refreshed daily",
        btn));
    }

    function emptyCard(st) {
      const failed = st.state === "failed";
      const nothing = st.state === "done" && !st.found;
      return el("div", { class: "card empty", style: { padding: "40px 24px" } },
        el("div", { class: "icon-tile", style: { margin: "0 auto 14px" } }, "🔍"),
        el("h3", {}, `No resources for ${topic.title} yet`),
        el("p", { class: "muted", style: { maxWidth: "520px", margin: "0 auto 16px" } },
          "We can search these sources right now, then summarise, rank and tag the best material for interview prep."),
        el("div", { style: { marginBottom: "20px" } }, SOURCES.map((s) => el("span", { class: "chip" }, s))),
        failed || nothing ? el("div", { class: "alert", style: { maxWidth: "520px", margin: "0 auto 16px", textAlign: "left" } },
          st.message || "The last attempt didn't finish.") : null,
        el("div", { class: "res-actions", style: { justifyContent: "center" } },
          el("button", { class: "btn btn-primary btn-lg", onclick: (e) => startRefresh(e.currentTarget),
            disabled: Boolean(st.next_allowed_at && new Date(st.next_allowed_at) > new Date()) },
            failed ? "Try again" : "🔍 Find resources now"),
          el("a", { class: "btn btn-ghost btn-lg", href: `/discuss/?topic=${encodeURIComponent(topic.id)}` }, "🎙 Discuss it meanwhile")),
        el("p", { class: "small muted", style: { marginTop: "14px" } }, "Takes about 1–3 minutes. New material is also added automatically every day."));
    }

    $("sort").addEventListener("change", (e) => { sort = e.target.value; load(); });
    renderTabs();
    load();
    try {
      showStatus(await api(`/learn/topics/${encodeURIComponent(topic.id)}/refresh`));
    } catch { /* status is optional */ }
    window.addEventListener("pagehide", () => clearTimeout(pollTimer));
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (document.body.dataset.page === "learn-index") bootIndex();
    if (document.body.dataset.page === "learn-topic") bootTopic();
  });

  PV.learn = { resourceCard, watch, TYPES };
})();
