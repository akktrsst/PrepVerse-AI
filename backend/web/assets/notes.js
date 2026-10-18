// Notebook: highlights, personal notes and AI session notes, grouped by topic.
"use strict";

(() => {
  const { el, api, toast } = PV;
  const $ = (id) => document.getElementById(id);
  const COLORS = ["yellow", "green", "blue", "pink"];
  const KINDS = [["all", "All"], ["highlight", "Highlights"], ["ai_note", "AI notes"], ["manual", "My notes"]];

  let notes = [];
  let topics = [];
  const state = { topic: new URLSearchParams(location.search).get("topic") || "all", kind: "all", color: null, q: "" };

  const topicName = (id) => topics.find((t) => t.id === id)?.title || "General";
  const fmt = (iso) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

  function filtered() {
    const q = state.q.toLowerCase();
    return notes.filter((n) =>
      (state.topic === "all" || (n.topic_id || "general") === state.topic)
      && (state.kind === "all" || n.kind === state.kind)
      && (!state.color || n.color === state.color)
      && (!q || `${n.quote} ${n.text} ${n.source_title || ""}`.toLowerCase().includes(q)));
  }

  // ---------- Sidebar ----------
  function renderTopics() {
    const counts = {};
    notes.forEach((n) => { const k = n.topic_id || "general"; counts[k] = (counts[k] || 0) + 1; });
    const rows = [["all", "All notes", notes.length],
      ...Object.keys(counts).sort((a, b) => topicName(a).localeCompare(topicName(b))).map((k) => [k, topicName(k), counts[k]])];
    $("topic-list").replaceChildren(...rows.map(([id, name, n]) => el("button", {
      class: id === state.topic ? "on" : null,
      onclick: () => { state.topic = id; history.replaceState(null, "", id === "all" ? location.pathname : `?topic=${encodeURIComponent(id)}`); render(); },
    }, el("span", {}, name), el("span", { class: "muted" }, String(n)))));
  }

  // ---------- Cards ----------
  function noteCard(n) {
    const editing = el("div", { class: "hidden", style: { marginTop: "8px" } });
    const textEl = n.text ? el("p", { class: "note-text" }, n.text) : null;
    const card = el("article", { class: `card note-card c-${n.color}` },
      n.quote ? el("p", { class: "note-quote" }, el("mark", { class: `hl hl-${n.color}` }, n.quote)) : null,
      textEl, editing,
      el("div", { class: "note-foot" },
        el("span", {},
          n.kind === "manual" ? "✎ My note" : "★ Highlight",
          n.source_title ? [" · ", n.source_url
            ? el("a", { href: n.source_url, target: n.source_url.startsWith("/") ? null : "_blank", rel: "noopener" }, n.source_title)
            : n.source_title] : null,
          ` · ${fmt(n.created_at)}`),
        el("span", { class: "acts" },
          el("button", { onclick: () => startEdit(n, card, editing, textEl) }, "Edit"),
          el("button", { onclick: () => remove([n.id], "Delete this note?") }, "Delete"))));
    return card;
  }

  function startEdit(n, card, host, textEl) {
    let color = n.color;
    const ta = el("textarea", { maxlength: "4000", placeholder: "Your note…", style: { minHeight: "80px" } });
    ta.value = n.text;
    const dots = el("div", { style: { display: "flex", gap: "6px", alignItems: "center" } },
      COLORS.map((c) => el("button", {
        class: `icon-btn`, title: c, "aria-label": `${c}`, style: { width: "26px", height: "26px", borderRadius: "50%", background: `var(--hl-${c}-bar)`, outline: c === color ? "2px solid var(--text)" : "none" },
        onclick: (e) => { color = c; dots.querySelectorAll("button").forEach((b) => { b.style.outline = b === e.currentTarget ? "2px solid var(--text)" : "none"; }); },
      })));
    host.replaceChildren(ta, el("div", { style: { display: "flex", justifyContent: "space-between", gap: "8px", marginTop: "8px", flexWrap: "wrap" } },
      dots,
      el("div", { style: { display: "flex", gap: "8px" } },
        el("button", { class: "btn btn-ghost", onclick: () => { host.classList.add("hidden"); textEl?.classList.remove("hidden"); } }, "Cancel"),
        el("button", { class: "btn btn-primary", onclick: async () => {
          try {
            const updated = await api(`/notes/${n.id}`, { method: "PATCH", body: { text: ta.value.trim(), color } });
            notes = notes.map((x) => (x.id === n.id ? updated : x));
            render();
          } catch (e) { toast(e.message); }
        } }, "Save"))));
    host.classList.remove("hidden");
    textEl?.classList.add("hidden");
    ta.focus();
  }

  function sessionCard(items) {
    const first = items[0];
    const section = (key, title) => {
      const rows = items.filter((n) => n.section === key);
      return rows.length ? el("div", {}, el("h4", {}, title), el("ul", {}, rows.map((n) =>
        el("li", {}, key === "definition" ? [el("strong", {}, n.quote), `: ${n.text}`] : n.text)))) : null;
    };
    return el("article", { class: "card note-card c-green session-notes", "data-highlightable": "" },
      el("div", { class: "note-foot", style: { marginBottom: "4px" } },
        el("strong", { style: { color: "var(--text)", fontSize: ".95rem" } }, `🎙 ${first.source_title || "Discussion notes"}`),
        el("span", {}, fmt(first.created_at))),
      section("takeaway", "Key takeaways"),
      section("definition", "Definitions"),
      section("review_question", "Review questions"),
      el("div", { class: "note-foot", style: { marginTop: "12px" } },
        first.session_id ? el("a", { href: `/discuss/?session=${encodeURIComponent(first.session_id)}` }, "Continue this discussion →") : el("span"),
        el("span", { class: "acts" },
          el("button", { onclick: () => remove(items.map((n) => n.id), "Delete these session notes?") }, "Delete"))));
  }

  async function remove(ids, question) {
    PV.modal(question, "This can't be undone.", [{ label: "Cancel" }, {
      label: "Delete", primary: true, onClick: async () => {
        try {
          await Promise.all(ids.map((id) => api(`/notes/${id}`, { method: "DELETE" })));
          notes = notes.filter((n) => !ids.includes(n.id));
          render();
        } catch (e) { toast(e.message); }
      },
    }]);
  }

  // ---------- Main ----------
  function renderFilters() {
    $("kind-tabs").replaceChildren(...KINDS.map(([k, name]) => el("button", {
      class: `tab${k === state.kind ? " on" : ""}`, onclick: () => { state.kind = k; render(); },
    }, name)));
    $("color-filter").replaceChildren(...COLORS.map((c) => el("button", {
      class: `dot dot-${c}`, title: `Only ${c}`, "aria-label": `Only ${c} notes`, "aria-pressed": String(state.color === c),
      style: { width: "22px", height: "22px", borderRadius: "50%", border: state.color === c ? "2px solid var(--text)" : "2px solid transparent", background: `var(--hl-${c}-bar)`, cursor: "pointer", opacity: state.color && state.color !== c ? ".35" : "1" },
      onclick: () => { state.color = state.color === c ? null : c; render(); },
    })));
    const t = state.topic;
    $("discuss-btn").href = t !== "all" && t !== "general" ? `/discuss/?topic=${encodeURIComponent(t)}` : "/discuss/";
    $("heading").textContent = t === "all" ? "All notes" : topicName(t === "general" ? null : t);
  }

  function renderFeed() {
    const list = filtered();
    const feed = $("feed");
    if (!notes.length) {
      feed.replaceChildren(el("div", { class: "card empty" },
        el("div", { class: "icon-tile", style: { margin: "0 auto 14px" } }, "🖍"),
        el("h3", {}, "Your notebook is empty"),
        el("p", { class: "muted" }, "Select text in any Learn Hub summary or AI answer to highlight it, or end a Discuss session to get AI study notes."),
        el("div", { class: "res-actions", style: { justifyContent: "center" } },
          el("a", { class: "btn btn-primary", href: "/learn/" }, "Browse Learn Hub"),
          el("a", { class: "btn btn-ghost", href: "/discuss/" }, "Start a discussion"))));
      return;
    }
    if (!list.length) { feed.replaceChildren(el("p", { class: "muted" }, "No notes match these filters.")); return; }

    // Group AI notes by session; keep everything newest first.
    const groups = new Map();
    const cards = [];
    for (const n of list) {
      if (n.kind === "ai_note") {
        const key = n.session_id || n.id;
        if (!groups.has(key)) { groups.set(key, []); cards.push({ at: n.created_at, session: key }); }
        groups.get(key).push(n);
      } else {
        cards.push({ at: n.created_at, note: n });
      }
    }
    cards.sort((a, b) => b.at.localeCompare(a.at));
    feed.replaceChildren(...cards.map((c) => (c.note ? noteCard(c.note) : sessionCard(groups.get(c.session)))));
  }

  function render() { renderTopics(); renderFilters(); renderFeed(); }

  function newNote() {
    let color = "yellow";
    const ta = el("textarea", { maxlength: "4000", placeholder: "Write a note…", style: { minHeight: "120px" } });
    const sel = el("select", {}, el("option", { value: "" }, "General"),
      ...topics.map((t) => el("option", { value: t.id, selected: t.id === state.topic }, t.title)));
    const body = el("div", { class: "stack", style: { gap: "10px" } },
      ta, el("label", { class: "field small" }, "Topic"), sel,
      el("div", { style: { display: "flex", gap: "8px" } }, COLORS.map((c) => el("button", {
        class: "icon-btn", "aria-label": c,
        style: { width: "26px", height: "26px", borderRadius: "50%", background: `var(--hl-${c}-bar)`, outline: c === color ? "2px solid var(--text)" : "none" },
        onclick: (e) => { color = c; e.currentTarget.parentElement.querySelectorAll("button").forEach((b) => { b.style.outline = b === e.currentTarget ? "2px solid var(--text)" : "none"; }); },
      }))));
    PV.modal("New note", body, [{ label: "Cancel" }, { label: "Save", primary: true, onClick: async () => {
      if (!ta.value.trim()) return;
      try {
        const n = await api("/notes", { method: "POST", body: { kind: "manual", text: ta.value.trim(), color, topic_id: sel.value || null } });
        notes.unshift(n);
        render();
      } catch (e) { toast(e.message); }
    } }]);
    setTimeout(() => ta.focus(), 50);
  }

  async function exportMd() {
    try {
      const t = state.topic;
      const md = await api(`/notes/export.md${t !== "all" && t !== "general" ? `?topic_id=${encodeURIComponent(t)}` : ""}`);
      const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
      const a = el("a", { href: url, download: `prepverse-notes${t !== "all" ? `-${t}` : ""}.md` });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { toast(e.message); }
  }

  async function boot() {
    if (!(await PV.requireAuth($("notes-root"), "your notebook"))) return;
    $("search").addEventListener("input", (e) => { state.q = e.target.value; renderFeed(); });
    $("export-btn").addEventListener("click", exportMd);
    $("new-btn").addEventListener("click", newNote);
    try {
      [notes, topics] = await Promise.all([api("/notes"), api("/learn/topics")]);
      render();
    } catch (e) {
      $("feed").replaceChildren(el("div", { class: "alert" }, e.message));
    }
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
