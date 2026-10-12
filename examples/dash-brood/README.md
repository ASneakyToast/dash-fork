# dash-brood

A [dash](../..) plugin. A mother squid lives in a phone-shaped panel on the right of dash. She is dash. Each running job hatches a small squid that swims near her, and she changes color and mood with the state of the queue.

| In the panel | Means |
|---|---|
| A small squid swimming | A job is running. Click it to open its conversation. |
| A squid with a thought bubble | The worker recalled memories for the job. |
| A squid that hops, then sleeps on the sea floor | The job finished. |
| A gray squid, upside down | The job failed. |
| An egg on the sea floor | A job is waiting in the queue. |
| A pearl that rises to the mother | A new memory was stored. |
| The mother is violet, teal, orange, green, or asleep | Content, busy, strained, unwell, or no worker running. |

## Try it

```sh
uv pip install -e examples/dash-brood
uv run dash serve
```

Or without installing: `PYTHONPATH=examples/dash-brood/src DASH_PLUGINS=dash_brood:plugin uv run dash serve`.

`dash worker` loads the same plugin, so install it in both processes.

## What it shows about the plugin API

- `routes`: `GET /api/plugins/brood/mother` computes the mood in Python, where it is testable.
- `static`, `script`, `style`: the panel is a plain ES module and a stylesheet, with no build step.
- The browser module calls `dash.addDock` for the panel and `dash.onActivity` for the live feed of job state changes.
- `dash.openConversation` lets a click on a squid open its chat.

## Tests

```sh
uv run --with-editable ./examples/dash-brood pytest examples/dash-brood
node --test "examples/dash-brood/tests/*.test.js"
```
