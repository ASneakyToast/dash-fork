## ADDED Requirements

### Requirement: Memory is an optional plugin

Recall, learning, the memory API and the Memories tab SHALL be provided by the plugin `matts-memory`. dash SHALL run, and chat SHALL work, when that plugin is not installed or is disabled with `DASH_PLUGINS_DISABLED=matts-memory`. With the plugin on, every other requirement of this capability holds unchanged.

#### Scenario: Memory off

- **WHEN** the plugin is disabled and the user sends a message
- **THEN** the agent receives no memory system message, the job has no `memories` event, and no memory is stored after the reply

#### Scenario: No Memories tab

- **WHEN** the plugin is disabled
- **THEN** the web UI has no Memories tab

#### Scenario: Memory on

- **WHEN** the plugin is enabled
- **THEN** memories are recalled and learned exactly as the other requirements of this capability describe

### Requirement: The memory API is served under the plugin's prefix

The plugin SHALL serve listing and searching, adding, and deleting memories under `/api/plugins/matts-memory/memories`, with the same request and response shapes the memory API had. The former `/api/memories` paths SHALL answer 404.

#### Scenario: List at the new path

- **WHEN** a client requests `/api/plugins/matts-memory/memories`
- **THEN** the response is the same list the former `/api/memories` returned

#### Scenario: Former path

- **WHEN** a client requests `/api/memories`
- **THEN** the response is 404

#### Scenario: Plugin disabled

- **WHEN** the plugin is disabled and a client requests `/api/plugins/matts-memory/memories`
- **THEN** the response is 404
