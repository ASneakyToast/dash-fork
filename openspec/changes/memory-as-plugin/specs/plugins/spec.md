## Purpose

Let a plugin take part in each chat turn, before the agent is called and after the reply is saved, so features such as memory can live outside dash's core.

## ADDED Requirements

### Requirement: A plugin can add context before a turn

Before the worker calls the agent for a job, it SHALL call each active plugin's before-turn hook, in load order, with the conversation id, the job id and the user's latest message. A hook MAY return text for the system message and a list of short items to show the user. The worker SHALL put the returned texts, in order, in one system message ahead of the stored messages, and SHALL send no system message when no hook returns text.

#### Scenario: One plugin adds context

- **WHEN** a plugin's before-turn hook returns the text `The user likes tea.`
- **THEN** the agent receives a system message containing that text ahead of the stored messages

#### Scenario: Two plugins add context

- **WHEN** two plugins each return text
- **THEN** both texts are in the system message, in plugin load order

#### Scenario: No context

- **WHEN** no plugin returns text
- **THEN** the agent receives no system message

### Requirement: A plugin can show what it recalled

When a before-turn hook returns items, the worker SHALL emit one `memories` job event listing every returned item, and one `recalled` activity entry whose `count` is the number of items. When no hook returns items it SHALL emit neither.

#### Scenario: Items returned

- **WHEN** a before-turn hook returns three items
- **THEN** the job has a `memories` event with those three items, and a `recalled` activity entry with `count` 3

### Requirement: A plugin can act after a turn

After the reply is saved and `done` is emitted, the worker SHALL call each active plugin's after-turn hook, in load order, with the conversation id, the job id, the user's message and the reply, and SHALL wait for each before it acknowledges the job. A hook MAY return a count of things it stored. For a count above zero the worker SHALL publish a `remembered` activity entry with that `count`. After-turn hooks SHALL NOT run for a turn that ended in an error.

#### Scenario: Plugin stores something

- **WHEN** an after-turn hook returns 2
- **THEN** a `remembered` activity entry with `count` 2 is published

#### Scenario: Turn fails

- **WHEN** the agent call fails and the job ends with an `error` event
- **THEN** no after-turn hook is called

### Requirement: A failing hook never fails the turn

A hook that raises an error SHALL be logged and treated as if it had returned nothing. The worker SHALL cut off a before-turn hook after 10 seconds and an after-turn hook after 60 seconds, and treat a hook cut off the same way.

#### Scenario: Hook raises

- **WHEN** a before-turn hook raises an error
- **THEN** the error is logged and the reply is generated as if no plugin had returned context

#### Scenario: Hook is too slow

- **WHEN** an after-turn hook is still running after 60 seconds
- **THEN** it is cut off, the job is acknowledged, and the reply the user saw is unaffected

### Requirement: Plugins declare the plugin API they use

dash SHALL load plugins written for plugin API 1 or 2, and SHALL refuse any other version with the reason shown in the Apps tab. Turn hooks are part of API 2.

#### Scenario: API 1 plugin

- **WHEN** a plugin declares API 1
- **THEN** it loads as before and its turn hooks, if any, are not called

#### Scenario: Unknown API version

- **WHEN** a plugin declares API 3
- **THEN** it is not loaded and the Apps tab says which version it needs
