# Agents

dash can talk to more than one agent. Each conversation is bound to one agent when it is made, and the picker next to **+ New** chooses which. There are two kinds:

| Kind | How dash reaches it | What dash keeps |
|---|---|---|
| `openai` | An OpenAI-compatible `/chat/completions` API, such as hermes's API server. | dash owns the history and sends all of it each turn. |
| `acp` | The [Agent Client Protocol](https://agentclientprotocol.com): JSON-RPC over stdio (dash starts the process) or over a WebSocket (the agent runs somewhere else). | The agent owns the session. dash stores its session id on the conversation and sends only the new message. |

With no settings, dash has one agent, `hermes`, of kind `openai`, built from `HERMES_BASE_URL`, `HERMES_API_KEY` and `HERMES_MODEL`. That is how dash worked before agents existed.

## Settings

`DASH_AGENTS` is a JSON object from agent name to its settings. `DASH_DEFAULT_AGENT` names the one new conversations use, else the first. `dash agents` prints what dash read, without starting anything.

```json
{
  "hermes": {"title": "Hermes", "url": "ws://hermes-acp.hermes.svc:8765/", "token_env": "HERMES_ACP_TOKEN"},
  "claude": {"title": "Claude Code", "command": ["claude-agent-acp"], "pass_env": ["ANTHROPIC_API_KEY"], "cwd": "/work"},
  "planner-api": {"title": "Planner (API)"}
}
```

| Key | Meaning |
|---|---|
| `title` | The name in the UI. Defaults to the agent name. |
| `command` | ACP over stdio: the program and its arguments. dash starts it on the first turn and keeps it running. |
| `url` | ACP over a WebSocket. Set `command` or `url`, not both. |
| `token_env`, `headers` | For `url`: sent as `Authorization: Bearer <value of that env var>`, and extra handshake headers. |
| `env`, `pass_env` | For `command`: the process gets only `HOME`, `PATH`, `SHELL`, `TERM`, `USER` and `LOGNAME`. `pass_env` copies more from dash's environment; `env` sets fixed values. |
| `cwd` | The working directory sent with each session (and the process's directory for `command`). Defaults to dash's. |
| `memory` | `true` by default: dash's recalled memories go in front of the message. Set `false` for an agent with its own memory. |
| `base_url`, `api_key_env`, `model` | For `openai`: override the `HERMES_*` settings. |

## Sessions

The first turn of a conversation opens a session on the agent with `session/new` and stores its id. Later turns reuse it. After a restart of the worker or the agent, dash restores the session with `session/load` (it ignores the history the agent replays) or `session/resume`, whichever the agent supports. If the agent can't restore it, dash opens a new session and sends the last 20 messages as text before the new one, so the conversation carries on.

One connection per agent serves every session. Jobs of different conversations run side by side, up to `DASH_WORKER_CONCURRENCY`; jobs of one conversation run in order, because an ACP session takes one prompt at a time. The worker renews its claim on running jobs every minute, so a long turn is never handed to a second worker.

## What the browser sees

The job's event stream (`GET /api/jobs/<id>/events`) carries more than text:

| `kind` | Fields | Meaning |
|---|---|---|
| `delta` | `text` | A piece of the reply. |
| `thought` | `text` | A piece of the agent's reasoning. |
| `tool` | `tool`: `id`, `title`, `kind`, `status`, `detail`, `paths` | The latest state of one tool call. |
| `plan` | `entries`: `content`, `status`, `priority` | The agent's whole current plan. |
| `permission` | `id`, `title`, `options`: `id`, `name`, `kind` | The agent asks before running a tool. |
| `permission_done` | `id`, `option_id` | The question was answered. `null` means not allowed. |
| `done` | `message_id`, `stop` | The reply is saved. |

The saved assistant message keeps the tool calls, plan, thoughts, permission answers and stop reason in `details`, so a reload shows them.

Answers go back through two endpoints. The worker reads them from the Redis stream `dash:control:<job>`.

- `POST /api/jobs/<id>/permissions/<question id>` with `{"option_id": "…"}`. Any open tab or device can answer; the conversation list marks a job that waits with **needs you**.
- `POST /api/jobs/<id>/cancel`. An ACP agent gets `session/cancel` and ends the turn itself; for an `openai` agent dash stops reading. Either way the partial reply is saved with `stop: "cancelled"` and no memories are extracted from it.

A question nobody answers waits until the agent gives up (hermes denies after `approvals.timeout`, 300 s by default).

## Agents to try

| Agent | Command |
|---|---|
| hermes | `hermes acp` (install with the `[acp]` extra). Stdio only, so to reach it in another container put a stdio-to-WebSocket bridge such as `websocketd --port 8765 hermes acp` in front of it. |
| Claude Code | `claude-agent-acp` from npm (`@zed-industries/claude-agent-acp`). |
| Gemini CLI | `gemini --acp` (older releases: `--experimental-acp`) |

dash advertises no file system or terminal to the agent: agents use their own tools where they run. An agent that runs commands runs them in its own container, as whoever it runs as, so put it where that is safe. A WebSocket bridge has no auth of its own; keep it off public networks and set `token_env` if the bridge checks a token.
