## 1. Agent settings

Implemented on `joel-dash/acp`.

- [x] 1.1 Add `agent-client-protocol[http]` 0.12.x and keep the lock in sync. Verify: `uv lock --check` passes.
- [x] 1.2 Parse `DASH_AGENTS` and `DASH_DEFAULT_AGENT` into a catalog of agent specs, with one `hermes` agent when unset. Verify: `test_an_empty_catalog_is_one_hermes_chat_agent`, `test_catalog_reads_stdio_and_websocket_agents`.
- [x] 1.3 Refuse bad settings at startup. Verify: `test_catalog_rejects_bad_settings`, `test_catalog_spec_raises_for_an_unknown_agent`.
- [x] 1.4 `dash agents` prints the catalog without starting anything. Verify: `DASH_AGENTS=… uv run dash agents` lists each agent and marks the default.
- [x] 1.5 Document the settings in `docs/agents.md` and the README settings table. Verify: both files are in the branch diff.

## 2. Agents

- [x] 2.1 The OpenAI-compatible agent wraps the existing hermes client, with memories as a system message and the full history. Verify: `test_chat_agent_sends_context_and_history`, and the existing worker tests pass unchanged apart from their setup.
- [x] 2.2 The ACP agent over stdio: start the process with a trimmed environment, initialize with no `fs` or `terminal`, open and reuse sessions, map updates to text, thought, tool and plan. Verify: `test_acp_turn_streams_thoughts_plan_tools_and_text`, `test_acp_session_is_reused_for_the_next_turn`, `test_acp_memory_off_sends_only_the_user_text`.
- [x] 2.3 Restore lost sessions (`session/load`, `session/resume`, else a new session carrying history), dropping replayed updates. Verify: `test_acp_session_is_loaded_without_replaying_old_updates`, `test_a_lost_session_starts_a_new_one_with_the_history`.
- [x] 2.4 Reconnect after a dead process or a failed connection. Verify: `test_a_dead_agent_process_is_restarted`, `test_an_agent_that_will_not_start_raises`, `test_a_websocket_agent_that_is_down_raises`.
- [x] 2.5 Route permission questions to the turn and deny unusable answers. Verify: `test_acp_permission_question_goes_to_the_turn` (allow, deny, `null`, unknown option).
- [x] 2.6 Cancel a turn, and on an abandoned turn wait for the agent before releasing the session. Verify: `test_acp_cancel_ends_the_turn`, `test_closing_a_turn_early_cancels_it_on_the_agent`, `test_cancel_without_a_connection_or_session_is_refused`.
- [x] 2.7 The ACP agent over a WebSocket. Verify: by hand, the fake agent behind `websocketd` 0.4.1 answers a turn and a permission question.

## 3. Worker, queue and storage

- [x] 3.1 Migration 0003: nullable `conversations.agent` and `conversations.session_id`, `messages.details` JSONB default `{}`. Verify: `dash migrate` then downgrade to 0002 and upgrade again on `pgvector/pgvector:pg16`.
- [x] 3.2 Run each job on its conversation's agent, store a new session id, stream `thought`, `tool` and `plan` events, store `details`, put `stop` on `done`. Verify: `test_an_acp_turn_is_streamed_saved_and_bound_to_its_session`, `test_a_conversation_with_an_unknown_agent_errors`.
- [x] 3.3 The `dash:control:<job>` stream and the watcher: permission answers and Stop, with the 15 s cut-off. Verify: `test_the_browser_answers_a_permission_question`, `test_cancel_stops_an_acp_turn_and_learns_nothing`, `test_cancel_stops_a_chat_turn_that_cannot_cancel_itself`, `test_cancel_cuts_off_an_agent_that_ignores_it`, `test_a_question_after_stop_is_denied_without_asking`, `test_cancel_before_the_session_exists_stops_reading`.
- [x] 3.4 Concurrent jobs, one at a time per conversation, and the claim heartbeat. Verify: `test_run_handles_jobs_side_by_side`, `test_heartbeat_keeps_running_jobs_claimed`.
- [x] 3.5 Activity entries `waiting`, `answered`, `cancelling`, and `stop` on `done`, documented in `docs/plugins.md`. Verify: the permission and cancel worker tests check the activity kinds; the dash-brood tests still pass.

## 4. API

- [x] 4.1 `GET /api/agents`, `agent` on conversation create and list, `details` on messages. Verify: `test_agents_are_listed`, `test_a_conversation_is_bound_to_the_chosen_agent`, `test_messages_carry_their_details`.
- [x] 4.2 `POST /api/jobs/{job_id}/cancel` and `POST /api/jobs/{job_id}/permissions/{id}`, 400 on malformed ids. Verify: `test_cancel_and_permission_answers_reach_the_worker`.

## 5. Web UI

- [x] 5.1 Agent picker, tool calls, plan, thoughts, permission prompts, Stop, and running / needs-you marks; re-attach to a running job on open. Verify: a Playwright run against `dash serve` and `dash worker` with the fake agent: a turn, Allow, Stop, a reload while a question is open (it comes back, marked needs you), Deny, and a reload showing the stored answers, at 1200 px and 390 px wide.
- [x] 5.2 Style it with design tokens, adding `dash.color.warning` and `dash.color.success` to `tokens.json` and the high-contrast theme, documented in `docs/theming.md`. Verify: `tests/test_theme.py` passes and `style.css` has no fixed colors in the new rules.

## 6. Checks and spec

- [x] 6.1 `uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest` pass (160 tests on `joel-dash/main`), and `node --test "examples/dash-brood/tests/*.test.js" "tests/js/*.test.js"` passes.
- [x] 6.2 `openspec validate acp-agent-sessions --strict` passes.

## 7. QA on the cluster

Run after the fork image from `joel-dash/acp` is pinned and hermes's ACP sidecar is deployed (jlithgow-ops `docs/plans/dash-acp.md`).

- [ ] 7.1 `kubectl -n dash logs deploy/dash-api -c migrate` shows 0003 ran.
- [ ] 7.2 A new Planner (ACP) chat streams a reply with its tool calls shown.
- [ ] 7.3 A command hermes treats as dangerous asks in dash; Allow and Deny both reach hermes.
- [ ] 7.4 Stop ends a long turn and the partial reply is stored as stopped.
- [ ] 7.5 After `kubectl -n dash rollout restart deploy/dash-worker`, a follow-up message in the same chat still knows the earlier turns.
- [ ] 7.6 A chat on the old API agent still works.
- [ ] 7.7 The ACP port refuses connections from any pod but the worker.

## Workflow follow-up

- Archive this change once cluster QA passes, so `openspec/specs/agents/spec.md` is created and `openspec/specs/chat/spec.md` takes the delta.
- If the work goes to `whatever/dash`, open it from a branch off upstream `main` without the fork's workflow and `openspec/changes/` files, as with `openai-compatible-memory`.
