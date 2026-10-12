## RENAMED Requirements

- FROM: `### Requirement: Embeddings and fact extraction run on Amazon Bedrock`
- TO: `### Requirement: Memory models default to Amazon Bedrock`

## MODIFIED Requirements

### Requirement: Memory models default to Amazon Bedrock

When `MEMORY_BASE_URL` is unset or empty, the system SHALL create embeddings with the Bedrock model named by `EMBED_MODEL` (default Titan Text Embeddings v2, normalized, input cut to 20,000 characters) and extract facts with the Bedrock model named by `EXTRACT_MODEL` (default Claude Haiku 4.5, temperature 0, at most 512 output tokens). Credentials and region SHALL come from the standard AWS environment chain.

#### Scenario: Default models

- **WHEN** `EMBED_MODEL` and `EXTRACT_MODEL` are unset
- **THEN** embeddings use `amazon.titan-embed-text-v2:0` and extraction uses `us.anthropic.claude-haiku-4-5-20251001-v1:0`

#### Scenario: No base URL

- **WHEN** `MEMORY_BASE_URL` is empty
- **THEN** memory models run on Bedrock

## ADDED Requirements

### Requirement: Memory models can run on an OpenAI-compatible API

When `MEMORY_BASE_URL` is set, the system SHALL create embeddings and extract facts through that OpenAI-compatible API instead of Bedrock, using `EMBED_MODEL` and `EXTRACT_MODEL` as model names, and SHALL need no AWS credentials. It SHALL send `MEMORY_API_KEY` as a bearer token only when it is set, and SHALL give up on a request after 60 seconds.

#### Scenario: Provider selected

- **WHEN** `MEMORY_BASE_URL` is `https://gateway.test/v1/`
- **THEN** embeddings and extraction requests go to `https://gateway.test/v1` and Bedrock is not called

#### Scenario: Embedding request

- **WHEN** the system embeds `tea`
- **THEN** it posts `{model: EMBED_MODEL, input: "tea", dimensions: 1024}` to `/embeddings`, input cut to 20,000 characters, and uses the first embedding returned

#### Scenario: Extraction request

- **WHEN** the system extracts facts from an exchange
- **THEN** it posts one user message holding the extraction prompt to `/chat/completions` with model `EXTRACT_MODEL`, temperature 0 and at most 512 tokens, and reads facts from the reply as it would from Bedrock

#### Scenario: Empty extraction reply

- **WHEN** the reply has no text content
- **THEN** no facts are extracted

#### Scenario: No API key

- **WHEN** `MEMORY_API_KEY` is empty
- **THEN** requests carry no `Authorization` header

#### Scenario: Gateway error

- **WHEN** the API answers with an error status during recall or extraction
- **THEN** it is handled as any other memory-model failure: recall proceeds with no memories, and extraction is logged and skipped
