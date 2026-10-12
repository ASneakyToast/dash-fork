## Context

Memories use two model calls: an embedding per text and a fact extraction per finished turn (see `openspec/specs/memories/spec.md`). Both were Bedrock-only. Embeddings live in a `vector(1024)` column with an HNSW cosine index. See `proposal.md` for the motivation.

## Goals / Non-Goals

**Goals**
- Run memories on any OpenAI-compatible API without touching the schema.
- Leave Bedrock behavior byte-for-byte unchanged when the new variables are unset.

**Non-Goals**
- Moving hermes chat traffic. That already uses an OpenAI-compatible endpoint.
- Re-embedding existing memories, or detecting that the embedding model changed.

## Decisions

**One variable selects the provider.** Setting `MEMORY_BASE_URL` switches to the OpenAI-compatible client; there is no `MEMORY_PROVIDER` enum. Fewer settings, and an unset variable is exactly today's behavior. Alternative: an explicit provider name, which would scale to more providers but nothing needs a third yet.

**Ask for 1024 dimensions instead of changing the column.** OpenAI-style embedding endpoints accept `dimensions`, and Titan v2 was already used at 1024. Changing `EMBED_DIM` would need a migration and a re-embed. The cost is a constraint on operators: the embedding model must support `dimensions`. Documented in the README's settings table.

**Separate key from hermes.** `MEMORY_API_KEY` is its own variable so the memory provider can have its own key and spend limit. The deployment sets one in `cluster/apps/dash/secrets.enc.yaml` (jlithgow-ops plan `docs/plans/dash.md`).

**Same two-method interface for both providers.** Both clients implement `embed` and `extract`, and each has a `close()` that the web lifespan and the worker call on shutdown. Callers don't know which provider they hold.

**Local dev stays optional.** `LITELLM_CONFIG` picks which LiteLLM config the compose stack mounts, defaulting to the Bedrock one, so `just up` works as before.

## Risks / Trade-offs

- **Mixed vector spaces.** Vectors from different embedding models are not comparable. Switching `EMBED_MODEL`, or moving from Bedrock to a gateway, on a database that already has memories makes recall and duplicate detection return nonsense for old rows. Nothing detects it. Mitigation: choose the provider before the first memory, or delete the old memories. The deployment is new and has none yet.
- **Gateway latency and errors** are treated like Bedrock failures (logged, memories skipped), so a flaky gateway degrades memories, not chat.

## Migration Plan

Set `MEMORY_BASE_URL`, `MEMORY_API_KEY`, `EMBED_MODEL` and `EXTRACT_MODEL` and restart the API and worker. Roll back by unsetting `MEMORY_BASE_URL` (and restoring the Bedrock model names). Rolling back after memories were created on the gateway has the same mixed-space problem.

## Open Questions

Neither changes what this change builds, so both are follow-ups:
- Should dash store the embedding model name with each memory and warn on mismatch?
- Should there be a `dash reembed` command?
