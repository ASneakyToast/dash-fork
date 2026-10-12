# github-apps Specification

## Purpose

Create private GitHub Apps from inside dash, install them, and keep their credentials so other features can act as the app or as one of its installations.

## Requirements

### Requirement: A GitHub App is created from a manifest

The system SHALL return a GitHub App manifest for a private app named by the request (default `dash`, 1 to 34 characters), with permissions `metadata: read`, `contents: read`, `issues: write` and `pull_requests: write`, and no webhook events.

#### Scenario: Default manifest

- **WHEN** a client posts to `/api/github/manifest` with no name
- **THEN** the manifest is for a non-public app named `dash` with exactly those permissions and no default events

### Requirement: The manifest points back at dash

The manifest's URLs SHALL be built on `PUBLIC_URL`, or on the request's base URL when that is unset. The response SHALL also give the GitHub URL that receives the manifest: the organization's app settings when an `org` is given, otherwise the user's.

#### Scenario: Personal account

- **WHEN** a client posts to `/api/github/manifest` with no `org`
- **THEN** `action` is `https://github.com/settings/apps/new?state=<state>` and the manifest's `redirect_url` is `<base>/github/callback` and `setup_url` is `<base>/github/setup`

#### Scenario: Organization

- **WHEN** a client posts with `org` set to `acme`
- **THEN** `action` is `https://github.com/organizations/acme/settings/apps/new?state=<state>`

#### Scenario: Invalid organization name

- **WHEN** a client posts an `org` that is not a valid GitHub organization name
- **THEN** the request is rejected

### Requirement: Creation is bound to the browser that started it

The system SHALL set a random `state` in an `HttpOnly`, `SameSite=Lax` cookie scoped to `/github`, valid for ten minutes and marked `Secure` only when the base URL is HTTPS, and SHALL put the same `state` in the GitHub URL.

#### Scenario: State cookie

- **WHEN** a manifest is requested
- **THEN** the response sets a `github_manifest_state` cookie equal to the `state` in `action`

### Requirement: The callback stores the new app

When GitHub redirects back with a `code` and `state`, the system SHALL check the state against the cookie. If they match, it SHALL exchange the code for the app, store the app and its credentials, clear the cookie, and redirect with 303 to the app's installation page on GitHub.

#### Scenario: Matching state

- **WHEN** the callback has a state equal to the cookie
- **THEN** the app is stored and the response is a 303 to `<app html_url>/installations/new`

#### Scenario: Missing or wrong state

- **WHEN** the cookie is absent or differs from `state`
- **THEN** the response is 400 and nothing is stored

#### Scenario: GitHub refuses the code

- **WHEN** GitHub returns an error for the code
- **THEN** the response is 502 naming GitHub and nothing is stored

### Requirement: Installations are copied from GitHub

The system SHALL replace the stored installations of every stored app with the list GitHub returns, removing ones GitHub no longer lists. It SHALL do so when GitHub redirects to `/github/setup` (then redirect with 303 to `/#apps`) and when a client posts to `/api/github/sync` (which returns the current list).

#### Scenario: Installed after creation

- **WHEN** the user finishes installing an app and GitHub redirects to `/github/setup`
- **THEN** the app's installations are stored and the response is a 303 to `/#apps`

#### Scenario: Uninstalled on GitHub

- **WHEN** an installation is gone on GitHub and a sync runs
- **THEN** it is no longer stored or listed

#### Scenario: GitHub fails during sync

- **WHEN** GitHub returns an error during a sync
- **THEN** the response is 502 naming GitHub

### Requirement: Apps and installations can be listed without their secrets

The system SHALL list stored apps, each with its installations, at `/api/github`. The response SHALL include an app's id, GitHub app id, owner, slug, name and URL, and each installation's id, account and URL. It SHALL NOT include the private key, client secret or webhook secret.

#### Scenario: Listing

- **WHEN** a client lists apps after creating and installing one
- **THEN** the app appears with its installation, and no secret appears anywhere in the response

### Requirement: Apps can be forgotten

The system SHALL delete a stored app and its installations by id and return 204, or 404 if there is none. Deleting it SHALL NOT touch the app on GitHub.

#### Scenario: Unknown app

- **WHEN** a client deletes an app id that is not stored
- **THEN** the response is 404

### Requirement: Stored credentials can act as the app or an installation

The system SHALL provide GitHub clients built from a stored app, authenticating as the app, or from a stored app and one of its installations, authenticating as that installation.

#### Scenario: Installation client

- **WHEN** a client is built for a stored installation
- **THEN** it authenticates with the app's GitHub id, the installation's GitHub id, and the app's stored client id, key and secret
