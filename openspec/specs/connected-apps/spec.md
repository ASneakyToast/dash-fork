# connected-apps Specification

## Purpose

Let the user connect outside apps through a self-hosted Nango. Nango holds the OAuth tokens; dash only starts connections, lists them and removes them.

## Requirements

### Requirement: Nango is optional

The system SHALL treat Nango as configured only when `NANGO_SECRET_KEY` is set. `/api/config` SHALL report whether it is configured, and the Nango addresses the browser needs. Every connection endpoint SHALL answer 503 when it is not configured.

#### Scenario: Not configured

- **WHEN** `NANGO_SECRET_KEY` is empty and a client requests `/api/connections`
- **THEN** the response is 503 with `Nango is not configured.`

#### Scenario: Config for the browser

- **WHEN** a client requests `/api/config`
- **THEN** the response says whether Nango is enabled, and gives `nango_host` (`NANGO_PUBLIC_URL`, else `NANGO_URL`) and `nango_connect_url`

### Requirement: Connections can be listed

The system SHALL return Nango's integrations and connections together.

#### Scenario: List

- **WHEN** a client requests `/api/connections`
- **THEN** the response has `integrations` and `connections` from Nango

#### Scenario: Nango is down

- **WHEN** Nango answers with an HTTP error or cannot be reached
- **THEN** the response is 502 naming Nango

### Requirement: Connecting starts with a short-lived session token

The system SHALL create a Nango connect session for a single fixed end user, `owner`, and return its token for the browser to open Nango's Connect UI.

#### Scenario: Start a connection

- **WHEN** a client posts to `/api/connections/session`
- **THEN** the response holds a `token` from Nango

### Requirement: Connections can be removed

The system SHALL delete a connection in Nango by its integration key and connection id, and return 204.

#### Scenario: Disconnect

- **WHEN** a client deletes `/api/connections/{provider_config_key}/{connection_id}`
- **THEN** Nango is asked to delete that connection under that integration key, and the response is 204

### Requirement: OAuth tokens stay in Nango

The system SHALL NOT store or return the OAuth tokens of connected apps.

#### Scenario: Listing shows no tokens

- **WHEN** a client lists connections
- **THEN** the response carries only what Nango's list endpoints return, with no credentials added by dash
