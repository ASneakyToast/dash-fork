# chat Specification

## Purpose

Talk to the hermes agent in saved conversations. A message becomes a job on a Redis queue, a worker streams hermes's reply into a per-job event stream, and the browser follows that stream over server-sent events.

## Requirements

### Requirement: Conversations are saved and listed by recent activity

The system SHALL store conversations and their messages. The conversation list SHALL return at most 50 conversations, most recently active first.

#### Scenario: Create a conversation

- **WHEN** a client creates a conversation
- **THEN** the response is 201 with the conversation's `id` and the title `New conversation`

#### Scenario: Activity moves a conversation to the top

- **WHEN** a message is added to an older conversation
- **THEN** that conversation is listed before conversations with no newer activity

### Requirement: The first message names the conversation

The system SHALL title a conversation still named `New conversation` after the first line of the first user message, cut to 80 characters.

#### Scenario: First user message

- **WHEN** a user message is added to a conversation titled `New conversation`
- **THEN** the title becomes the first line of that message, at most 80 characters

#### Scenario: Later messages leave the title alone

- **WHEN** a user message is added to a conversation that already has a title
- **THEN** the title does not change

### Requirement: Sending a message queues a reply job

The system SHALL accept a user message for an existing conversation, store it, add a job to the queue, and return 202 with the `job_id`. A message SHALL have between 1 and 100,000 characters.

#### Scenario: Message accepted

- **WHEN** a client posts a valid message to an existing conversation
- **THEN** the message is stored with role `user`, one job is queued for that conversation, and the response is 202 with a `job_id`

#### Scenario: Unknown conversation

- **WHEN** a client posts a message to a conversation that does not exist
- **THEN** the response is 404 and nothing is stored or queued

#### Scenario: Empty or oversized message

- **WHEN** a client posts a message that is empty or longer than 100,000 characters
- **THEN** the request is rejected and nothing is stored or queued

### Requirement: Replies come from hermes

The worker SHALL answer a job by streaming a chat completion from the hermes router's OpenAI-compatible `/chat/completions` endpoint, using the model named by `HERMES_MODEL`. The request SHALL contain the conversation's full stored history in order. The worker SHALL send a bearer token only when `HERMES_API_KEY` is set.

#### Scenario: Full history is sent

- **WHEN** a conversation has earlier messages and the user sends another
- **THEN** hermes receives every stored message of that conversation in order, ending with the new user message

#### Scenario: Recalled memories lead the history

- **WHEN** memories were recalled for the job
- **THEN** a system message listing them comes before the stored messages

#### Scenario: No API key

- **WHEN** `HERMES_API_KEY` is empty
- **THEN** requests to hermes carry no `Authorization` header

### Requirement: Replies stream as job events

The worker SHALL append events to the job's own stream. A `delta` event SHALL carry reply text; the worker SHALL batch text so each event holds at least 48 characters, except the last. After the whole reply is stored as an `assistant` message, the worker SHALL append a `done` event carrying the `message_id`.

#### Scenario: Successful reply

- **WHEN** hermes streams a reply
- **THEN** the job's events are the `delta` events that spell out the reply, then `done`, and the full reply is stored as one assistant message

#### Scenario: Memories event

- **WHEN** at least one memory was recalled for the job
- **THEN** a `memories` event listing their text comes before the first `delta`

### Requirement: Failures end the job with an error event

The worker SHALL end a job that cannot be answered with a single `error` event carrying a message, and SHALL NOT store an assistant message for it.

#### Scenario: hermes fails

- **WHEN** the call to hermes raises an error part-way through
- **THEN** the job ends with an `error` event beginning `hermes:`, no assistant message is stored, and no memories are extracted

#### Scenario: Nothing to answer

- **WHEN** a job's conversation is empty or its last message is not from the user
- **THEN** the job ends with the `error` event `No user message to answer.`

#### Scenario: Unexpected failure

- **WHEN** handling a job raises an unexpected error
- **THEN** the job ends with an `error` event and is acknowledged, so it is not retried

### Requirement: A job's events can be followed and replayed

The system SHALL serve a job's events as server-sent events at `/api/jobs/{job_id}/events`. A client SHALL receive every event from the start of the job, whenever it connects, then new events as they arrive, until a `done` or `error` event. While idle the stream SHALL send a comment line (`: ping`) at least every 15 seconds. The system SHALL keep a job's events for one hour after the last event, and SHALL stop streaming when the client disconnects.

#### Scenario: Connect after the reply started

- **WHEN** a client opens the events stream after some `delta` events exist
- **THEN** it receives those events first, then the rest, and the stream ends after `done`

#### Scenario: Malformed job id

- **WHEN** a client requests events for a job id that is not alphanumeric
- **THEN** the response is 400

### Requirement: Jobs survive worker failure

The queue SHALL give each job to one worker at a time and remove it only after the worker finishes it, with a reply or an error. A job held unfinished for five minutes SHALL be given to another worker. A worker that cannot reach the queue SHALL keep running and retry every two seconds.

#### Scenario: Worker dies mid-job

- **WHEN** a worker takes a job and stops without finishing it
- **THEN** after five minutes another worker takes the job

#### Scenario: Queue outage

- **WHEN** the queue is unreachable and then recovers
- **THEN** the worker resumes taking jobs without being restarted

### Requirement: Queue status

The system SHALL report the number of waiting jobs, jobs in flight, and workers at `/api/queue`.

#### Scenario: One job running

- **WHEN** one worker holds one job and none are waiting
- **THEN** the report shows `in_flight` 1, `waiting` 0 and `workers` 1
