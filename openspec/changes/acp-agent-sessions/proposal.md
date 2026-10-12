## Why

dash talks only to hermes, through its OpenAI-compatible API: text in, text out, with dash resending the whole history each turn. That locks dash to one agent and hides what the agent does (its tools, its plan, the commands it wants to run). The Agent Client Protocol (ACP) is an open protocol that hermes already speaks (`hermes acp`), as do Claude Code and Gemini CLI. With ACP the agent owns the session, and dash can become the place to start, follow, answer and stop sessions on any of them.

## What Changes

- Add `DASH_AGENTS`, a JSON object of named agents, and `DASH_DEFAULT_AGENT`. An agent is either an OpenAI-compatible chat API (today's hermes path) or an ACP agent reached over stdio (dash starts the process) or a WebSocket. With neither variable set, dash has one `hermes` agent built from `HERMES_*`, which is exactly today's behavior.
- Each conversation is bound to one agent when it is made. `POST /api/conversations` takes an optional `agent`; `GET /api/agents` lists the agents. Conversations made before this change use the default agent.
- On an ACP agent, the first turn opens a session and dash stores its id. Later turns send only the new message. After a restart dash restores the session (`session/load`, else `session/resume`), or opens a new one carrying the last 20 messages.
- The job event stream gains `thought`, `tool`, `plan`, `permission` and `permission_done` events, and `done` carries the stop reason.
- Permission questions from the agent are answered through `POST /api/jobs/{job_id}/permissions/{id}`, and a turn is stopped through `POST /api/jobs/{job_id}/cancel`, from any tab or device.
- The stored assistant message keeps the agent's tool calls, plan, thoughts, permission answers and stop reason in `details`, returned by the messages endpoint.
- The worker runs up to `DASH_WORKER_CONCURRENCY` jobs at once (default 4), in order within a conversation, and renews its claim on running jobs so a long turn is not handed to a second worker.
- The activity feed gains `waiting`, `answered` and `cancelling`; `done` carries `stop`.
- The web UI gets an agent picker, renders tool calls, plan, thoughts and permission prompts, adds Stop, and marks conversations that are running or need you. Two design tokens are added for it: `dash.color.warning` and `dash.color.success`.
- `dash agents` prints the configured agents without starting any.
- Nothing is **BREAKING**: with no new settings, requests to hermes, the stored data and the event stream for a text reply are as before, apart from the extra `stop` field on `done`.

## Capabilities

### New Capabilities

- `agents`: configuring the agents dash can talk to, binding a conversation to one, running ACP sessions on it, and the permission questions and Stop that a running turn accepts.

### Modified Capabilities

- `chat`: conversations carry an agent; replies come from the conversation's agent instead of always from hermes; the job event stream and `done` event gain fields; assistant messages keep details; failure messages name the agent; jobs run side by side and the worker renews its claim on running jobs.

## Impact

- Code: new `src/dash/agents.py`; `worker.py`, `web.py`, `queue.py`, `db.py`, `config.py`, `__init__.py`; migration `0003_agents.py` (nullable `conversations.agent` and `conversations.session_id`, `messages.details` JSONB defaulting to `{}`); `static/app.js`, `index.html`, `style.css`; `tokens.json` and `themes/high-contrast.json`.
- Dependency: `agent-client-protocol[http]` 0.12.x (adds `websockets` and `httpx[http2]`).
- Tests: `tests/test_agents.py` and new worker and web tests run against a real ACP agent over stdio (`tests/acp_agent.py`).
- Docs: `docs/agents.md` (new), `README.md`, `docs/plugins.md` (activity kinds), `docs/theming.md` (tokens).
- Operators: an ACP agent runs its tools where it runs, and a WebSocket bridge to it has no auth of its own. The deployment plan (hermes behind a `websocketd` sidecar, locked down with a NetworkPolicy) is jlithgow-ops `docs/plans/dash-acp.md`.
- Code lives on the fork's `joel-dash/acp` branch, on `joel-dash/main`. This is fork-only; whether it goes to `whatever/dash` is open.
