const $ = (sel) => document.querySelector(sel);
const el = (tag, props = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
};

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body && JSON.stringify(opts.body),
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

const state = { conversation: null, config: {} };

// Tabs
document.querySelectorAll("nav button").forEach((btn) =>
  btn.addEventListener("click", () => {
    setConversationsOpen(false);
    document.querySelectorAll("nav button, .tab").forEach((n) => n.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "memories") loadMemories();
    if (btn.dataset.tab === "apps") {
      loadApps();
      loadGitHub();
    }
  }),
);

// Conversations
function setConversationsOpen(open) {
  $("aside").classList.toggle("open", open);
  $("#toggle-conversations").setAttribute("aria-expanded", String(open));
}

$("#toggle-conversations").addEventListener("click", () =>
  setConversationsOpen(!$("aside").classList.contains("open")),
);

async function loadConversations() {
  const list = await api("/api/conversations");
  $("#conversations").replaceChildren(
    ...list.map((c) => {
      const li = el("li", { textContent: c.title, title: c.title });
      if (c.id === state.conversation) li.classList.add("active");
      li.addEventListener("click", () => openConversation(c.id));
      return li;
    }),
  );
  return list;
}

function bubble(role, text) {
  const node = el("div", { className: `msg ${role}`, textContent: text });
  $("#messages").append(node);
  node.scrollIntoView({ block: "end" });
  return node;
}

async function openConversation(id) {
  state.conversation = id;
  localStorage.setItem("conversation", id);
  document.querySelector('nav button[data-tab="chat"]').click();
  const messages = await api(`/api/conversations/${id}/messages`);
  $("#messages").replaceChildren();
  messages.forEach((m) => bubble(m.role, m.content));
  loadConversations();
}

$("#new-chat").addEventListener("click", async () => {
  const c = await api("/api/conversations", { method: "POST" });
  await openConversation(c.id);
  $("#input").focus();
});

// Sending and streaming
function follow(jobId, node) {
  return new Promise((resolve) => {
    const source = new EventSource(`/api/jobs/${jobId}/events`);
    let text = "";
    source.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.kind === "delta") {
        text += ev.text;
        node.textContent = text;
        node.scrollIntoView({ block: "end" });
      } else if (ev.kind === "memories") {
        node.after(el("div", { className: "recalled", textContent: `Recalled ${ev.items.length} memories` }));
      } else if (ev.kind === "done" || ev.kind === "error") {
        if (ev.kind === "error") {
          node.classList.add("error");
          node.textContent = text + `\n\n${ev.message}`;
        }
        source.close();
        resolve();
      }
    };
  });
}

$("#composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const content = $("#input").value.trim();
  if (!content) return;
  if (!state.conversation) {
    const c = await api("/api/conversations", { method: "POST" });
    state.conversation = c.id;
  }
  $("#input").value = "";
  bubble("user", content);
  const node = bubble("assistant", "…");
  try {
    const { job_id } = await api(`/api/conversations/${state.conversation}/messages`, {
      method: "POST",
      body: { content },
    });
    loadConversations();
    await follow(job_id, node);
  } catch (err) {
    node.classList.add("error");
    node.textContent = String(err);
  }
});

$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("#composer").requestSubmit();
  }
});

// Memories
async function loadMemories(q = "") {
  const items = await api(`/api/memories?q=${encodeURIComponent(q)}`);
  $("#memory-list").replaceChildren(
    ...items.map((m) => {
      const del = el("button", { textContent: "Delete" });
      del.addEventListener("click", async () => {
        await api(`/api/memories/${m.id}`, { method: "DELETE" });
        loadMemories($("#memory-q").value);
      });
      const meta = [m.source, m.created_at?.slice(0, 10), m.distance != null && `distance ${m.distance}`]
        .filter(Boolean)
        .join(" · ");
      return el("li", {}, el("div", {}, m.content, el("div", { className: "meta", textContent: meta })), del);
    }),
  );
}

$("#memory-search").addEventListener("submit", (e) => {
  e.preventDefault();
  loadMemories($("#memory-q").value);
});

$("#memory-add").addEventListener("submit", async (e) => {
  e.preventDefault();
  const content = $("#memory-new").value.trim();
  if (!content) return;
  await api("/api/memories", { method: "POST", body: { content } });
  $("#memory-new").value = "";
  loadMemories();
});

// Apps (Nango)
async function loadApps() {
  if (!state.config.nango) {
    $("#app-list").replaceChildren(el("li", { textContent: "Nango is not configured." }));
    return;
  }
  const { connections } = await api("/api/connections");
  $("#app-list").replaceChildren(
    ...connections.map((c) => {
      const del = el("button", { textContent: "Disconnect" });
      del.addEventListener("click", async () => {
        await api(`/api/connections/${c.provider_config_key}/${c.connection_id}`, { method: "DELETE" });
        loadApps();
      });
      const meta = `${c.provider} · ${c.connection_id} · since ${c.created?.slice(0, 10) ?? "?"}`;
      return el("li", {}, el("div", {}, c.provider_config_key, el("div", { className: "meta", textContent: meta })), del);
    }),
  );
  if (!connections.length) $("#app-list").append(el("li", { textContent: "No apps connected yet." }));
}

$("#connect").addEventListener("click", async () => {
  const { default: Nango } = await import("https://esm.sh/@nangohq/frontend@0.69");
  const { token } = await api("/api/connections/session", { method: "POST" });
  const nango = new Nango({ host: state.config.nango_host, connectSessionToken: token });
  nango.openConnectUI({
    baseURL: state.config.nango_connect_url || undefined,
    apiURL: state.config.nango_host,
    onEvent: (ev) => {
      if (ev.type === "connect" || ev.type === "close") loadApps();
    },
  });
});

// GitHub Apps
function renderGitHub({ apps }) {
  $("#github-list").replaceChildren(
    ...apps.map((a) => {
      const install = el("a", { href: `${a.html_url}/installations/new`, textContent: "Install" });
      const forget = el("button", { textContent: "Forget" });
      forget.addEventListener("click", async () => {
        await api(`/api/github/apps/${a.id}`, { method: "DELETE" });
        loadGitHub();
      });
      const accounts = a.installations.map((i) => i.account).join(", ") || "not installed";
      const meta = `${a.owner} · app ${a.app_id} · ${accounts}`;
      const name = el("a", { href: a.html_url, textContent: a.name, target: "_blank" });
      return el("li", {}, el("div", {}, name, el("div", { className: "meta", textContent: meta })), el("div", {}, install, " ", forget));
    }),
  );
  if (!apps.length) $("#github-list").append(el("li", { textContent: "No GitHub Apps yet." }));
}

async function loadGitHub() {
  renderGitHub(await api("/api/github"));
}

$("#github-sync").addEventListener("click", async () => {
  renderGitHub(await api("/api/github/sync", { method: "POST" }));
});

$("#github-create").addEventListener("submit", async (e) => {
  e.preventDefault();
  const org = $("#github-org").value.trim() || null;
  const { action, manifest } = await api("/api/github/manifest", { method: "POST", body: { org } });
  const form = el("form", { method: "post", action }, el("input", { type: "hidden", name: "manifest", value: manifest }));
  document.body.append(form);
  form.submit();
});

// Queue badge
async function pollQueue() {
  try {
    const q = await api("/api/queue");
    $("#queue").textContent = `${q.in_flight} running · ${q.waiting} waiting · ${q.workers} workers`;
  } catch {
    $("#queue").textContent = "queue offline";
  }
}

// Boot
state.config = await api("/api/config");
const list = await loadConversations();
const last = localStorage.getItem("conversation");
if (last && list.some((c) => c.id === last)) openConversation(last);
if (location.hash === "#apps") document.querySelector('nav button[data-tab="apps"]').click();
pollQueue();
setInterval(pollQueue, 5000);
