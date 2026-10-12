# Writing a dash plugin

A plugin is a Python package that dash finds at startup. It can add API routes, a tab or a side panel to the web UI, code that runs when dash starts, and a listener for what the worker does. [`examples/dash-brood`](../examples/dash-brood) is a complete one: a mother squid in a side panel, with one small squid per running job.

## What a plugin can do

| To add | Declare | Runs in |
|---|---|---|
| API routes, at `/api/plugins/<name>/…` | `routes` | `dash serve` |
| Files for the browser, at `/plugins/<name>/…` | `static`, `script`, `style` | the browser |
| A tab or a side panel in the UI | `dash.addTab`, `dash.addDock` in the `script` | the browser |
| Setup and teardown, such as a client or a background task | `lifespan` | `dash serve` and `dash worker` |
| A reaction to a job changing state | `on_activity` | `dash worker` |
| A live view of job state changes | `dash.onActivity` in the `script` | the browser |
| Design tokens, and whole themes | `tokens`, `themes` | `dash serve`, applied in the browser |

Every part is optional. A plugin that only listens for failures has just `name` and `on_activity`.

## The smallest plugin

```python
from pathlib import Path

from dash.plugins import Plugin

plugin = Plugin(name="hello", static=Path(__file__).parent / "static", script="hello.js")
```

```js
export default function setup(dash) {
  dash.addTab({
    id: "main",
    title: "Hello",
    mount(root) {
      root.textContent = "Hello from a plugin.";
    },
  });
}
```

Register it in your `pyproject.toml`:

```toml
[project]
name = "dash-hello"
dependencies = ["dash"]

[project.entry-points."dash.plugins"]
hello = "dash_hello:plugin"
```

The entry point can name a `Plugin`, or a function that returns one.

## Installing and turning plugins off

Install the package into the same environment as dash. Do it for `dash serve` and `dash worker`: they are separate processes, and each loads plugins on its own.

| Env var | Meaning |
|---|---|
| `DASH_PLUGINS` | Extra `module:attribute` references to load without installing. For development. A plugin that is both installed and listed loads once. |
| `DASH_PLUGINS_DISABLED` | Entry point names or references to skip. A skipped plugin is not imported. |

The Apps tab lists every plugin, and the reason for any that failed to load.

## The Python API

```python
Plugin(
    name="brood",
    version="0.1.0",
    api=1,
    routes=lambda ctx: router,
    lifespan=lambda ctx: some_async_context_manager,
    on_activity=handler,
    static=Path("static"),
    script="brood.js",
    style="brood.css",
    tokens=[Token("brood.water.top", "#4aa6d6", "#134069")],
    themes=[Theme.load(Path("tidepool.json"))],
)
```

- `name` is lower case, starts with a letter, and is at most 32 characters of `a-z 0-9 _ -`. It is the plugin's URL prefix, so two plugins cannot share it.
- `api` is the plugin API version the plugin was written for. dash refuses a plugin that needs a different one, with a message in the Apps tab. It is `1` today.
- `routes(ctx)` returns an `APIRouter`. dash mounts it under `/api/plugins/<name>`, so a plugin cannot shadow a core route.
- `lifespan(ctx)` returns an async context manager, the same shape as a Starlette lifespan. If it raises while starting, dash logs it and carries on without it.
- `on_activity(ctx, activity)` is awaited for each state change the worker reports. It is cut off after 5 seconds, and an exception is logged and swallowed.
- `static` is a directory. `script` and `style` are file names inside it.
- `tokens` and `themes` add design tokens and whole themes. `name` must not be `dash`, because tokens use it. See [theming.md](theming.md).

`ctx` is a `Context`:

| Field | Meaning |
|---|---|
| `process` | `"api"` or `"worker"`. A `lifespan` runs in both, so it can tell which. |
| `store` | The database `Store`. |
| `queue` | The Redis `Queue`. |

### Activity

The worker publishes a state change to the capped Redis stream `dash:activity` and to each plugin's `on_activity`.

| `kind` | `data` | When |
|---|---|---|
| `started` | `{}` | The worker picked the job up. |
| `recalled` | `{"count": n}` | Memories were found for the message. |
| `waiting` | `{"title": "…"}` | The agent asked permission to run a tool. The job waits for the user. |
| `answered` | `{"option_id": "…"}` | The user answered. `null` means not allowed. |
| `cancelling` | `{}` | The user pressed Stop. |
| `done` | `{"stop": "…"}` | The reply is saved. `stop` is the ACP stop reason, such as `end_turn` or `cancelled`. |
| `failed` | `{"message": "…"}` | The job could not be answered. |
| `remembered` | `{"count": n}` | New memories were stored after the reply. |

An `Activity` also has `id`, `job_id`, `conversation_id` and `at` (Unix seconds). `queue.recent_activity(n)` returns the last `n`. The API streams the feed at `GET /api/activity` as server-sent events. It replays the last 50 on connect and resumes from `Last-Event-ID` after a drop.

## The browser API

`script` is an ES module. Its default export is called once, with the host object `dash`:

| Member | Does |
|---|---|
| `dash.addTab({id, title, mount(root)})` | Adds a tab. `mount` runs the first time it opens. |
| `dash.addDock({id, title, mount(root)})` | Mounts a panel in the permanent right-hand dock. The dock shows once a plugin adds one. Under 900 px wide the panel moves to a tab with the same title, so it works on a phone too. |
| `dash.onActivity(fn)` | Calls `fn` with each activity event, starting with the recent ones the page already has. Returns an unsubscribe function. |
| `dash.openConversation(id)` | Switches to Chat and opens the conversation. |
| `dash.conversations()` | Returns the conversation list. |
| `dash.plugin.api(path, opts)` | Calls your own routes: `dash.plugin.api("/mother")` fetches `/api/plugins/<name>/mother`. |
| `dash.api(path, opts)` | Calls any dash API route. |
| `dash.theme` | Reads design tokens (`dash.theme.get("brood.water.top")`) and reports theme changes. See [theming.md](theming.md). |
| `dash.el(tag, props, ...children)`, `dash.config` | A small DOM helper, and the server config. |

Tab and dock ids are prefixed with the plugin name, so ids never clash. A callback that throws is caught and logged to the console under the plugin's name. A plugin whose script fails to load shows as an error in the Apps tab, and the rest of the UI keeps working.

## Putting a plugin in the Docker image

The image only has what is installed in it. Pass plugin paths or package names as the `PLUGINS` build argument, and they are installed into the image's virtual environment:

```sh
docker build --build-arg PLUGINS=./examples/dash-brood -t dash .
```

`dash serve` and `dash worker` run from the same image, so both load the plugin. With no argument, nothing extra is installed.

## Testing a plugin

Build the app with your plugin and the in-memory fakes from dash's own tests:

```python
from dash.plugins import discover
from dash.web import create_app

app = create_app(
    store=store,
    queue=queue,
    embedder=embedder,
    nango=nango,
    plugins=discover(["dash_hello:plugin"]),
)
```

`examples/dash-brood/tests` shows this, and tests a pure function on its own. The brood's state logic is a plain JS module with `node --test` tests. Keeping logic out of the DOM code is what makes it testable without a browser.

## Trust model

A plugin is arbitrary code. In the server it runs in-process with full access to the database, Redis and every secret in the environment. In the browser it runs same-origin with the page, so it can call any dash API. dash loads every plugin installed in its environment, as pytest does, so treat `pip install` of a plugin like any dependency. `DASH_PLUGINS_DISABLED` is the off switch.

Isolation covers failure, not hostility: a plugin that crashes, hangs or has a bad version cannot take dash down, but a malicious one is not contained. A registry of third-party plugins would need more: an iframe for plugin UI, and declared permissions.

## Not built yet

These came up and were left out of the prototype on purpose:

- **Plugin tables.** A plugin can use `ctx.store.sessions` but has no way to ship a migration. The likely answer is an alembic branch per plugin.
- **Settings.** Plugins read their own env vars. A declared settings schema would let the UI show a form.
- **Hooks in the chat path**, such as editing the system prompt or adding a tool before a reply. These need a stable, narrow interface, so they wait for a real plugin that needs one.
- **GitHub as a plugin.** `dash.github` is the natural second one to move over. It is the test of whether this API is enough.
- **A stable activity contract.** The kinds above are API version 1. Adding a kind is compatible. Renaming one needs `api = 2`.
