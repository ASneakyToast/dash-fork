## Context

Memory touches four places in core: `Worker.handle` (recall before the agent call, learning after `done`), `web.py` (the `/api/memories` routes, which need an embedder), `static/{index.html,app.js}` (the Memories tab) and `__init__.py` (building the embedder and extractor for both processes). The plugin system (`docs/plugins.md`) offers routes, a tab, a lifespan and an `on_activity` listener. `on_activity` is a notification after the fact, cut off after 5 seconds, and it cannot change what the agent receives. See `proposal.md` for why.

## Goals / Non-Goals

**Goals**
- Memory off with a setting that already exists (`DASH_PLUGINS_DISABLED`), and replaceable by another plugin.
- Identical behavior with the plugin on: the same recall, the same learning, the same events and activity.

**Non-Goals**
- Plugin-owned database tables and migrations. The `memories` table and pgvector stay in core migration 0001.
- Moving the memory code (`dash.memory`, the `Store` memory methods) out of core.
- Making learning asynchronous.
- A baseline spec for the rest of the plugin system.

## Decisions

**New hooks, not `on_activity`.** Recall has to change the prompt, so a plugin must run before the agent call and hand something back. `before_turn` returns context text and display items; `after_turn` runs once the reply is saved and returns a count. Alternative: let a plugin subscribe to a `started` activity and write context somewhere the worker reads. That is a hook with extra steps and a race.

**Wrap first, move later.** The plugin imports `dash.memory` (providers, prompts, thresholds) and the `Store` memory methods and owns only *when* they run, the routes and the tab. Diff against upstream stays small, so Matt's changes to memory internals still merge. Alternative: move all memory code into the plugin. Cleaner boundary, but every upstream memory change would then conflict.

**Learning stays inside the job.** `after_turn` is awaited before the job is acknowledged, as `remember` is today. The next turn in the conversation then sees what this one learned. The cost, which exists today too, is that the worker slot is held for the length of one extraction call. Alternative: a background task, which frees the slot but lets turn N+1 start recall before turn N's facts exist.

**The worker keeps the events.** It turns hook results into the `memories` job event and the `recalled` and `remembered` activity entries. The chat UI and dash-brood already read those, so neither changes, and every plugin's `on_activity` still hears them.

**Off is "plugin disabled".** `DASH_PLUGINS_DISABLED=matts-memory` already skips a plugin without importing it. No new flag. Alternative: a `MEMORY_ENABLED` setting in core. Smaller to write today, but it would be a second off switch next to the plugin one and could not be swapped.

**Settings keep their names.** The plugin reads `EMBED_MODEL`, `EXTRACT_MODEL` and `MEMORY_*` through `Settings.from_env()` and builds its own embedder and extractor in `lifespan(ctx)`, which runs in the API and the worker. No ops change.

**API 2, and dash accepts 1 and 2.** `check()` today refuses any plugin whose `api` differs from dash's. It changes to accept a set, so dash-brood (API 1) keeps loading.

**Timeouts.** 10 seconds for `before_turn` (an embedding call and a vector search take well under one second) and 60 for `after_turn` (an LLM call plus an embedding per fact). Both are well above normal and well below the 900-second chat timeout.

**Name and place.** The plugin is `matts-memory`: its URLs already say `/plugins/`, so no `-plugin` suffix. It lives in `plugins/matts-memory`, which needs `COPY plugins ./plugins` in the Dockerfile and a second path in the build workflow's `PLUGINS` argument. Putting it in `examples/` next to dash-brood would avoid the Dockerfile edit, at the cost of calling an essential component an example.

## Risks / Trade-offs

- [Fork divergence: `worker.py`, `web.py` and `app.js` lose their memory code] → The memory modules stay in core, so only call sites move.
- [ACP edits the same part of `worker.py`] → Do this change after ACP merges, or on top of it.
- [A slow before-turn hook delays every reply] → The 10-second cap, and the plugin does one embedding and one query. Several slow plugins add up.
- [Memory off still needs pgvector, because the table is in the core migration] → Accepted for now; see the open questions.
- [`/api/memories` disappears] → Only dash's own page called it. Nothing external is known to.
- [hermes keeps its own memory (`MEMORY.md`, `USER.md`), so with the plugin on there are two] → Disable the plugin for agents that own their memory. That is the point of the switch.

## Interaction with ACP

ACP gives each agent a `memory` setting. Today it only drops memories from the prompt. Once hooks exist, turn hooks receive the agent and its settings, and the memory plugin does nothing for an agent with `memory: false`: no lookup, no learning. That makes the setting a real off switch per agent. It is the last task, because ACP is not on `joel-dash/main` yet.

## Migration Plan

Build the image with the plugin and deploy it. Memories already in Postgres keep working. To turn memory off, set `DASH_PLUGINS_DISABLED=matts-memory` in the dash config and roll the pods. The stored memories stay in the table. Roll back by pinning the previous image; the table is untouched either way.

## Open Questions

- Should plugins own tables and migrations, so the memory tables leave the core migration and memory off means no pgvector?
- Is a hook enough for a harness-owned memory such as mem0, or does that work as tools the agent calls, with no hook at all? If it is tools, the answer is simply that no memory plugin is installed.
- Should the hooks go upstream to Matt as a plugin-API proposal on their own, before the memory move?
