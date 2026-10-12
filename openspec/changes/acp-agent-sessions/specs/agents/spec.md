## Purpose

Let dash talk to more than one agent: hermes's OpenAI-compatible API, or any agent that speaks the Agent Client Protocol (ACP), and run each conversation as a session on its agent that the user can follow, answer and stop.

## ADDED Requirements

### Requirement: Agents are configured by name

The system SHALL read its agents from `DASH_AGENTS`, a JSON object from agent name to settings. An agent with `command` SHALL be an ACP agent over stdio, one with `url` an ACP agent over a WebSocket, and one with neither an OpenAI-compatible chat agent. `title` SHALL default to the name. `DASH_DEFAULT_AGENT` SHALL name the agent new conversations use, else the first.

#### Scenario: Three kinds

- **WHEN** `DASH_AGENTS` is `{"claude": {"command": ["claude-agent-acp"]}, "hermes": {"url": "ws://h:8765/"}, "api": {}}`
- **THEN** `claude` is an ACP agent over stdio, `hermes` an ACP agent over a WebSocket, `api` an OpenAI-compatible agent, and the default is `claude`

#### Scenario: Default named

- **WHEN** `DASH_DEFAULT_AGENT` is `hermes` and `hermes` is in `DASH_AGENTS`
- **THEN** new conversations use `hermes`

### Requirement: Without settings there is one hermes agent

When `DASH_AGENTS` is unset or empty, the system SHALL have exactly one agent, `hermes`, of the OpenAI-compatible kind, using `HERMES_BASE_URL`, `HERMES_API_KEY` and `HERMES_MODEL`. An OpenAI-compatible agent's `base_url`, `model` and `api_key_env` (the name of an env var holding the key) SHALL override those settings for that agent.

#### Scenario: No settings

- **WHEN** `DASH_AGENTS` and `DASH_DEFAULT_AGENT` are unset
- **THEN** the only agent is `hermes`, and replies come from `HERMES_BASE_URL` as before this change

#### Scenario: Override for one agent

- **WHEN** an agent sets `base_url` `http://h/v1/`, `model` `m` and `api_key_env` `KEY`
- **THEN** that agent calls `http://h/v1` with model `m` and the value of `KEY` as its key

### Requirement: Invalid agent settings stop startup

The API and the worker SHALL refuse to start when `DASH_AGENTS` is not a JSON object with at least one agent, when an agent sets both `command` and `url`, or when `DASH_DEFAULT_AGENT` names an agent that is not configured.

#### Scenario: Both transports

- **WHEN** an agent sets both `command` and `url`
- **THEN** startup fails with an error naming that agent

#### Scenario: Unknown default

- **WHEN** `DASH_DEFAULT_AGENT` is `b` and only `a` is configured
- **THEN** startup fails with an error naming `DASH_DEFAULT_AGENT`

### Requirement: Agents are listed without secrets

The system SHALL list the agents at `GET /api/agents` as the default agent's name and, for each agent, its `name`, `title`, `kind` (`acp` or `openai`) and `transport` (`stdio`, `websocket` or `http`). The list SHALL NOT contain tokens, keys, headers, commands or environment values.

#### Scenario: Listing

- **WHEN** a client requests `GET /api/agents`
- **THEN** the response holds `default` and one entry per configured agent with only those four fields

#### Scenario: A token is never shown

- **WHEN** an agent's `token_env` names a variable holding `t0k`
- **THEN** `t0k` does not appear in the response

### Requirement: The configured agents can be checked from the command line

`dash agents` SHALL print each configured agent's name, kind and address, marking the default, without starting or contacting any agent.

#### Scenario: Check the settings

- **WHEN** an operator runs `dash agents`
- **THEN** each agent is printed on its own line and the default one is marked

### Requirement: A conversation is bound to one agent

Creating a conversation SHALL accept an optional `agent` naming a configured agent and SHALL bind the conversation to it, or to the default agent when none is given. A conversation made before agents existed SHALL use the default agent. A job whose conversation names an agent that is no longer configured SHALL end with the `error` event `Unknown agent '<name>'.`

#### Scenario: Agent chosen

- **WHEN** a client creates a conversation with `agent` `hermes`
- **THEN** the response is 201 with `agent` `hermes`, and the conversation list shows `hermes` for it

#### Scenario: Unknown agent

- **WHEN** a client creates a conversation with an agent name that is not configured
- **THEN** the response is 400 and no conversation is made

#### Scenario: Agent removed from settings

- **WHEN** a job runs for a conversation bound to `gone`, which is no longer configured
- **THEN** the job ends with the `error` event `Unknown agent 'gone'.`

### Requirement: A stdio agent gets only the environment it is given

The system SHALL start a stdio agent's `command` on its first turn, in `cwd` when set, and keep it running for later turns. The process SHALL receive only `HOME`, `LOGNAME`, `PATH`, `SHELL`, `TERM` and `USER` from dash's environment, plus the variables named in `pass_env` that are set, plus the fixed values in `env`.

#### Scenario: Passing a key

- **WHEN** an agent sets `pass_env` `["ANTHROPIC_API_KEY"]` and dash's environment holds `ANTHROPIC_API_KEY` and `DATABASE_URL`
- **THEN** the agent process has `ANTHROPIC_API_KEY` and does not have `DATABASE_URL`

### Requirement: A WebSocket agent is reached with its configured headers

The system SHALL open a WebSocket agent's `url` on its first turn and send the configured `headers` with the handshake. When `token_env` is set, it SHALL send `Authorization: Bearer <value of that variable>`.

#### Scenario: Bearer token

- **WHEN** an agent sets `token_env` `HERMES_ACP_TOKEN` and that variable is `s3cret`
- **THEN** the handshake carries `Authorization: Bearer s3cret`

#### Scenario: Agent unreachable

- **WHEN** nothing listens at the agent's `url`
- **THEN** the job ends with an `error` event beginning with the agent's name

### Requirement: dash offers no files or terminal to an ACP agent

When it connects, the system SHALL identify itself to an ACP agent as `dash` and SHALL advertise no file system and no terminal capability, so the agent uses its own tools where it runs. A new session SHALL be opened with the agent's `cwd`, or the worker's directory when unset, and no MCP servers.

#### Scenario: Capabilities

- **WHEN** dash initializes a connection to an ACP agent
- **THEN** the client capabilities it sends grant no file reads or writes and no terminals

### Requirement: An ACP conversation keeps one session

On a conversation's first turn the system SHALL open a session on its ACP agent and store the session id on the conversation. Later turns SHALL reuse that session and send only the new user message. A turn's prompt SHALL be text blocks: recalled memories when the agent's `memory` setting is on (the default), then any carried history, then the user message.

#### Scenario: Second turn

- **WHEN** a conversation that already has a session gets a new message
- **THEN** the agent receives a prompt for that session holding the new message and not the earlier ones

#### Scenario: Memory off

- **WHEN** an agent sets `memory` `false` and memories were recalled for the job
- **THEN** the prompt holds only the user message

### Requirement: A lost session is restored or replaced

When the stored session is not open on the current connection, the system SHALL restore it with `session/load` if the agent supports it, else `session/resume` if supported. Updates the agent replays while loading SHALL NOT be shown or stored. If neither works, the system SHALL open a new session, store its id, and send the last 20 earlier messages, at most 20,000 characters, before the new one.

#### Scenario: Worker restarted

- **WHEN** the worker restarts and an agent that supports `session/load` gets the next message of a conversation
- **THEN** the conversation keeps its session id and no replayed text appears in the reply

#### Scenario: Agent forgot the session

- **WHEN** the agent cannot restore the stored session
- **THEN** a new session id is stored, and the prompt starts with the earlier messages as text, then the new message

### Requirement: A dead agent is reconnected on the next turn

When a stdio agent's process has exited, or a connection to an agent fails, the system SHALL start or open a new connection on the agent's next turn. A turn that fails because the connection failed SHALL end with an `error` event beginning with the agent's name.

#### Scenario: Process killed

- **WHEN** a stdio agent's process is killed between two turns
- **THEN** the next turn starts a new process and is answered

### Requirement: Permission questions wait for the user

When an ACP agent asks permission to run a tool, the system SHALL append a `permission` event to the job with an `id`, a `title` and the agent's `options` (`id`, `name`, `kind`), and SHALL wait. A client SHALL answer with `POST /api/jobs/{job_id}/permissions/{id}` and `{"option_id": …}`, answered 202. The system SHALL then give the agent that option and append `permission_done` with `id` and `option_id`.

#### Scenario: Allowed

- **WHEN** the agent asks with options `yes` and `no`, and a client answers `yes`
- **THEN** the agent receives `yes`, the job gets `permission_done` with `option_id` `yes`, and the turn continues

#### Scenario: Answer from another device

- **WHEN** the question was asked while one tab was open, and a different tab or device answers it
- **THEN** the answer is applied the same way

#### Scenario: Malformed ids

- **WHEN** the job id or question id in the answer path is not alphanumeric
- **THEN** the response is 400

### Requirement: An unusable answer denies the request

The system SHALL tell the agent the request was cancelled when the answer's `option_id` is `null` or is not one of the offered options, when the user stopped the turn, or when the turn ends with the question open. A question asked after the user stopped the turn SHALL be denied without being shown.

#### Scenario: Unknown option

- **WHEN** a client answers with `option_id` `bogus`
- **THEN** the agent is told the request was cancelled

#### Scenario: Asked after Stop

- **WHEN** the agent asks permission after the user pressed Stop
- **THEN** no `permission` event is appended and the request is denied

### Requirement: The answers are kept with the reply

The stored assistant message's `details.permissions` SHALL list each question asked during the turn with its `id`, `title`, `options` and the `option_id` it was answered with, `null` when the answer was empty or never came (Stop, or the turn ended first).

#### Scenario: After reload

- **WHEN** a client reads the messages of a conversation after a turn in which the user allowed a command
- **THEN** that assistant message's `details.permissions` holds the question and the chosen option

### Requirement: Stop ends a running turn

A client SHALL stop a running job with `POST /api/jobs/{job_id}/cancel`, answered 202. An ACP agent SHALL be sent `session/cancel` and given 15 seconds to end the turn; after that, or at once for an OpenAI-compatible agent or an ACP turn with no session yet, the system SHALL stop reading the reply. The partial reply SHALL be stored and `done` SHALL carry `stop` `cancelled`. No memories SHALL be extracted from it.

#### Scenario: ACP agent stops

- **WHEN** a client cancels a job while its ACP agent is running a tool
- **THEN** the agent gets `session/cancel`, the partial reply is stored with `details.stop` `cancelled`, `done` carries `stop` `cancelled`, and no memories are extracted

#### Scenario: Agent ignores the cancel

- **WHEN** the agent keeps running 15 seconds after `session/cancel`
- **THEN** the system stops reading, stores the reply as cancelled and ends the job with `done`

#### Scenario: Chat agent

- **WHEN** a client cancels a job on an OpenAI-compatible agent mid-reply
- **THEN** the system stops reading at once and stores the text received so far as cancelled

#### Scenario: Cancel before the job runs

- **WHEN** a client cancels a job before the worker takes it
- **THEN** the job ends with `done` carrying `stop` `cancelled` when it runs

#### Scenario: Malformed job id

- **WHEN** the job id is not alphanumeric
- **THEN** the response is 400

### Requirement: The activity feed shows what a turn waits on

The worker SHALL add a `waiting` activity entry with the question's `title` when a permission question is asked, an `answered` entry with the chosen `option_id` when it is answered, and a `cancelling` entry when a client stops the job. The `done` entry SHALL carry `stop`.

#### Scenario: Question and answer

- **WHEN** an agent asks permission and the user answers
- **THEN** the job's activity includes `waiting` then `answered` before `done`
