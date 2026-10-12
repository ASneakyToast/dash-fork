## 1. Provider selection and clients

Implemented on `feat/openai-compatible-memory`.

- [x] 1.1 Read `MEMORY_BASE_URL` (trailing slash trimmed) and `MEMORY_API_KEY` into settings. Verify: `test_memory_base_url_selects_openai_compatible`.
- [x] 1.2 OpenAI-compatible embeddings with `dimensions` set to the column size. Verify: `test_openai_compatible_embed_asks_for_the_column_size`.
- [x] 1.3 OpenAI-compatible fact extraction. Verify: `test_openai_compatible_extract_parses_facts`.
- [x] 1.4 Use the selected client in the API and the worker, and close it on shutdown. Verify: `uv run pytest` passes (31 tests at `3bc1f31`).

## 2. Local dev and docs

- [x] 2.1 `compose.yaml` passes the new variables and `LITELLM_CONFIG`, and `dev/litellm.openrouter.yaml` exists. Verify: both files are in the branch diff.
- [x] 2.2 README settings table, README worker note and `.env.example` describe the new variables. Verify: the three files are in the branch diff.

## 3. Spec

- [x] 3.1 `openspec validate openai-compatible-memory --strict` passes.

## 4. QA on the cluster

Run after the fork image carrying this branch is pinned in jlithgow-ops (`docs/plans/dash.md`).

- [ ] 4.1 `kubectl -n dash logs deploy/dash-api -c migrate` shows the migration ran.
- [ ] 4.2 A chat turn streams a reply from the Planner.
- [ ] 4.3 After the turn, the Memories tab shows a new "The user …" fact (source `conversation`).
- [ ] 4.4 Memory search finds it, and a new chat shows "Recalled N memories".
- [ ] 4.5 Adding a memory by hand works (the API embeds it).

## 5. Upstream

- [ ] 5.1 Squash the `fixup!` commit on `feat/openai-compatible-memory`. Verify: `git log` shows one commit above upstream `main`.
- [ ] 5.2 Open the PR on `whatever/dash` from that branch. Verify: the PR diff has no `.github/workflows/joel-dash-build.yml` and no `openspec/changes/` files.

## Workflow follow-up

- After the PR merges upstream and the deployment pins an upstream image, archive this change so `openspec/specs/memories/spec.md` takes the delta.
