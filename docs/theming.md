# Theming dash

dash styles itself with design tokens. A token is a named value, such as `dash.color.bg`. dash writes each token as a CSS custom property (`--dash-color-bg`), and the UI and every plugin read them with `var()`. A theme is a set of token values. A plugin can add tokens, add whole themes, and read tokens from JavaScript.

## How it fits together

| Layer | Holds | Who writes it |
|---|---|---|
| `dash-base` | Every token's default, light and dark. | dash (`src/dash/tokens.json`) and each plugin's `tokens`. |
| `dash-theme` | The values of the theme that is selected. | dash's built-in themes and each plugin's `themes`. |
| `dash-user` | Your own overrides, on top of any theme. | You, in the file named by `DASH_THEME_OVERRIDES`. |

dash serves the layers as one stylesheet at `/api/theme.css`, in the order above, with `@layer dash-base, dash-theme, dash-user;`. A later layer wins whatever the selector specificity, so a plugin's CSS never needs `!important` to lose to a theme.

The page has two attributes on `<html>`. `data-theme` names the theme (absent means the default). `data-mode` is `light` or `dark` (absent means follow the system). The Apps tab has a picker, and the choice is kept in `localStorage`.

A theme that sets a token for only one mode leaves the other mode on the layer below. A theme that sets only `dark` is a dark-only theme: choosing it fixes the mode to dark, and the mode picker is disabled.

## Using tokens in a plugin

Read the tokens, and do not write your own colors.

```css
.my-panel {
  background: var(--dash-color-surface);
  color: var(--dash-color-text);
  border: 1px solid var(--dash-color-border);
  border-radius: var(--dash-radius-control);
}
```

### The tokens dash defines

These names are part of the plugin API. A token is never renamed or removed without a new `api` version.

| Token | CSS variable | Old name | Use |
|---|---|---|---|
| `dash.color.bg` | `--dash-color-bg` | `--bg` | The page background. |
| `dash.color.surface` | `--dash-color-surface` | `--panel` | Panels, the sidebar, inputs. |
| `dash.color.text` | `--dash-color-text` | `--text` | Body text. |
| `dash.color.text-muted` | `--dash-color-text-muted` | `--muted` | Secondary text and metadata. |
| `dash.color.border` | `--dash-color-border` | `--line` | Dividers and control borders. |
| `dash.color.accent` | `--dash-color-accent` | `--accent` | The active tab, focus and hover. |
| `dash.color.on-accent` | `--dash-color-on-accent` | | Text on an accent background. |
| `dash.color.bubble-user` | `--dash-color-bubble-user` | `--user` | The user's own messages. |
| `dash.color.danger` | `--dash-color-danger` | | Errors. |
| `dash.color.warning` | `--dash-color-warning` | | Something that waits for the user, such as a permission question. |
| `dash.color.success` | `--dash-color-success` | | A finished step, such as a completed tool call. |
| `dash.radius.control` | `--dash-radius-control` | | Buttons and inputs. |
| `dash.radius.bubble` | `--dash-radius-bubble` | | Message bubbles. |
| `dash.font.family` | `--dash-font-family` | | The body font stack. |
| `dash.font.size` | `--dash-font-size` | | The base font size. |

The old names (`--bg`, `--panel` and so on) still work. They are aliases of the new ones, kept so that plugins written before theming keep working. Use the new names in new code.

### Adding your own tokens

Declare a token when a plugin has a color that a theme might reasonably change. The name must start with the plugin's name.

```python
from dash.plugins import Plugin
from dash.theme import Token

plugin = Plugin(
    name="brood",
    tokens=[
        Token(
            "brood.water.top",
            light="#4aa6d6",
            dark="#134069",
            description="The water at the surface.",
        ),
        Token("brood.mood.busy", light="hsl(188 72% 62%)"),
    ],
)
```

- `dark` is optional. Without it the token has one value in both modes.
- A value can refer to another token: `Token("my.edge", "var(--dash-color-border)")`.
- The variable is `--` plus the name with dots turned into hyphens: `brood.water.top` is `--brood-water-top`. A plugin cannot declare a variable that another plugin or dash already uses, and a plugin that tries fails to load with that reason in the Apps tab.
- Prefer a few tokens that carry meaning (`brood.mood.busy`) over one per drawing call. A theme author has to set every one.

### Reading tokens from JavaScript

Canvas and other non-CSS code reads tokens through `dash.theme`:

| Member | Does |
|---|---|
| `dash.theme.get(name)` | Returns the token's current value as a string. It takes `"brood.water.top"` or a variable such as `"--brood-water-top"`. An unknown name throws. |
| `dash.theme.mode()` | Returns `"light"` or `"dark"`. |
| `dash.theme.onChange(fn)` | Calls `fn(mode)` after a theme or mode change, or a change of the system setting while the mode is automatic. Returns an unsubscribe function. |
| `dash.theme.themes()`, `.tokens()`, `.current()` | The theme list, the token list, and the `{theme, mode}` in use. |
| `dash.theme.select({theme, mode})` | Changes the theme or the mode, as the Apps tab picker does. |

Read the tokens again in `onChange` rather than keeping a copy. `examples/dash-brood/src/dash_brood/static/palette.js` is the pattern: one module lists every token name the drawing code uses, so a test can check that list against the plugin's declared tokens.

Values come back as authored (`#4aa6d6`, `hsl(268 58% 64%)`), and a canvas accepts any of them. To shade a color, use `color-mix()`, which a canvas also accepts: `color-mix(in oklab, ${color}, black 25%)`.

## Writing a theme

A theme file is JSON: a `name`, a `title`, and a group of tokens for each mode. Each group is in the [Design Tokens Community Group format](https://www.designtokens.org/), with the dotted token name written as nested groups.

```json
{
  "name": "tidepool",
  "title": "Tidepool",
  "dark": {
    "dash": {
      "color": {
        "bg": { "$type": "color", "$value": "#06141f" },
        "text": { "$type": "color", "$value": "#e6f4ff" }
      }
    }
  }
}
```

A plugin ships it with `themes=[Theme.load(Path(__file__).parent / "tidepool.json")]`. A theme can also be built in Python: `Theme("sunny", "Sunny", light={"dash.color.bg": "#fffbe6"})`. dash's own built-in theme is `src/dash/themes/high-contrast.json`.

A theme can set any token, dash's or any plugin's. Tokens it does not set keep the layer below's value. A token that no loaded plugin declares is ignored and shown as a warning in the Apps tab, so a theme that targets a plugin you have not installed does no harm.

The theme name is lower case, starts with a letter, and is at most 32 characters of `a-z 0-9 _ -`. It must not clash with a built-in theme or another plugin's.

### Checks

- **Safe values.** A value can use letters, digits, spaces and `# % . , ( ) / + * ' " -`. It must not contain `;`, `{`, `}`, `/*`, `url(`, an unbalanced parenthesis or an odd number of quotes. A theme or token that breaks this raises `ValueError` when it is built, so a plugin that ships one fails to load. This keeps a value from escaping its declaration into the rest of the stylesheet.
- **Contrast.** For each mode a theme sets, dash checks six pairs, such as `dash.color.text` on `dash.color.bg`, against the WCAG 4.5:1 minimum for body text. A failure is a warning shown in the Apps tab, and the theme still loads. The check reads `#rgb` and `#rrggbb` values and follows `var(--token)` references. It skips any other color syntax, so `oklch()` and `color-mix()` values are not checked.

## Your own overrides

Set `DASH_THEME_OVERRIDES` to a JSON file in the same format. `name` is optional. Its values apply to every theme, on top of it.

```json
{
  "light": { "dash": { "color": { "accent": { "$value": "#7c3aed" } } } },
  "dark":  { "dash": { "color": { "accent": { "$value": "#c4b5fd" } } } }
}
```

dash reads the file at startup, so restart `dash serve` after editing it. If the file is missing or invalid, dash logs why and runs without it.

## Compatibility

Theming adds to plugin API version 1, and does not change what a version 1 plugin can do. The token names above are API: adding one is compatible. Renaming or removing one needs `api = 2`, and the old name stays as an alias until then.

## Not built yet

- The DTCG Resolver document format. A theme file has a group per mode, which covers light and dark. Multi-axis themes, such as brand by density by mode, would need the Resolver.
- DTCG object color values (`{ "colorSpace": "srgb", ... }`). Use CSS color strings.
- `@property` registration, which would give typed values and animated theme changes.
- A default theme chosen by the server. The choice is per browser.
- Themes for plugin UI that is not in the page. A plugin that moved into an iframe would have to be sent the tokens.
