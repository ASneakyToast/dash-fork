## Why

Memories only work with AWS Bedrock, so running dash without an AWS account means no recall and no learning. Joel's deployment runs hermes through OpenRouter and has no AWS account. An OpenAI-compatible API (OpenRouter, LiteLLM) covers embeddings and chat, so memories can use it too.

## What Changes

- Add `MEMORY_BASE_URL` and `MEMORY_API_KEY`. When `MEMORY_BASE_URL` is set, embeddings and fact extraction go to that OpenAI-compatible API instead of Bedrock. No AWS credentials are needed.
- `EMBED_MODEL` and `EXTRACT_MODEL` name models on whichever provider is active. Defaults stay the Bedrock models.
- Embeddings are requested with `dimensions: 1024`, so the existing `vector(1024)` column and index stay as they are. The embedding model must accept that parameter.
- Local dev: `compose.yaml` passes the new variables through, and `dev/litellm.openrouter.yaml` runs the local LiteLLM on OpenRouter (selected with `LITELLM_CONFIG`).
- No change when `MEMORY_BASE_URL` is unset. Nothing is **BREAKING**.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `memories`: the Bedrock-only requirement becomes "defaults to Bedrock", and a new requirement covers the OpenAI-compatible provider.

## Impact

- Code: `config.py`, `memory.py`, `web.py`, `__init__.py` (worker), plus `tests/test_units.py`.
- Config and docs: `compose.yaml`, `.env.example`, `README.md`, `dev/litellm.openrouter.yaml`.
- Operators: switching the embedding model on a database that already holds memories mixes vector spaces (see `design.md`).
- Code lives on `feat/openai-compatible-memory` (cut from upstream `main`, so it can go to `whatever/dash` without any fork files). This change folder is fork-only until upstream adopts OpenSpec.
