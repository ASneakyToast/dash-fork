## Why

Memory is wired into dash's core. The worker looks memories up and learns new ones on every turn, `web.py` serves the memory routes, and the Memories tab is built into the page. There is no off switch: ACP's per-agent `memory: false` only keeps memories out of the prompt, and the worker still looks them up and stores new ones. Joel wants to turn memory off, swap it for another system, or let an agent's own harness own it. The plugin system is the place for that, but plugins cannot yet act before or after a turn.

## What Changes

- Plugin API 2 adds two hooks: `before_turn` (return context for the system message and items to show) and `after_turn` (act on the saved reply and report how many things were stored). dash keeps loading API 1 plugins.
- A new plugin, `matts-memory`, takes over everything memory-shaped: recall before a reply, learning after it, the memory routes and the Memories tab. It reuses the existing memory code (providers, store methods, tables), so behavior with the plugin on is unchanged.
- The worker no longer calls recall and learning itself. It calls the hooks, and still emits the `memories` event and the `recalled` and `remembered` activity entries, so the web UI and dash-brood need no change.
- Core drops its `/api/memories` routes and the built-in Memories tab.
- Memory is off when the plugin is disabled (`DASH_PLUGINS_DISABLED=matts-memory`) or not installed.
- **BREAKING**: the memory API moves from `/api/memories` to `/api/plugins/matts-memory/memories`. Only dash's own page calls it.
- The fork's image build installs the plugin, so a deployment keeps memory by default.

## Capabilities

### New Capabilities

- `plugins`: what a plugin can do around a chat turn. This change specifies only the turn hooks and the API versions it needs. The rest of the plugin system (routes, tabs, themes, activity) is not specified yet.

### Modified Capabilities

- `memories`: memory becomes optional and moves behind the plugin. Existing requirements are unchanged. New requirements cover turning it off and the new API path.

## Impact

- Code: `src/dash/plugins.py` (API 2, hook dispatch), `src/dash/worker.py` (call hooks instead of recall and learn), `src/dash/web.py` (drop memory routes, stop taking an embedder), `src/dash/static/{app.js,index.html}` (drop the Memories tab), and a new package `matts-memory` for the plugin.
- Image: the Dockerfile and `joel-dash-build.yml` install the plugin next to dash-brood.
- Operators: no new environment variables. `EMBED_MODEL`, `EXTRACT_MODEL`, `MEMORY_*` keep their names. Memory tables stay in the core migration, so Postgres still needs pgvector even with memory off.
- Fork-only. The plugin system is not upstream, and this change edits memory code that Matt owns, so it is not meant for `whatever/dash`.
- Order: do this after ACP merges into `joel-dash/main`, or on top of it. Both change `worker.py` around the same lines.
