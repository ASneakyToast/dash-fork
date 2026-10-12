import { createTheme } from "./theme.js";

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

const state = {
  conversation: null,
  conversations: [],
  config: {},
  agents: { default: null, agents: [] },
  job: null,
  source: null,
  sending: false,
};
const touch = matchMedia("(pointer: coarse)");

$("#menu").addEventListener("click", () => {
  const open = $("aside").classList.toggle("open");
  $("#menu").setAttribute("aria-expanded", String(open));
});

function closeMenu() {
  $("aside").classList.remove("open");
  $("#menu").setAttribute("aria-expanded", "false");
}

// Tabs
const tabHooks = {};

function showTab(name) {
  document.querySelectorAll("nav button, .tab").forEach((n) => n.classList.remove("active"));
  document.querySelector(`nav button[data-tab="${name}"]`).classList.add("active");
  closeMenu();
  $(`#tab-${name}`).classList.add("active");
  tabHooks[name]?.();
}

function bindTab(btn) {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
}

document.querySelectorAll("nav button").forEach(bindTab);
tabHooks.memories = () => loadMemories();
tabHooks.apps = () => {
  loadApps();
  loadGitHub();
  loadPluginList();
};

// Agents and conversations
const IDLE = new Set(["done", "failed"]);

function agentTitle(name) {
  return state.agents.agents.find((a) => a.name === name)?.title ?? name ?? "";
}

async function loadAgents() {
  state.agents = await api("/api/agents");
  $("#agent").replaceChildren(
    ...state.agents.agents.map((a) =>
      el("option", { value: a.name, textContent: a.title, selected: a.name === state.agents.default }),
    ),
  );
  $("#agent").hidden = state.agents.agents.length < 2;
}

function jobState(conversationId) {
  const last = feed.events.findLast((e) => e.conversation_id === conversationId);
  if (!last || IDLE.has(last.kind)) return null;
  return { jobId: last.job_id, status: last.kind === "waiting" ? "waiting" : "running" };
}

function markStatus() {
  document.querySelectorAll("#conversations li").forEach((li) => {
    const job = jobState(li.dataset.id);
    if (job) li.dataset.status = job.status;
    else delete li.dataset.status;
  });
}

async function loadConversations() {
  const list = await api("/api/conversations");
  state.conversations = list;
  $("#conversations").replaceChildren(
    ...list.map((c) => {
      const li = el("li", { title: c.title }, c.title, el("span", { className: "meta", textContent: agentTitle(c.agent) }));
      li.dataset.id = c.id;
      if (c.id === state.conversation) li.classList.add("active");
      li.addEventListener("click", () => openConversation(c.id));
      return li;
    }),
  );
  markStatus();
  return list;
}

function bubble(role, text) {
  const node = el("div", { className: `msg ${role}`, textContent: text });
  $("#messages").append(node);
  node.scrollIntoView({ block: "end" });
  return node;
}

function turnView(agent, text = "…") {
  const steps = el("div", { className: "steps" });
  const node = el("div", { className: "msg assistant", textContent: text });
  $("#messages").append(el("div", { className: "agent-name", textContent: agentTitle(agent) }), steps, node);
  node.scrollIntoView({ block: "end" });
  return { steps, node, tools: new Map(), thought: null, plan: null };
}

function showTool(view, tool) {
  let item = view.tools.get(tool.id);
  if (!item) {
    item = el("details", { className: "step tool" }, el("summary"), el("pre"));
    view.tools.set(tool.id, item);
    view.steps.append(item);
  }
  item.dataset.status = tool.status;
  const where = tool.paths?.length ? ` · ${tool.paths.join(", ")}` : "";
  item.querySelector("summary").textContent = `${tool.title}${where}`;
  item.querySelector("pre").textContent = tool.detail || "";
  item.querySelector("pre").hidden = !tool.detail;
}

function showThought(view, text) {
  if (!view.thought) {
    view.thought = el("details", { className: "step thought" }, el("summary", { textContent: "Thinking" }), el("pre"));
    view.steps.prepend(view.thought);
  }
  view.thought.querySelector("pre").textContent += text;
}

function showPlan(view, entries) {
  if (!view.plan) {
    view.plan = el("details", { className: "step plan", open: true }, el("summary", { textContent: "Plan" }), el("ul"));
    view.steps.prepend(view.plan);
  }
  view.plan.querySelector("ul").replaceChildren(
    ...entries.map((e) => {
      const li = el("li", { textContent: e.content });
      li.dataset.status = e.status;
      return li;
    }),
  );
}

function showPermission(view, jobId, ask) {
  const choices = ask.options.map((o) => {
    const button = el("button", { type: "button", textContent: o.name });
    button.addEventListener("click", () =>
      api(`/api/jobs/${jobId}/permissions/${ask.id}`, { method: "POST", body: { option_id: o.id } }),
    );
    return button;
  });
  const box = el("div", { className: "permission" }, el("div", { textContent: ask.title }), el("div", { className: "choices" }, ...choices));
  box.dataset.id = ask.id;
  box.dataset.options = JSON.stringify(ask.options);
  view.node.before(box);
  box.scrollIntoView({ block: "end" });
}

function answerPermission(ev) {
  const box = document.querySelector(`.permission[data-id="${ev.id}"]`);
  if (!box) return;
  const chosen = JSON.parse(box.dataset.options).find((o) => o.id === ev.option_id);
  box.dataset.answered = "";
  box.append(el("div", { className: "meta", textContent: chosen ? `Answered: ${chosen.name}` : "Not allowed" }));
}

function renderMessage(m) {
  if (m.role !== "assistant") return bubble(m.role, m.content);
  const d = m.details || {};
  const view = turnView(d.agent, m.content || (d.stop === "cancelled" ? "(stopped)" : ""));
  if (d.thoughts) showThought(view, d.thoughts);
  if (d.plan) showPlan(view, d.plan);
  (d.tools || []).forEach((t) => showTool(view, t));
  (d.permissions || []).forEach((ask) => {
    showPermission(view, null, ask);
    answerPermission(ask);
  });
  if (d.stop === "cancelled" && m.content) view.node.append(el("div", { className: "meta", textContent: "(stopped)" }));
  return view.node;
}

function current() {
  return state.conversations.find((c) => c.id === state.conversation);
}

async function openConversation(id) {
  state.source?.close();
  state.conversation = id;
  localStorage.setItem("conversation", id);
  closeMenu();
  const messages = await api(`/api/conversations/${id}/messages`);
  $("#messages").replaceChildren();
  messages.forEach(renderMessage);
  await loadConversations();
  $("#input").placeholder = `Message ${agentTitle(current()?.agent) || "the agent"}…`;
  attach();
}

function attach() {
  const job = state.conversation && jobState(state.conversation);
  if (job && !state.sending && state.job !== job.jobId) follow(job.jobId, turnView(current()?.agent));
}

let attachTimer;
function attachSoon() {
  clearTimeout(attachTimer);
  attachTimer = setTimeout(attach, 300);
}

$("#new-chat").addEventListener("click", async () => {
  const c = await api("/api/conversations", { method: "POST", body: { agent: $("#agent").value || null } });
  await openConversation(c.id);
  $("#input").focus();
});

// Sending and streaming
function finish(source) {
  source.close();
  if (state.source === source) {
    state.source = null;
    state.job = null;
    $("#stop").hidden = true;
  }
}

function follow(jobId, view) {
  state.source?.close();
  const { node } = view;
  return new Promise((resolve) => {
    const source = new EventSource(`/api/jobs/${jobId}/events`);
    Object.assign(state, { source, job: jobId });
    $("#stop").hidden = false;
    let text = "";
    source.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.kind === "delta") {
        text += ev.text;
        node.textContent = text;
        node.scrollIntoView({ block: "end" });
      } else if (ev.kind === "thought") {
        showThought(view, ev.text);
      } else if (ev.kind === "tool") {
        showTool(view, ev.tool);
      } else if (ev.kind === "plan") {
        showPlan(view, ev.entries);
      } else if (ev.kind === "permission") {
        showPermission(view, jobId, ev);
      } else if (ev.kind === "permission_done") {
        answerPermission(ev);
      } else if (ev.kind === "memories") {
        node.after(el("div", { className: "recalled", textContent: `Recalled ${ev.items.length} memories` }));
      } else if (ev.kind === "done" || ev.kind === "error") {
        if (ev.kind === "error") {
          node.classList.add("error");
          node.textContent = text + `\n\n${ev.message}`;
        } else if (ev.stop === "cancelled") {
          node.textContent = text || "(stopped)";
        }
        finish(source);
        resolve();
      }
    };
  });
}

$("#stop").addEventListener("click", async () => {
  if (state.job) await api(`/api/jobs/${state.job}/cancel`, { method: "POST" });
});

$("#composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const content = $("#input").value.trim();
  if (!content) return;
  if (!state.conversation) {
    const c = await api("/api/conversations", { method: "POST", body: { agent: $("#agent").value || null } });
    state.conversation = c.id;
    await loadConversations();
  }
  $("#input").value = "";
  bubble("user", content);
  const view = turnView(current()?.agent);
  state.sending = true;
  try {
    const { job_id } = await api(`/api/conversations/${state.conversation}/messages`, {
      method: "POST",
      body: { content },
    });
    loadConversations();
    const done = follow(job_id, view);
    state.sending = false;
    await done;
  } catch (err) {
    view.node.classList.add("error");
    view.node.textContent = String(err);
  } finally {
    state.sending = false;
  }
});

$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !touch.matches) {
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

// Plugins
const narrowScreen = matchMedia("(max-width: 900px)");
const feed = { events: [], listeners: new Set() };
const FEED_LIMIT = 200;
let plugins = [];

function startFeed() {
  const source = new EventSource("/api/activity");
  source.onmessage = (e) => {
    const event = JSON.parse(e.data);
    feed.events = [...feed.events, event].slice(-FEED_LIMIT);
    markStatus();
    if (event.conversation_id === state.conversation) attachSoon();
    feed.listeners.forEach((fn) => fn(event));
  };
}

function guarded(plugin, fn) {
  return (...args) => {
    try {
      return fn(...args);
    } catch (err) {
      console.error(`dash plugin ${plugin.name}:`, err);
    }
  };
}

function hostFor(plugin) {
  const guard = (fn) => guarded(plugin, fn);
  const id = (name) => `${plugin.name}-${name}`;
  const addTab = ({ id: name, title, mount }) => {
    const button = el("button", { textContent: title });
    button.dataset.tab = id(name);
    const root = el("section", { id: `tab-${id(name)}`, className: "tab" });
    let mounted = false;
    tabHooks[id(name)] = () => {
      if (!mounted) {
        mounted = true;
        guard(mount)(root);
      }
    };
    bindTab(button);
    $("nav").append(button);
    $("main").append(root);
    return { root, button };
  };
  return {
    api,
    el,
    config: state.config,
    plugin: {
      name: plugin.name,
      version: plugin.version,
      api: (path, opts) => api(`/api/plugins/${plugin.name}${path}`, opts),
    },
    addTab: (options) => addTab(options).root,
    addDock({ id: name, title, mount }) {
      const root = el("section", { id: `dock-${id(name)}`, className: "dock-panel" });
      root.setAttribute("aria-label", title);
      const { root: tab, button } = addTab({ id: `${name}-dock`, title, mount: () => {} });
      tab.classList.add("tab-dock");
      const place = () => {
        const narrow = narrowScreen.matches;
        (narrow ? tab : $("#dock")).append(root);
        button.hidden = !narrow;
        $("#dock").hidden = narrow || !$("#dock").children.length;
        if (!narrow && button.classList.contains("active")) showTab("chat");
      };
      narrowScreen.addEventListener("change", place);
      place();
      guard(mount)(root);
      return root;
    },
    onActivity(fn) {
      const handler = guard(fn);
      feed.events.forEach(handler);
      feed.listeners.add(handler);
      return () => feed.listeners.delete(handler);
    },
    async openConversation(conversationId) {
      showTab("chat");
      await openConversation(conversationId);
    },
    conversations: () => api("/api/conversations"),
    theme: {
      ...theme,
      onChange: (fn) => theme.onChange(guard(fn)),
    },
  };
}

async function loadPlugin(plugin) {
  try {
    if (plugin.style) document.head.append(el("link", { rel: "stylesheet", href: plugin.style }));
    if (plugin.script) await (await import(plugin.script)).default(hostFor(plugin));
  } catch (err) {
    plugin.status = "error";
    plugin.error = String(err);
    console.error(`dash plugin ${plugin.name} failed to start:`, err);
  }
}

async function loadPlugins() {
  plugins = (await api("/api/plugins")).plugins;
  await Promise.all(plugins.filter((p) => p.status === "ok").map(loadPlugin));
  loadPluginList();
}

function loadPluginList() {
  $("#plugin-list").replaceChildren(
    ...plugins.map((p) => {
      const meta = p.status === "ok" ? `v${p.version}` : p.error;
      const name = el("div", {}, p.name, el("div", { className: `meta${p.status === "ok" ? "" : " error-text"}`, textContent: meta }));
      return el("li", {}, name, el("span", { className: "meta", textContent: p.status }));
    }),
  );
  if (!plugins.length) $("#plugin-list").append(el("li", { textContent: "No plugins installed." }));
}

function option(value, text) {
  return el("option", { value, textContent: text });
}

function renderAppearance() {
  const choice = theme.current();
  const wanted = theme.themes().find((t) => t.name === choice.theme);
  const modes = wanted && wanted.modes.length === 1 ? wanted.modes : ["auto", "light", "dark"];
  $("#theme-pick").replaceChildren(
    option("default", "Default"),
    ...theme.themes().map((t) => option(t.name, t.source && t.source !== "dash" ? `${t.title} (${t.source})` : t.title)),
  );
  $("#theme-pick").value = choice.theme;
  $("#mode-pick").replaceChildren(...modes.map((m) => option(m, m === "auto" ? "Match system" : m)));
  $("#mode-pick").value = choice.mode;
  $("#mode-pick").disabled = modes.length === 1;
  const warnings = [
    ...(wanted?.warnings ?? []).map((w) => `${wanted.title}: ${w}`),
    ...(theme.overrides()?.warnings ?? []).map((w) => `Your overrides: ${w}`),
  ];
  $("#theme-warnings").replaceChildren(...warnings.map((w) => el("li", { textContent: w })));
}

$("#appearance").addEventListener("change", () => {
  theme.select({ theme: $("#theme-pick").value, mode: $("#mode-pick").value });
  renderAppearance();
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
const theme = createTheme({
  manifest: await api("/api/theme"),
  root: document.documentElement,
  dark: matchMedia("(prefers-color-scheme: dark)"),
  style: () => getComputedStyle(document.documentElement),
  storage: localStorage,
});
renderAppearance();
await loadAgents();
const list = await loadConversations();
startFeed();
const last = localStorage.getItem("conversation");
if (last && list.some((c) => c.id === last)) openConversation(last);
if (location.hash === "#apps") document.querySelector('nav button[data-tab="apps"]').click();
pollQueue();
setInterval(pollQueue, 5000);
loadPlugins();
