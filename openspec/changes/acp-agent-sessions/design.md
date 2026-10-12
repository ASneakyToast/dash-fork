## Context

A turn is a job on `dash:jobs`. The worker builds the reply and writes events to `dash:events:<job>`, which the API replays to the browser over SSE (`openspec/specs/chat/spec.md`). Before this change the worker held one hermes client and sent the whole history each turn. See `proposal.md` for why that changes.

ACP is JSON-RPC 2.0 between a client (dash) and an agent: `initialize`, `session/new|load|resume`, `session/prompt` with `session/update` notifications streaming back, `session/cancel`, and agent-to-client requests such as `session/request_permission`. hermes's `hermes acp` speaks it over stdio only, and hermes's data (SQLite `state.db`, `.env`, skills) is on a ReadWriteOnce volume in its own pod.

## Goals / Non-Goals

**Goals:**
- Any ACP agent behind one interface, with the old hermes path as one more agent.
- Turn-time interaction (permission questions, Stop) from any tab or device.
- No change at all for an install that sets none of the new variables.

**Non-Goals:**
- Giving agents dash's file system or a terminal (ACP client capabilities `fs` and `terminal`). Agents use their own tools where they run.
- Listing or importing sessions dash did not start (`session/list`).
- Session modes, model switching, slash commands, images or other non-text prompt blocks.
- Authentication on dash itself or on the WebSocket bridge.

## Decisions

**The official Python SDK, `agent-client-protocol` 0.12.x, with the `http` extra.** It handles framing, the stdio subprocess and a WebSocket transport, and its schema models track the spec. Pinned below 0.13 because 1.0 is in release candidates. Alternative: hand-rolled JSON-RPC, which would be small for stdio but would have to follow every schema change.

**One `Agent` interface, two implementations.** An agent runs a `Turn` (conversation id, stored session id, history, memory context, an `ask` callback) and yields updates: text, thought, tool, plan, a new session id, stop. `ChatAgent` wraps the existing hermes client; `AcpAgent` speaks ACP. The worker never branches on the kind. A `Catalog` of specs (no connections) serves the API, so `dash serve` never starts agent processes.

**One connection per agent, shared by its sessions.** Updates are routed to the waiting turn by session id. A stdio process is started on first use and restarted when it has exited; a connection error resets the connection and the next turn reconnects. Alternative: one process per conversation, which isolates sessions but costs a process each and loses nothing ACP doesn't already give.

**Ordering by conversation, not by agent.** ACP allows one prompt at a time per session, so jobs of a conversation take a per-conversation lock; different conversations run side by side up to `DASH_WORKER_CONCURRENCY`. The worker renews its claim with `XCLAIM … JUSTID` every 60 s, so `XAUTOCLAIM`'s five-minute idle rule only fires for a dead worker.

**Answers travel on a per-job Redis stream, `dash:control:<job>`.** The API appends `cancel` or `permission`; the job's watcher task reads from the start, so a cancel sent before the job starts is still seen. The same mechanism serves both, and any API process can take the answer. Alternatives: pub/sub, which drops messages sent while nothing listens, or polling a key.

**Stop: ask, then cut.** An ACP agent gets `session/cancel` and 15 s to end its turn (its `stop_reason` is then `cancelled`); after that, or at once for a chat agent or a turn with no session yet, the worker cancels the reader task. When a turn is abandoned the client also waits (up to 10 s) for the agent's prompt to finish before releasing the session's route, so late updates from the old prompt can't leak into the next turn on that session.

**Restoring sessions.** `session/load` if the agent advertises `loadSession` (the agent replays history as updates; dash drops them because no route is registered yet), else `session/resume`, else a new session whose first prompt carries the last 20 messages. Alternative: always send the history, which would duplicate it for agents that keep their own.

**Memories as a prompt block, switchable per agent.** ACP has no system message, so recalled memories go as a text block before the user message. `memory: false` turns it off for agents with their own memory (hermes).

**Storage.** `conversations.agent` and `conversations.session_id` are nullable (old rows mean the default agent, no session). `messages.details` is JSONB defaulting to `{}`, keeping the tool calls, plan, thoughts, permission answers and stop reason. Text stays in `content`, so memory extraction and the OpenAI path are unchanged.

**UI from the activity feed.** The conversation list marks a conversation running or waiting from its last activity entry, and opening one re-attaches to its running job, whose event stream replays from the start (including an open permission question). Colors come from two new tokens, `dash.color.warning` and `dash.color.success`, rather than fixed values.

## Risks / Trade-offs

- [An ACP agent runs commands with the rights of wherever it runs] → Run agents in their own containers. hermes asks before commands it deems dangerous, and dash shows those questions. Narrow hermes's `platform_toolsets.acp` if that is not enough.
- [A WebSocket bridge such as `websocketd` has no auth] → Keep it ClusterIP and limit it to the worker with a NetworkPolicy (jlithgow-ops `docs/plans/dash-acp.md`). `token_env` exists for a bridge that checks a token.
- [Memories sent every turn grow the agent's session history] → `memory: false` per agent.
- [The SDK's unstable protocol features are on (`session/resume`)] → Only used when the agent advertises them; the pin keeps the schema fixed until bumped on purpose.
- [A question nobody answers holds a worker slot until the agent gives up] → hermes denies after `approvals.timeout` (300 s); Stop denies at once.
- [Two workers would each start their own stdio agents] → Sessions survive through `session/load`; the deployment keeps one worker for now.

## Migration Plan

Deploy the image and let `dash migrate` run 0003 (additive and nullable, so the old image still runs against the new schema). Then set `DASH_AGENTS` and restart the API and worker. Roll back by unsetting `DASH_AGENTS`: conversations bound to an agent that is no longer configured end their jobs with `Unknown agent`, so start new conversations on the default. The 0003 downgrade drops the three columns and the details in them.

## Open Questions

- Should the stored permission answers record who answered once dash has users? There are none today.
- Should `dash` ship its own token-checking WebSocket bridge to replace `websocketd`? Deployment detail; the client already sends `token_env`.
