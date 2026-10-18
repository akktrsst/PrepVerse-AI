// PrepVerse AI — shared helpers: layout, theme, API, safe DOM building, local history.
"use strict";

const PV = (() => {
  // ---- Safe DOM builder: all text goes through textContent (model output is untrusted). ----
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c == null || c === false) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }

  // ---- Storage (per-browser convenience; always guarded) ----
  const store = {
    get(key, fallback) {
      try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode etc. */ }
    },
    del(key) { try { localStorage.removeItem(key); } catch {} },
  };

  // ---- API ----
  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }
  // ---- Auth state (auth.js fills this in via PV._setAuth) ----
  let resolveReady;
  const auth = {
    enabled: null,       // false = server runs with AUTH_DISABLED (local dev)
    configured: true,    // false = auth on, but no Firebase web config
    user: null,          // { name, email, photo }
    ready: new Promise((r) => { resolveReady = r; }),
    _impl: null,
    async getToken() { return auth._impl ? auth._impl.getToken() : null; },
    signIn() { return auth._impl ? auth._impl.signIn() : Promise.reject(new Error("Sign-in isn't configured")); },
    signOut() { return auth._impl ? auth._impl.signOut() : Promise.resolve(); },
  };
  const authListeners = [];
  function onAuthChange(fn) { authListeners.push(fn); }
  function _setAuth(patch) {
    Object.assign(auth, patch);
    resolveReady();
    authListeners.forEach((fn) => fn(auth));
  }

  async function authHeaders() {
    await auth.ready;
    const token = await auth.getToken().catch(() => null);
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function errorFrom(res) {
    const data = await res.json().catch(() => ({}));
    let msg = data.detail;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
    if (res.status === 401) msg = "Please sign in to continue.";
    if (res.status === 429) msg = typeof msg === "string" && msg.includes("note") ? msg
      : "You've hit today's AI usage limit. It resets at midnight UTC.";
    if (res.status === 502) msg = "The AI service had a hiccup. Please try again.";
    return new ApiError(res.status, msg || `Request failed (${res.status})`);
  }

  /** API calls take paths like "/learn/topics"; the server serves them under /api. */
  const apiUrl = (path) => (path.startsWith("/api/") ? path : `/api${path}`);

  async function rawFetch(path, { method = "GET", body } = {}) {
    let res;
    try {
      res = await fetch(apiUrl(path), {
        method,
        headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(await authHeaders()) },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch {
      throw new ApiError(0, "Can't reach the server. Is the backend running?");
    }
    if (!res.ok) throw await errorFrom(res);
    return res;
  }

  async function api(path, opts) {
    const res = await rawFetch(path, opts);
    if (res.status === 204) return null;
    const type = res.headers.get("content-type") || "";
    return type.includes("json") ? res.json() : res.text();
  }

  /** POST and read a Server-Sent Events stream; calls onEvent(event, data) for each event. */
  async function stream(path, body, onEvent) {
    const res = await rawFetch(path, { method: "POST", body });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let event = "message";
        const data = [];
        for (const line of raw.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7);
          else if (line.startsWith("data: ")) data.push(line.slice(6));
        }
        if (data.length) onEvent(event, JSON.parse(data.join("\n")));
      }
    }
  }

  /** Resolve true when the user may call authenticated APIs; otherwise render a sign-in prompt into `host`. */
  async function requireAuth(host, what = "this feature") {
    await auth.ready;
    if (auth.enabled === false || auth.user) return true;
    const card = el("div", { class: "card empty" },
      el("div", { class: "icon-tile", style: { margin: "0 auto 14px" } }, "🔐"),
      el("h3", {}, `Sign in to use ${what}`),
      el("p", { class: "muted" }, auth.configured
        ? "Your notes and sessions are saved to your account so they sync across devices."
        : "Sign-in isn't configured on this server yet (missing Firebase web config)."),
      auth.configured ? el("button", { class: "btn btn-primary", onclick: () => auth.signIn().catch((e) => toast(e.message)) },
        "Continue with Google") : null);
    host.replaceChildren(card);
    onAuthChange((a) => { if (a.user) location.reload(); });
    return false;
  }

  // ---- Interview history (summaries saved when a report completes) ----
  const HISTORY_KEY = "pv.history";
  function history() { return store.get(HISTORY_KEY, []); }
  function saveToHistory(entry) {
    const list = history().filter((h) => h.id !== entry.id);
    list.push(entry);
    store.set(HISTORY_KEY, list.slice(-50));
  }

  // ---- Labels ----
  const LABELS = {
    data_analyst: "Data Analyst", data_scientist: "Data Scientist", ml_engineer: "ML Engineer",
    ai_engineer: "AI Engineer", agent_developer: "Agent Developer",
    data_science: "Data Science", genai_llms: "GenAI & LLMs", ai_agents: "AI Agents",
    beginner: "Beginner", intermediate: "Intermediate", advanced: "Advanced",
    startup: "Startup", faang: "Big Tech", service: "Services", product: "Product company",
  };
  const label = (k) => LABELS[k] || k;

  function scoreTone(score100) {
    if (score100 >= 75) return { col: "var(--good)", badge: "badge-good", text: "Interview-ready" };
    if (score100 >= 50) return { col: "var(--warn)", badge: "badge-warn", text: "Getting there" };
    return { col: "var(--bad)", badge: "badge-bad", text: "Needs work" };
  }

  // ---- UI bits ----
  function toast(msg, ms = 3200) {
    const t = el("div", { class: "toast", role: "status" }, msg);
    document.body.append(t);
    setTimeout(() => t.remove(), ms);
  }
  function modal(title, body, actions) {
    const close = () => backdrop.remove();
    const backdrop = el("div", { class: "modal-backdrop", onclick: (e) => e.target === backdrop && close() },
      el("div", { class: "card modal", role: "dialog", "aria-modal": "true", "aria-label": title },
        el("h3", {}, title),
        typeof body === "string" ? el("p", { class: "muted" }, body) : body,
        el("div", { style: { display: "flex", gap: "10px", justifyContent: "flex-end", marginTop: "16px" } },
          ...(actions || []).map((a) => el("a", {
            class: `btn ${a.primary ? "btn-primary" : "btn-ghost"}`, href: a.href || "#",
            onclick: (e) => { if (!a.href) e.preventDefault(); close(); a.onClick && a.onClick(); },
          }, a.label)),
        )));
    document.addEventListener("keydown", function esc(e) {
      if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); }
    });
    document.body.append(backdrop);
  }

  // ---- Theme ----
  function applyTheme(t) {
    if (t) document.documentElement.setAttribute("data-theme", t);
    else document.documentElement.removeAttribute("data-theme");
  }
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme")
      || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }
  applyTheme(store.get("pv.theme", null));

  // ---- Layout ----
  const NAV = [
    ["/learn/", "Learn"],
    ["/discuss/", "Discuss"],
    ["/interview/", "Mock Interview"],
    ["/notes/", "Notes"],
    ["/dashboard/", "Dashboard"],
    ["/pricing/", "Pricing"],
  ];

  function renderAuthSlot(slot) {
    if (auth.enabled === null) { slot.replaceChildren(); return; }
    if (auth.enabled === false) {
      slot.replaceChildren(el("a", { class: "btn btn-primary", href: "/interview/" }, "Start free interview"));
      return;
    }
    if (!auth.user) {
      slot.replaceChildren(el("button", {
        class: "btn btn-primary", disabled: !auth.configured,
        title: auth.configured ? null : "Sign-in isn't configured on this server",
        onclick: () => auth.signIn().catch((e) => toast(e.message)),
      }, "Sign in"));
      return;
    }
    const u = auth.user;
    const initial = (u.name || u.email || "?").trim()[0].toUpperCase();
    const menu = el("div", { class: "user-menu hidden", role: "menu" },
      el("div", { class: "small", style: { padding: "8px 12px" } }, el("strong", {}, u.name || "Signed in"),
        el("div", { class: "muted" }, u.email || "")),
      el("a", { href: "/notes/", role: "menuitem" }, "My notes"),
      el("a", { href: "/dashboard/", role: "menuitem" }, "Dashboard"),
      el("button", { role: "menuitem", onclick: () => auth.signOut().then(() => location.reload()) }, "Sign out"));
    const btn = el("button", {
      class: "avatar-btn", "aria-label": "Account menu", "aria-haspopup": "menu",
      onclick: (e) => { e.stopPropagation(); menu.classList.toggle("hidden"); },
    }, u.photo ? el("img", { src: u.photo, alt: "", referrerpolicy: "no-referrer" }) : initial);
    document.addEventListener("click", () => menu.classList.add("hidden"));
    slot.replaceChildren(el("div", { style: { position: "relative" } }, btn, menu));
  }

  function renderHeader() {
    const host = document.getElementById("site-header");
    if (!host) return;
    const path = location.pathname.replace(/index\.html$/, "");
    const links = el("nav", { class: "nav-links", id: "nav-links", "aria-label": "Main" },
      NAV.map(([href, text]) => el("a", { href, class: path.startsWith(href) ? "active" : null }, text)));
    const themeBtn = el("button", { class: "icon-btn", "aria-label": "Toggle dark mode", title: "Toggle theme" });
    const syncIcon = () => { themeBtn.textContent = currentTheme() === "dark" ? "☀" : "☾"; };
    themeBtn.addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      applyTheme(next); store.set("pv.theme", next); syncIcon();
    });
    syncIcon();
    const menuBtn = el("button", {
      class: "icon-btn menu-btn", "aria-label": "Menu", "aria-controls": "nav-links",
      onclick: () => links.classList.toggle("open"),
    }, "☰");
    const slot = el("div", { class: "auth-slot" });
    renderAuthSlot(slot);
    onAuthChange(() => renderAuthSlot(slot));
    host.className = "site-header";
    host.append(el("div", { class: "container nav" },
      el("a", { class: "brand", href: "/" }, el("span", { class: "brand-mark" }, "P"), "PrepVerse AI"),
      links,
      el("div", { class: "nav-right" }, themeBtn, slot, menuBtn)));
  }

  function renderFooter() {
    const host = document.getElementById("site-footer");
    if (!host) return;
    host.className = "site-footer";
    host.append(el("div", { class: "container" },
      el("div", { class: "footer-grid" },
        el("div", {},
          el("a", { class: "brand", href: "/" }, el("span", { class: "brand-mark" }, "P"), "PrepVerse AI"),
          el("p", { style: { marginTop: "12px", maxWidth: "320px" } },
            "AI interview prep for Data Science, ML, GenAI and AI Agent roles, always up to date with the field.")),
        el("div", {}, el("h4", {}, "Product"),
          el("a", { href: "/learn/" }, "Learn Hub"),
          el("a", { href: "/discuss/" }, "Voice Discuss"),
          el("a", { href: "/interview/" }, "Mock Interview"),
          el("a", { href: "/notes/" }, "Notes"),
          el("a", { href: "/pricing/" }, "Pricing")),
        el("div", {}, el("h4", {}, "Tracks"),
          el("a", { href: "/interview/?module=data_science" }, "Data Science"),
          el("a", { href: "/interview/?module=genai_llms" }, "GenAI & LLMs"),
          el("a", { href: "/interview/?module=ai_agents" }, "AI Agents")),
        el("div", {}, el("h4", {}, "Developers"),
          el("a", { href: "/api/docs" }, "API docs"),
          el("a", { href: "/api/healthz" }, "Status"))),
      el("p", { class: "small", style: { marginTop: "28px" } }, `© ${new Date().getFullYear()} PrepVerse AI`)));
  }

  document.addEventListener("DOMContentLoaded", () => { renderHeader(); renderFooter(); });

  // Load the auth module on every page (Firebase is only fetched when sign-in is enabled).
  const authScript = document.createElement("script");
  authScript.type = "module";
  authScript.src = "/assets/auth.js";
  document.head.append(authScript);

  return {
    el, api, stream, ApiError, store, history, saveToHistory, label, scoreTone, toast, modal,
    auth, onAuthChange, requireAuth, _setAuth,
  };
})();
