## RENAMED Requirements

- FROM: `### Requirement: Replies come from hermes`
- TO: `### Requirement: Replies come from the conversation's agent`

## MODIFIED Requirements

### Requirement: Conversations are saved and listed by recent activity

The system SHALL store conversations and their messages. The conversation list SHALL return at most 50 conversations, most recently active first. Each listed conversation SHALL carry its `agent` and, once its agent opened one, its `session_id`.

#### Scenario: Create a conversation

- **WHEN** a client creates a conversation
- **THEN** the response is 201 with the conversation's `id`, the title `New conversation` and its `agent`

#### Scenario: Activity moves a conversation to the top

- **WHEN** a message is added to an older conversation
- **THEN** that conversation is listed before conversations with no newer activity

#### Scenario: Agent in the list

- **WHEN** a client lists conversations
- **THEN** each one carries the name of the agent it is bound to, the default agent for a conversation made before agents existed

### Requirement: Replies come from the conversation's agent

The worker SHALL answer a job with the agent the conversation is bound to (see the `agents` capability). For an OpenAI-compatible agent it SHALL stream a chat completion from that agent's `/chat/completions` endpoint, using its model (`HERMES_MODEL` by default). That request SHALL contain the conversation's full stored history in order. The worker SHALL send a bearer token only when the agent has a key (`HERMES_API_KEY` by default).

#### Scenario: Full history is sent

- **WHEN** a conversation on an OpenAI-compatible agent has earlier messages and the user sends another
- **THEN** the agent receives every stored message of that conversation in order, ending with the new user message

#### Scenario: Recalled memories lead the history

- **WHEN** memories were recalled for a job on an OpenAI-compatible agent
- **THEN** a system message listing them comes before the stored messages

#### Scenario: No API key

- **WHEN** `HERMES_API_KEY` is empty
- **THEN** requests to hermes carry no `Authorization` header

#### Scenario: ACP agent

- **WHEN** a conversation is bound to an ACP agent
- **THEN** the reply comes from that agent's session, and only the new message is sent

### Requirement: Replies stream as job events

The worker SHALL append events to the job's own stream. A `delta` event SHALL carry reply text and a `thought` event the agent's reasoning; the worker SHALL batch each so an event holds at least 48 characters, except the last before an event of another kind. A `tool` event SHALL carry one tool call's latest state, and a `plan` event the agent's whole plan. After the reply is stored as an `assistant` message, the worker SHALL append `done` with `message_id` and `stop`.

#### Scenario: Successful reply

- **WHEN** an agent streams a reply
- **THEN** the job's events are the `delta` events that spell out the reply, then `done`, and the full reply is stored as one assistant message

#### Scenario: Memories event

- **WHEN** at least one memory was recalled for the job
- **THEN** a `memories` event listing their text comes before the first `delta`

#### Scenario: Tool call

- **WHEN** an ACP agent starts a tool call and then completes it
- **THEN** the job gets a `tool` event whose `tool` has `id`, `title`, `kind`, `status` `in_progress`, `detail` and `paths`, then another for the same `id` with `status` `completed` and the output's text, at most 2,000 characters, as `detail`

#### Scenario: Plan

- **WHEN** an ACP agent reports a plan
- **THEN** the job gets a `plan` event whose `entries` each have `content`, `status` and `priority`

#### Scenario: Stop reason

- **WHEN** an agent ends its turn normally
- **THEN** `done` carries `stop` `end_turn`

### Requirement: Failures end the job with an error event

The worker SHALL end a job that cannot be answered with a single `error` event carrying a message, and SHALL NOT store an assistant message for it.

#### Scenario: hermes fails

- **WHEN** the call to the default `hermes` agent raises an error part-way through
- **THEN** the job ends with an `error` event beginning `hermes:`, no assistant message is stored, and no memories are extracted

#### Scenario: Another agent fails

- **WHEN** the call to an agent named `claude` raises an error part-way through
- **THEN** the job ends with an `error` event beginning `claude:`, and nothing is stored or extracted

#### Scenario: Nothing to answer

- **WHEN** a job's conversation is empty or its last message is not from the user
- **THEN** the job ends with the `error` event `No user message to answer.`

#### Scenario: Unexpected failure

- **WHEN** handling a job raises an unexpected error
- **THEN** the job ends with an `error` event and is acknowledged, so it is not retried

### Requirement: Jobs survive worker failure

The queue SHALL give each job to one worker at a time and remove it only after the worker finishes it, with a reply or an error. A worker SHALL renew its claim on each job it runs at least every minute, and a job whose worker stopped renewing for five minutes SHALL be given to another worker. A worker that cannot reach the queue SHALL keep running and retry every two seconds.

#### Scenario: Worker dies mid-job

- **WHEN** a worker takes a job and stops without finishing it
- **THEN** after five minutes another worker takes the job

#### Scenario: Long turn

- **WHEN** a live worker runs one job for longer than five minutes
- **THEN** no other worker takes that job

#### Scenario: Queue outage

- **WHEN** the queue is unreachable and then recovers
- **THEN** the worker resumes taking jobs without being restarted

## ADDED Requirements

### Requirement: Jobs run side by side, in order within a conversation

A worker SHALL run up to `DASH_WORKER_CONCURRENCY` jobs at once (default 4). Jobs of the same conversation SHALL run one at a time, in the order they were queued.

#### Scenario: Two conversations

- **WHEN** two conversations each have a queued job and the limit is 2 or more
- **THEN** both jobs run at the same time

#### Scenario: Same conversation

- **WHEN** a conversation gets a second message while its first job runs
- **THEN** the second job starts only after the first one ends

### Requirement: Assistant messages keep what the agent did

The messages endpoint SHALL return each message's `details`, an empty object when there are none. An assistant message's `details` SHALL hold `agent`, `stop`, and, when there were any, `tools` (each call's last state), `plan`, `permissions` and `thoughts` (at most 20,000 characters).

#### Scenario: Reload after a turn with tools

- **WHEN** a client reads the messages of a conversation after an ACP turn that ran a tool
- **THEN** the assistant message's `details` has the agent's name, `stop`, and the tool call with its final status

#### Scenario: Stopped reply

- **WHEN** the user stopped a turn
- **THEN** the stored assistant message has `details.stop` `cancelled`
