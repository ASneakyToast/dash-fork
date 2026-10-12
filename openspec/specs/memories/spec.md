# memories Specification

## Purpose

Long-term facts about the user. dash recalls the relevant ones into each reply, learns new ones from conversations, and lets the user search, add and delete them.

## Requirements

### Requirement: Memories are stored with an embedding

The system SHALL store each memory with its text, a source, tags, a creation time, and a 1024-dimension embedding that can be searched by cosine distance.

#### Scenario: Stored fields

- **WHEN** a memory is added
- **THEN** it keeps its text, its source (`manual` or `conversation`), its tags, and its embedding

### Requirement: Memories can be added by hand

The system SHALL let a client add a memory of 1 to 2,000 characters with optional tags. The system SHALL embed it, store it with source `manual`, and return 201 with the memory.

#### Scenario: Add a memory

- **WHEN** a client posts `The user prefers short answers.`
- **THEN** the response is 201 and the memory appears in the list with source `manual`

#### Scenario: Empty or oversized memory

- **WHEN** a client posts empty text or text longer than 2,000 characters
- **THEN** the request is rejected and nothing is stored

### Requirement: Memories can be listed and searched

The system SHALL list memories newest first, at most 200. When the `q` parameter has text other than whitespace, the system SHALL instead return the 50 memories nearest to the embedding of `q`, nearest first, each with its cosine `distance` rounded to four decimal places.

#### Scenario: List

- **WHEN** a client requests memories with no query
- **THEN** memories are returned newest first and carry no `distance`

#### Scenario: Search by meaning

- **WHEN** a client requests memories with `q=music`
- **THEN** memories are returned ordered by distance from `music`, each with a `distance`

#### Scenario: Blank query

- **WHEN** `q` is empty or only whitespace
- **THEN** the response is the plain list

### Requirement: Memories can be deleted

The system SHALL delete a memory by id and return 204, or 404 if it does not exist.

#### Scenario: Unknown memory

- **WHEN** a client deletes a memory id that does not exist
- **THEN** the response is 404

### Requirement: Relevant memories are recalled into each reply

Before answering a job, the worker SHALL embed the latest user message and look up the `MEMORY_TOP_K` nearest memories (default 8). It SHALL keep only those within cosine distance 0.65. If any remain, it SHALL emit a `memories` event and put them in a system message that tells the model to use them when relevant and not to mention the list unless asked. If none remain, it SHALL send no system message and emit no event.

#### Scenario: Relevant memory

- **WHEN** a stored memory is within 0.65 of the user's message
- **THEN** the reply is generated with that memory in a system message, and the job has a `memories` event

#### Scenario: Nothing relevant

- **WHEN** no stored memory is within 0.65
- **THEN** hermes receives no system message and the job has no `memories` event

#### Scenario: Recall fails

- **WHEN** embedding or searching raises an error
- **THEN** the error is logged and the reply proceeds as if nothing was recalled

### Requirement: New memories are learned from conversations

After a reply is saved and `done` is emitted, the worker SHALL pass the user message and the reply to a fact extractor. For each fact returned, it SHALL embed it and store it with source `conversation`, unless a stored memory is within cosine distance 0.08 of it.

#### Scenario: New fact

- **WHEN** the extractor returns `The user lives in Oakland.` and no stored memory is within 0.08
- **THEN** a memory with that text and source `conversation` is stored

#### Scenario: Duplicate fact

- **WHEN** the extractor returns a fact within 0.08 of a stored memory
- **THEN** it is not stored again

#### Scenario: Extraction fails

- **WHEN** the extractor or the embedder raises an error
- **THEN** the error is logged, the already-delivered reply is unaffected, and facts stored before the error are kept

### Requirement: Extracted facts are short sentences about the user

The extractor SHALL be asked for durable facts as short, standalone, third-person sentences that begin `The user`, and SHALL receive at most 8,000 characters each of the user message and the reply. Output that does not contain a JSON array of strings SHALL yield no facts, and blank strings SHALL be dropped.

#### Scenario: Malformed extractor output

- **WHEN** the extractor's output has no JSON array, or the array holds non-strings or blank strings
- **THEN** only the non-blank strings, if any, are kept

### Requirement: Embeddings and fact extraction run on Amazon Bedrock

The system SHALL create embeddings with the Bedrock model named by `EMBED_MODEL` (default Titan Text Embeddings v2, normalized, input cut to 20,000 characters) and extract facts with the Bedrock model named by `EXTRACT_MODEL` (default Claude Haiku 4.5, temperature 0, at most 512 output tokens). Credentials and region SHALL come from the standard AWS environment chain.

#### Scenario: Default models

- **WHEN** `EMBED_MODEL` and `EXTRACT_MODEL` are unset
- **THEN** embeddings use `amazon.titan-embed-text-v2:0` and extraction uses `us.anthropic.claude-haiku-4-5-20251001-v1:0`
