# dash

An always-on assistant in front of [hermes-agent](https://github.com/whatever/geometry.dev/tree/main/apps/hermes-agent).

| Part | What it does |
|---|---|
| Web UI (`src/dash/static`) | Chat, memories (list, search, add, delete), connected apps, and queue status. No build step. |
| API (`dash serve`) | FastAPI. Stores each user message, then adds a job to the Redis stream `dash:jobs`. |
| Worker (`dash worker`) | Reads `dash:jobs`, recalls memories from pgvector, and streams the hermes reply. Then it extracts new memories. |
| Memories | Postgres + pgvector. Bedrock Titan v2 makes the embeddings. Bedrock Haiku extracts the facts. |
| App keys | A self-hosted [Nango](https://nango.dev). Nango holds the OAuth tokens. dash and hermes ask Nango for them. |
| Plugins (`src/dash/plugins.py`) | Python packages that add routes, UI tabs or a side panel, and listeners for what the worker does. See [docs/plugins.md](docs/plugins.md). |
| GitHub (`src/dash/github`) | Creates a private GitHub App from a manifest and stores its keys in the `authorizations` table. Use `app_client` and `installation_client` to call GitHub. |

The browser follows a reply through `GET /api/jobs/<id>/events` (SSE). The worker writes each reply to its own Redis stream, so a page reload replays the reply from the start.

The worker also appends each state change of a job to the capped stream `dash:activity`. `GET /api/activity` (SSE) replays the recent entries and follows new ones. Plugins build on it.

## Run locally

The compose stack runs everything, Nango included. Nango needs `NANGO_ENCRYPTION_KEY` in `.env`. Make it with `openssl rand -base64 32`.

```sh
cp .env.example .env   # then set NANGO_ENCRYPTION_KEY
just up                # also: just down, just nuke, just logs [service], just ps
```

Then open http://localhost:8000 (dash) and http://localhost:3003 (Nango, user `admin`). See `compose.yaml` for the other ports.

To run dash outside Docker:

```sh
docker run -d --name pg -p 5432:5432 -e POSTGRES_PASSWORD=dash pgvector/pgvector:pg16
docker run -d --name redis -p 6379:6379 redis:8-alpine
export DATABASE_URL=postgresql://postgres:dash@localhost:5432/postgres
export HERMES_BASE_URL=http://localhost:8642/v1 HERMES_API_KEY=...
uv run dash migrate
uv run dash worker &
uv run dash serve
```

The worker needs AWS credentials for Bedrock in the standard env chain. Outside Docker, Nango is optional. To use it, set `NANGO_URL` and `NANGO_SECRET_KEY`.

## Plugins

A plugin is a Python package that registers a `dash.plugins` entry point. Install it next to dash, in the environment of both `dash serve` and `dash worker`, and it loads at startup. A plugin that fails to load is listed with its error in the Apps tab, and dash keeps running.

[`examples/dash-brood`](examples/dash-brood) is a full example: a mother squid in a phone-shaped panel on the right, with one small squid for each running job.

```sh
uv pip install -e examples/dash-brood
uv run dash serve
```

[docs/plugins.md](docs/plugins.md) covers the API, the trust model, and what is not built yet.

## GitHub

In the Apps tab, click **Create GitHub App**. Type an organization, or leave it empty for your personal account.

1. dash sends a manifest to GitHub. The manifest has the name, permissions, and redirect URLs.
2. On GitHub, you confirm the app. GitHub sends you back to `/github/callback` with a code.
3. dash exchanges the code for the app ID, private key, client secret, and webhook secret. Then it stores them.
4. GitHub opens the install page. After you install, `/github/setup` copies the installations from GitHub.

dash stores the private key and secrets as plain JSONB. Protect the database.

## Settings

| Env var | Default |
|---|---|
| `DATABASE_URL` | (required) |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `PUBLIC_URL` | Browser-facing dash address for GitHub redirects. Empty means the request address. |
| `HERMES_BASE_URL`, `HERMES_API_KEY`, `HERMES_MODEL` | `http://localhost:8642/v1`, empty, `hermes-opus` |
| `NANGO_URL`, `NANGO_SECRET_KEY` | `http://localhost:3003`, empty (disabled) |
| `NANGO_PUBLIC_URL`, `NANGO_CONNECT_URL` | Browser-facing Nango API and Connect UI addresses |
| `EMBED_MODEL`, `EXTRACT_MODEL`, `MEMORY_TOP_K` | Titan v2, Haiku 4.5, `8` |
| `DASH_PLUGINS` | Comma-separated `module:attribute` plugins to load without installing them. Empty by default. |
| `DASH_PLUGINS_DISABLED` | Comma-separated plugin entry point names to skip. Empty by default. |
| `DASH_THEME_OVERRIDES` | Path to a JSON file of design token overrides, applied on top of every theme. See `docs/theming.md`. Empty by default. |

## Deploy

ArgoCD deploys dash from the Kustomize manifests in [`whatever/geometry.dev/apps/dash`](https://github.com/whatever/geometry.dev/tree/main/apps/dash). They run the API, the worker, Redis (AOF), Nango, ExternalSecrets, and the Traefik ingress. `compose.yaml` is the reference for these parts.

On each push to `main`, CI does these steps:
1. It publishes the image `ghcr.io/whatever/dash:sha-<short>`.
2. It sends an `image-published` dispatch to geometry.dev.
3. geometry.dev opens a PR that bumps the image tag in `apps/dash`.
4. When that PR merges, ArgoCD syncs the new image.

CI needs the `GEOMETRY_BUMP_CLIENT_ID` variable and the `GEOMETRY_BUMP_APP_KEY` secret. The GitHub App must be installed on geometry.dev with contents write access.

Before the first sync, do these steps:
1. On RDS, as the master user, create the `dash` and `nango` databases. Then run `CREATE EXTENSION vector` in `dash`.
2. Add `DASH_DATABASE_URL` and `NANGO_DATABASE_URL` to `geometry/config`.
3. Create `geometry/dash` with `NANGO_ENCRYPTION_KEY` and `NANGO_DASHBOARD_PASSWORD`. Make the key with `openssl rand -base64 32`. Do not rotate it.
4. After Nango starts for the first time, copy `NANGO_SECRET_KEY` from its dashboard into `geometry/dash` and `geometry/hermes`.

`hermes/skills/nango/SKILL.md` is the hermes skill for connected apps. To use it, copy it into your hermes skills.

## Checks

```sh
uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest
```

The example plugin has its own tests:

```sh
uv run --with-editable ./examples/dash-brood pytest examples/dash-brood
node --test "examples/dash-brood/tests/*.test.js"
```
