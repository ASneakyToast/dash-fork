# dash-brood

A [dash](../..) plugin. A mother squid lives in a panel on the right of dash. She is dash. Each running job hatches a small squid that swims near her, and she changes color and mood with the state of the queue.

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

On a phone, or any screen under 900 px wide, the panel is a **Brood** tab instead of a side panel.

To bake it into the Docker image, build with `--build-arg PLUGINS=./examples/dash-brood`.

Or without installing: `PYTHONPATH=examples/dash-brood/src DASH_PLUGINS=dash_brood:plugin uv run dash serve`.

`dash worker` loads the same plugin, so install it in both processes.

## What it shows about the plugin API

- `routes`: `GET /api/plugins/brood/mother` computes the mood in Python, where it is testable.
- `static`, `script`, `style`: the panel is a plain ES module and a stylesheet, with no build step.
- The browser module calls `dash.addDock` for the panel and `dash.onActivity` for the live feed of job state changes.
- `dash.openConversation` lets a click on a squid open its chat.
- `tokens`, `themes` and `dash.theme` add design tokens and a whole theme, and read them from the canvas.

## Theming

The panel is themed like the rest of dash, and it shows what a plugin does for theming:

- `tokens`: 19 `brood.*` tokens, with a light and a dark value each where the tank should differ. They cover the water, the sea floor, the light, the eggs, the pearl and the five moods.
- `themes`: `tidepool`, a dark-only theme that recolors dash itself in deep-sea teal. A plugin can ship a theme for the whole app.
- `palette.js` lists every token the drawing code reads. `art.js` has no color literals except the per-job squid hues, which come from a hash of the job id and are data, not theme.
- `dash.theme.onChange` re-reads the palette, so the tank changes color the moment the theme or the mode does.

See [docs/theming.md](../../docs/theming.md).

## Tests

```sh
uv run --with-editable ./examples/dash-brood pytest examples/dash-brood
node --test "examples/dash-brood/tests/*.test.js"
```
