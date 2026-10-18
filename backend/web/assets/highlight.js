// Select text inside any [data-highlightable] element -> colour toolbar -> save as a note.
// The element's data-topic / data-resource / data-session attributes say where the note came from.
"use strict";

(() => {
  const { el, api, auth, toast } = PV;
  const COLORS = ["yellow", "green", "blue", "pink"];
  let toolbar = null;
  let current = null; // { range, root, quote }
  let color = PV.store.get("pv.hlColor", "yellow");

  function hide() {
    toolbar?.remove();
    toolbar = null;
    current = null;
  }

  function selectionInfo() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    const range = sel.getRangeAt(0);
    const anchor = range.commonAncestorContainer.nodeType === 1
      ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement;
    const root = anchor?.closest("[data-highlightable]");
    const quote = sel.toString().replace(/\s+/g, " ").trim();
    if (!root || quote.length < 3) return null;
    return { range: range.cloneRange(), root, quote: quote.slice(0, 2000) };
  }

  function markRange(range, c) {
    try {
      const mark = document.createElement("mark");
      mark.className = `hl hl-${c}`;
      range.surroundContents(mark);
    } catch {
      // Selection spans several elements: the note is saved, we just skip the in-page mark.
    }
  }

  async function save(comment) {
    if (!current) return;
    const { range, root, quote } = current;
    await auth.ready;
    if (auth.enabled && !auth.user) {
      hide();
      PV.modal("Sign in to save notes", "Highlights are saved to your notebook so they sync across devices.",
        [{ label: "Not now" }, { label: "Continue with Google", primary: true, onClick: () => auth.signIn().catch((e) => toast(e.message)) }]);
      return;
    }
    const body = {
      kind: "highlight", quote, text: comment || "", color,
      topic_id: root.dataset.topic || null,
      resource_id: root.dataset.resource || null,
      session_id: root.dataset.session || null,
    };
    hide();
    try {
      await api("/notes", { method: "POST", body });
      markRange(range, body.color);
      window.getSelection()?.removeAllRanges();
      const t = el("div", { class: "toast", role: "status" }, "Saved to your notes · ",
        el("a", { href: `/notes/${body.topic_id ? `?topic=${encodeURIComponent(body.topic_id)}` : ""}`, style: { color: "inherit", textDecoration: "underline" } }, "Open notes"));
      document.body.append(t);
      setTimeout(() => t.remove(), 3500);
    } catch (e) {
      toast(e.message);
    }
  }

  function show(info) {
    hide();
    current = info;
    const rect = info.range.getBoundingClientRect();
    const dots = COLORS.map((c) => el("button", {
      class: `dot dot-${c}${c === color ? " on" : ""}`, title: `${c} highlight`, "aria-label": `${c} highlight`,
      onclick: (e) => {
        e.preventDefault();
        color = c;
        PV.store.set("pv.hlColor", c);
        toolbar.querySelectorAll(".dot").forEach((d) => d.classList.toggle("on", d === e.currentTarget));
      },
    }));
    const input = el("input", { type: "text", placeholder: "Add a comment (optional)", maxlength: "4000", class: "hidden",
      onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); save(input.value.trim()); } } });
    const noteBtn = el("button", { class: "act", onclick: (e) => {
      e.preventDefault(); input.classList.toggle("hidden"); if (!input.classList.contains("hidden")) input.focus();
    } }, "✎ Comment");
    const saveBtn = el("button", { class: "act", onclick: (e) => { e.preventDefault(); save(input.value.trim()); } }, "★ Save");
    toolbar = el("div", { class: "hl-toolbar", role: "toolbar", "aria-label": "Highlight" }, ...dots, noteBtn, input, saveBtn);
    // Keep the selection alive while interacting with the toolbar.
    toolbar.addEventListener("mousedown", (e) => { if (e.target !== input) e.preventDefault(); });
    document.body.append(toolbar);
    const w = toolbar.offsetWidth;
    const left = Math.max(8, Math.min(window.scrollX + rect.left + rect.width / 2 - w / 2, window.scrollX + document.documentElement.clientWidth - w - 8));
    const top = window.scrollY + rect.top - toolbar.offsetHeight - 10;
    toolbar.style.left = `${left}px`;
    toolbar.style.top = `${top < window.scrollY ? window.scrollY + rect.bottom + 10 : top}px`;
  }

  function onSelectEnd(e) {
    if (toolbar && toolbar.contains(e.target)) return;
    setTimeout(() => {
      const info = selectionInfo();
      if (info) show(info);
      else if (toolbar && !toolbar.contains(document.activeElement)) hide();
    }, 10);
  }

  document.addEventListener("mouseup", onSelectEnd);
  document.addEventListener("touchend", onSelectEnd);
  document.addEventListener("keyup", (e) => { if (e.key === "Escape") hide(); else if (e.shiftKey) onSelectEnd(e); });
  window.addEventListener("scroll", () => { if (toolbar && !current) hide(); }, { passive: true });

  PV.highlight = { hide };
})();
