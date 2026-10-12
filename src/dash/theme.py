"""Design tokens and themes: the token vocabulary, theme files, and the stylesheet dash serves."""

import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from functools import lru_cache
from itertools import accumulate
from pathlib import Path
from typing import Any, Literal, cast

log = logging.getLogger(__name__)

Mode = Literal["light", "dark"]

MODES: tuple[Mode, ...] = ("light", "dark")
CORE = "dash"
MIN_CONTRAST = 4.5
CONTRAST_PAIRS = (
    ("dash.color.text", "dash.color.bg"),
    ("dash.color.text", "dash.color.surface"),
    ("dash.color.text-muted", "dash.color.bg"),
    ("dash.color.text-muted", "dash.color.surface"),
    ("dash.color.on-accent", "dash.color.accent"),
    ("dash.color.danger", "dash.color.surface"),
)
HERE = Path(__file__).parent
THEME_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
TOKEN_NAME = re.compile(r"^[a-z][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+$")
LEGACY_VAR = re.compile(r"^--[a-z][a-z0-9-]*$")
SAFE_VALUE = re.compile(r"""[\w #%.,()/+*'"-]{1,200}""")
FORBIDDEN = ("/*", "url(", "expression(")
HEX_COLOR = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$", re.IGNORECASE)
VAR_REF = re.compile(r"^var\((--[a-z0-9-]+)\)$")


def balanced(value: str) -> bool:
    """Return True if every parenthesis in the value is closed."""
    depth = list(accumulate(1 if ch == "(" else -1 if ch == ")" else 0 for ch in value))
    return min(depth, default=0) >= 0 and (not depth or depth[-1] == 0)


def check_value(label: str, value: str) -> str:
    """Return the value if it is safe to write into a stylesheet, or raise ValueError."""
    lowered = value.lower()
    if (
        not SAFE_VALUE.fullmatch(value)
        or any(bad in lowered for bad in FORBIDDEN)
        or value.count('"') % 2
        or value.count("'") % 2
        or not balanced(value)
    ):
        raise ValueError(f"{label}: {value!r} is not a safe CSS value.")
    return value


def check_name(name: str) -> str:
    """Return the token name if it is well formed, or raise ValueError."""
    if not TOKEN_NAME.fullmatch(name):
        raise ValueError(f"{name!r} is not a token name such as 'dash.color.bg'.")
    return name


@dataclass(frozen=True)
class Leaf:
    """A token as written in a token file."""

    value: str
    type: str | None = None
    description: str = ""
    legacy: str | None = None


def as_group(node: object, label: str) -> dict[str, Any]:
    """Return the node as a dict, or raise ValueError."""
    if not isinstance(node, dict):
        raise ValueError(f"{label or 'the file'} is not a token group.")
    return cast("dict[str, Any]", node)


def leaf_of(node: dict[str, Any], label: str, kind: str | None) -> Leaf:
    """Return the token that a node with a `$value` describes."""
    value = node["$value"]
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise ValueError(f"{label}: only a string or number $value is supported.")
    ours = as_group(node.get("$extensions", {}), label).get("dev.dash", {})
    legacy: str | None = as_group(ours, label).get("legacy")
    return Leaf(str(value), node.get("$type", kind), str(node.get("$description", "")), legacy)


def flatten(node: object, path: tuple[str, ...] = (), kind: str | None = None) -> dict[str, Leaf]:
    """Return the tokens in a DTCG group, keyed by dotted name."""
    label = ".".join(path)
    group = as_group(node, label)
    kind = group.get("$type", kind)
    if "$value" in group:
        return {check_name(label): leaf_of(group, label, kind)}
    return {
        name: leaf
        for key, child in group.items()
        if not key.startswith("$")
        for name, leaf in flatten(child, (*path, key), kind).items()
    }


def values_of(group: object) -> dict[str, str]:
    """Return the value of every token in a DTCG group, keyed by dotted name."""
    return {name: leaf.value for name, leaf in flatten(group).items()}


@dataclass(frozen=True)
class Token:
    """A design token: a name, a type, and its value in each mode."""

    name: str
    light: str
    dark: str | None = None
    type: str = "color"
    description: str = ""
    legacy: str | None = None

    def __post_init__(self) -> None:
        check_name(self.name)
        check_value(self.name, self.light)
        if self.dark is not None:
            check_value(self.name, self.dark)
        if self.legacy is not None and not LEGACY_VAR.fullmatch(self.legacy):
            raise ValueError(f"{self.name}: {self.legacy!r} is not a CSS variable name.")

    @property
    def var(self) -> str:
        """Return the CSS custom property that carries the token."""
        return "--" + self.name.replace(".", "-")

    @property
    def owner(self) -> str:
        """Return the first segment of the name: `dash`, or the plugin that declared it."""
        return self.name.split(".")[0]

    def value(self, mode: Mode) -> str:
        """Return the token's value in the mode."""
        return self.dark if mode == "dark" and self.dark is not None else self.light


@dataclass(frozen=True)
class Theme:
    """A named set of token values for light mode, dark mode, or both."""

    name: str
    title: str
    light: Mapping[str, str] = field(default_factory=dict[str, str])
    dark: Mapping[str, str] = field(default_factory=dict[str, str])
    source: str = ""

    def __post_init__(self) -> None:
        if not THEME_NAME.fullmatch(self.name):
            raise ValueError(f"{self.name!r} is not a valid theme name.")
        if not (self.light or self.dark):
            raise ValueError(f"theme {self.name} sets no tokens.")
        for mode in MODES:
            for name, value in self.values(mode).items():
                check_value(f"{self.name} {mode} {check_name(name)}", value)

    @property
    def modes(self) -> tuple[Mode, ...]:
        """Return the modes the theme sets tokens for."""
        return tuple(mode for mode in MODES if self.values(mode))

    def values(self, mode: Mode) -> Mapping[str, str]:
        """Return the theme's token values for the mode."""
        return self.light if mode == "light" else self.dark

    @classmethod
    def from_json(cls, text: str, default_name: str | None = None) -> "Theme":
        """Return the theme that a theme file describes."""
        doc = as_group(json.loads(text), "")
        name = doc.get("name", default_name)
        if not isinstance(name, str):
            raise ValueError("a theme file needs a name.")
        title = doc.get("title", name)
        if not isinstance(title, str):
            raise ValueError("a theme title must be a string.")
        return cls(name, title, values_of(doc.get("light", {})), values_of(doc.get("dark", {})))

    @classmethod
    def load(cls, path: Path) -> "Theme":
        """Return the theme in the JSON file."""
        return cls.from_json(path.read_text("utf-8"))


@lru_cache
def core_tokens() -> tuple[Token, ...]:
    """Return the tokens that dash itself defines."""
    doc = as_group(json.loads((HERE / "tokens.json").read_text("utf-8")), "")
    light = flatten(doc["light"])
    dark = values_of(doc["dark"])
    return tuple(
        Token(name, leaf.value, dark.get(name), leaf.type or "color", leaf.description, leaf.legacy)
        for name, leaf in light.items()
    )


@lru_cache
def builtin_themes() -> tuple[Theme, ...]:
    """Return the themes that ship with dash."""
    return tuple(
        replace(Theme.load(path), source=CORE) for path in sorted((HERE / "themes").glob("*.json"))
    )


def load_overrides(path: str) -> Theme | None:
    """Return the user's overrides from the file, or None if there are none or they are invalid."""
    if not path:
        return None
    try:
        return Theme.from_json(Path(path).read_text("utf-8"), "overrides")
    except (OSError, ValueError):
        log.exception("theme overrides %s were not loaded", path)
        return None


def rgb(value: str) -> tuple[float, float, float] | None:
    """Return the red, green and blue of a hex color as fractions, or None for any other value."""
    match = HEX_COLOR.fullmatch(value.strip())
    if match is None:
        return None
    digits = match[1] if len(match[1]) == 6 else "".join(ch * 2 for ch in match[1])
    r, g, b = (int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return r, g, b


def luminance(color: tuple[float, float, float]) -> float:
    """Return the WCAG relative luminance of an sRGB color."""
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Return the WCAG contrast ratio between two colors."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class ThemeSet:
    """The tokens and themes dash serves, and the stylesheet built from them."""

    def __init__(
        self, tokens: Iterable[Token], themes: Iterable[Theme], overrides: Theme | None = None
    ) -> None:
        self.tokens = tuple(tokens)
        self.themes = tuple(themes)
        self.overrides = overrides
        self.by_name = {token.name: token for token in self.tokens}
        self.by_var = {token.var: token for token in self.tokens}
        self.warnings = {theme.name: self.audit(theme) for theme in self.themes}
        self.override_warnings = self.unknown(overrides) if overrides else []
        self.css = self.render()

    def unknown(self, theme: Theme) -> list[str]:
        """Return a warning for each token in the theme that no loaded plugin declares."""
        names = sorted({name for mode in MODES for name in theme.values(mode)})
        return [f"unknown token {name}" for name in names if name not in self.by_name]

    def resolved(self, mode: Mode, overlay: Mapping[str, str]) -> dict[str, str]:
        """Return every token's value in the mode, with the overlay applied on top."""
        return {t.name: overlay.get(t.name, t.value(mode)) for t in self.tokens}

    def follow(self, values: Mapping[str, str], name: str) -> str:
        """Return the value of the token, following `var(--other)` references."""
        value = values.get(name, "")
        for _ in range(8):
            ref = VAR_REF.fullmatch(value.strip())
            target = self.by_var.get(ref[1]) if ref else None
            if target is None:
                break
            value = values.get(target.name, "")
        return value

    def audit(self, theme: Theme) -> list[str]:
        """Return the problems with a theme: unknown tokens and text that is hard to read."""
        warnings = self.unknown(theme)
        for mode in theme.modes:
            values = self.resolved(mode, theme.values(mode))
            for fg, bg in CONTRAST_PAIRS:
                front, back = rgb(self.follow(values, fg)), rgb(self.follow(values, bg))
                if front and back and (ratio := contrast(front, back)) < MIN_CONTRAST:
                    warnings.append(
                        f"{fg} on {bg} is {ratio:.1f}:1 in {mode} mode, below {MIN_CONTRAST}:1"
                    )
        return warnings

    def block(self, values: Mapping[str, str], scheme: Mode | None) -> str:
        """Return the declarations that set the values, in token order."""
        lines = [f"{t.var}: {values[t.name]};" for t in self.tokens if t.name in values]
        if lines and scheme:
            lines.append(f"color-scheme: {scheme};")
        return " ".join(lines)

    def rules(self, selector: str, theme: Theme | None, scheme: bool) -> list[str]:
        """Return the four rules that apply a theme's values: either mode set, or by the system."""
        light, dark = (
            (theme.light, theme.dark)
            if theme
            else ({t.name: t.value("light") for t in self.tokens}, self.resolved("dark", {}))
        )
        body = {
            "light": self.block(light, "light" if scheme else None),
            "dark": self.block(dark, "dark" if scheme else None),
        }
        queries = {
            "light": "not all and (prefers-color-scheme: dark)",
            "dark": "(prefers-color-scheme: dark)",
        }
        return [
            *(f'{selector}[data-mode="{mode}"] {{ {body[mode]} }}' for mode in MODES if body[mode]),
            *(
                f"@media {queries[mode]} {{ {selector}:not([data-mode]) {{ {body[mode]} }} }}"
                for mode in MODES
                if body[mode]
            ),
        ]

    def aliases(self) -> str:
        """Return the rule that keeps the old variable names working."""
        lines = [f"{t.legacy}: var({t.var});" for t in self.tokens if t.legacy]
        return f":root {{ {' '.join(lines)} }}" if lines else ""

    def render(self) -> str:
        """Return the stylesheet: base values, then each theme, then the user's overrides."""
        base = [self.aliases(), *self.rules(":root", None, scheme=True)]
        themes = [
            rule
            for theme in self.themes
            for rule in self.rules(f':root[data-theme="{theme.name}"]', theme, scheme=True)
        ]
        user = self.rules(":root", self.overrides, scheme=False) if self.overrides else []
        layers = (("dash-base", base), ("dash-theme", themes), ("dash-user", user))
        return (
            "\n".join(
                ["@layer dash-base, dash-theme, dash-user;"]
                + [
                    f"@layer {name} {{\n" + "\n".join(f"  {r}" for r in rules if r) + "\n}"
                    for name, rules in layers
                ]
            )
            + "\n"
        )

    def manifest(self) -> dict[str, Any]:
        """Return what the browser needs to know about tokens and themes."""
        return {
            "tokens": [
                {
                    "name": t.name,
                    "var": t.var,
                    "type": t.type,
                    "owner": t.owner,
                    "description": t.description,
                }
                for t in self.tokens
            ],
            "themes": [
                {
                    "name": theme.name,
                    "title": theme.title,
                    "source": theme.source,
                    "modes": list(theme.modes),
                    "warnings": self.warnings[theme.name],
                }
                for theme in self.themes
            ],
            "overrides": {"warnings": self.override_warnings} if self.overrides else None,
        }
