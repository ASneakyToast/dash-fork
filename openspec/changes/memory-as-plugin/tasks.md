## 1. Plugin API 2 in core

- [ ] 1.1 Accept plugin API 1 and 2 and refuse others. Verify: tests load an API 1 and an API 2 plugin and refuse API 3 with a reason in the Apps tab data.
- [ ] 1.2 Add `before_turn` and `after_turn` to `Plugin`, and call them from the worker with 10 s and 60 s timeouts, swallowing errors. Verify: worker tests with a fake plugin show context in the system message, two plugins in load order, and a raising or slow hook leaving the job answered.
- [ ] 1.3 Emit the `memories` event and `recalled` and `remembered` activity from hook results, and skip `after_turn` for a failed turn. Verify: worker tests assert the events and activity, and that a hermes failure calls no after-turn hook.
- [ ] 1.4 Document both hooks and the API versions in `docs/plugins.md`. Verify: the section exists and its example plugin runs in a test.

## 2. The matts-memory plugin

- [ ] 2.1 Create `plugins/matts-memory` with an entry point and a lifespan that builds the embedder and extractor from the settings in both processes. Verify: it shows as loaded in the Apps tab, and both clients open and close with each process.
- [ ] 2.2 `before_turn` does today's recall and `after_turn` today's learning, reusing `dash.memory` and the store. Verify: the existing recall and learning worker tests pass unchanged against the plugin.
- [ ] 2.3 Serve the routes at `/api/plugins/matts-memory/memories` and add the Memories tab with `dash.addTab`, then remove the core routes and tab. Verify: web tests pass for the new paths and give 404 for `/api/memories`, and a headless check shows no Memories tab with the plugin disabled.
- [ ] 2.4 Stop building and passing an embedder in core. Verify: `uv run pytest`, `ruff check`, `ruff format --check` and `pyright` pass.

## 3. Image and docs

- [ ] 3.1 Install the plugin in the image: `COPY plugins` in the Dockerfile and the plugin path in the `PLUGINS` build argument of `joel-dash-build.yml`. Verify: the Apps tab of the built image lists `matts-memory` and dash-brood.
- [ ] 3.2 Update the README and `FORK.md` to say memory is a plugin and how to turn it off. Verify: both mention `DASH_PLUGINS_DISABLED=matts-memory`.
- [ ] 3.3 `openspec validate memory-as-plugin --strict` passes.

## 4. Cluster QA

Run after the image is pinned in jlithgow-ops.

- [ ] 4.1 With the plugin on, a chat turn adds a "The user …" fact to the Memories tab, and a related new chat shows "Recalled N memories".
- [ ] 4.2 With `DASH_PLUGINS_DISABLED=matts-memory`, there is no Memories tab, no "Recalled" line, and the row count of the `memories` table does not change after turns.
- [ ] 4.3 `/api/memories` answers 404 either way.

## 5. After ACP merges

- [ ] 5.1 Make the memory plugin do nothing for an agent with `memory: false`. Verify: a worker test with such an agent shows no lookup and no stored memory.

## Workflow follow-up

- This change is fork-only for good, so archiving it would make `openspec/specs/` differ from upstream. Decide at archive time whether that matters.
