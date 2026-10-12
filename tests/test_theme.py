import json
import re
from pathlib import Path
from typing import cast

import fakeredis
import pytest
from fastapi.testclient import TestClient

from dash.db import Store
from dash.nango import Nango
from dash.plugins import Plugins, discover
from dash.queue import Queue
from dash.theme import (
    Theme,
    ThemeSet,
    Token,
    balanced,
    builtin_themes,
    check_value,
    contrast,
    core_tokens,
    flatten,
    load_overrides,
    rgb,
)
from dash.web import create_app
from tests.fakes import FakeEmbedder, FakeStore

F = "tests.plugin_fixtures"
BG = "dash.color.bg"


def make_client(plugins: Plugins, overrides: Theme | None = None) -> TestClient:
    app = create_app(
        store=cast("Store", FakeStore()),
        queue=Queue(fakeredis.FakeAsyncRedis(decode_responses=True)),
        embedder=FakeEmbedder(),
        nango=Nango("http://nango.invalid", ""),
        plugins=plugins,
        overrides=overrides,
    )
    return TestClient(app)


def themes_of(*themes: Theme, overrides: Theme | None = None) -> ThemeSet:
    return ThemeSet(core_tokens(), themes, overrides)


@pytest.mark.parametrize(
    "value",
    [
        "red; } body { display: none",
        "url(https://x.test/a.png)",
        "a /* b",
        "rgb(0 0 0",
        "'open",
        "{x}",
        "a\nb",
    ],
)
def test_a_value_that_could_break_out_of_a_declaration_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="not a safe CSS value"):
        check_value("x", value)


@pytest.mark.parametrize(
    "value",
    [
        "#fafaf9",
        "rgb(0 0 0 / 50%)",
        "color-mix(in oklab, #fff 20%, black)",
        "system-ui, 'Segoe UI', sans-serif",
        "var(--dash-color-bg)",
        "6px",
    ],
)
def test_ordinary_css_values_pass(value: str) -> None:
    assert check_value("x", value) == value


def test_balanced_counts_parentheses() -> None:
    assert [balanced(v) for v in ["", "(a)", "((a)b)", ")(", "(("]] == [
        True,
        True,
        True,
        False,
        False,
    ]


def test_tokens_have_namespaced_names_and_variables() -> None:
    token = Token("my-plugin.water.top", "#012")

    assert (token.var, token.owner) == ("--my-plugin-water-top", "my-plugin")
    assert token.value("dark") == "#012"
    assert Token("a.b", "#fff", "#000").value("dark") == "#000"


@pytest.mark.parametrize(
    "name", ["color", "Dash.color", "dash..color", ".dash.color", "dash.color bg"]
)
def test_a_malformed_token_name_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="not a token name"):
        Token(name, "#fff")


def test_a_legacy_variable_must_look_like_one() -> None:
    with pytest.raises(ValueError, match="not a CSS variable"):
        Token("a.b", "#fff", legacy="color: red")


def test_a_theme_needs_a_valid_name_and_at_least_one_token() -> None:
    with pytest.raises(ValueError, match="not a valid theme name"):
        Theme("Bad Name", "Bad", {BG: "#fff"})
    with pytest.raises(ValueError, match="sets no tokens"):
        Theme("empty", "Empty")
    with pytest.raises(ValueError, match="not a token name"):
        Theme("odd", "Odd", {"bg": "#fff"})
    with pytest.raises(ValueError, match="not a safe CSS value"):
        Theme("evil", "Evil", {BG: "red;}"})


def test_a_theme_file_is_a_dtcg_group_per_mode(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text(
        json.dumps(
            {
                "name": "mine",
                "light": {"dash": {"$type": "color", "color": {"bg": {"$value": "#fff"}}}},
                "dark": {"dash": {"radius": {"control": {"$type": "dimension", "$value": 4}}}},
            }
        )
    )

    theme = Theme.load(path)

    assert theme.title == "mine"
    assert dict(theme.light) == {BG: "#fff"}
    assert dict(theme.dark) == {"dash.radius.control": "4"}
    assert theme.modes == ("light", "dark")


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        ({"light": {"dash": {"color": {"bg": {"$value": "#fff"}}}}}, "needs a name"),
        (
            {"name": "x", "light": {"dash": {"color": {"bg": {"$value": {"colorSpace": "srgb"}}}}}},
            "only a string or number",
        ),
        ({"name": "x", "light": {"dash": {"color": {"bg": "#fff"}}}}, "not a token group"),
        (
            {"name": "x", "title": 3, "light": {"dash": {"color": {"bg": {"$value": "#fff"}}}}},
            "must be a string",
        ),
        ([], "not a token group"),
    ],
)
def test_a_theme_file_that_is_not_dtcg_is_refused(doc: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Theme.from_json(json.dumps(doc))


def test_flatten_inherits_a_group_type() -> None:
    leaves = flatten(
        {
            "a": {
                "$type": "color",
                "b": {"c": {"$value": "#fff"}},
                "d": {"$value": "1", "$type": "number"},
            }
        }
    )

    assert {name: leaf.type for name, leaf in leaves.items()} == {"a.b.c": "color", "a.d": "number"}


def test_the_core_tokens_come_from_tokens_json() -> None:
    tokens = {t.name: t for t in core_tokens()}

    assert tokens[BG].var == "--dash-color-bg"
    assert tokens[BG].legacy == "--bg"
    assert tokens[BG].light != tokens[BG].dark
    assert tokens["dash.radius.control"].dark is None
    assert tokens["dash.font.size"].type == "dimension"


def test_the_core_palette_meets_the_contrast_floor_in_both_modes() -> None:
    probe = Theme("probe", "Probe", {BG: "#fafaf9"}, {BG: "#0c0a09"})

    assert themes_of(probe).warnings["probe"] == []


def test_the_builtin_themes_load_clean() -> None:
    themes = builtin_themes()
    themeset = themes_of(*themes)

    assert [t.name for t in themes] == ["high-contrast"]
    assert themeset.warnings == {"high-contrast": []}
    assert {t.source for t in themes} == {"dash"}


def test_contrast_ratio_matches_the_wcag_examples() -> None:
    black, white = rgb("#000") or (0, 0, 0), rgb("#ffffff") or (1, 1, 1)

    assert contrast(black, white) == pytest.approx(21)
    assert contrast(white, white) == pytest.approx(1)
    assert rgb("rgb(0 0 0)") is None
    assert rgb("#12345") is None


def test_a_theme_that_is_hard_to_read_is_warned_about_per_mode() -> None:
    muddy = Theme(
        "muddy", "Muddy", {"dash.color.text": "#cccccc"}, {"dash.color.text-muted": "#222222"}
    )

    warnings = themes_of(muddy).warnings["muddy"]

    assert "dash.color.text on dash.color.bg is 1.5:1 in light mode, below 4.5:1" in warnings
    assert any("dash.color.text-muted on dash.color.bg" in w and "dark mode" in w for w in warnings)


def test_contrast_follows_var_references_and_skips_what_it_cannot_resolve() -> None:
    aliased = Theme("aliased", "Aliased", {"dash.color.text": "var(--dash-color-bg)"})
    fancy = Theme(
        "fancy", "Fancy", {"dash.color.text": "oklch(0.2 0 0)", "dash.color.danger": "var(--nope)"}
    )

    themeset = themes_of(aliased, fancy)

    assert any(
        "dash.color.text on dash.color.bg is 1.0:1" in w for w in themeset.warnings["aliased"]
    )
    assert themeset.warnings["fancy"] == []


def test_a_token_nobody_declares_is_a_warning_not_an_error() -> None:
    theme = Theme("ghost", "Ghost", {"gone.token": "#fff", BG: "#fff"})

    themeset = themes_of(theme)

    assert themeset.warnings["ghost"] == ["unknown token gone.token"]
    assert "gone" not in themeset.css


def test_the_stylesheet_has_the_layers_in_order_and_the_legacy_aliases() -> None:
    css = themes_of().css

    assert css.startswith("@layer dash-base, dash-theme, dash-user;")
    assert (
        css.index("@layer dash-base {")
        < css.index("@layer dash-theme {")
        < css.index("@layer dash-user {")
    )
    assert "--bg: var(--dash-color-bg);" in css
    assert ':root[data-mode="dark"] {' in css
    assert "@media (prefers-color-scheme: dark) { :root:not([data-mode])" in css
    assert "@media not all and (prefers-color-scheme: dark) { :root:not([data-mode])" in css


def test_a_theme_that_sets_one_mode_emits_rules_for_that_mode_only() -> None:
    night = Theme("night", "Night", dark={BG: "#001"})

    css = themes_of(night).css
    rules = [line for line in css.splitlines() if 'data-theme="night"' in line]

    assert len(rules) == 2
    assert all("#001" in line and "color-scheme: dark;" in line for line in rules)
    assert any('[data-mode="dark"]' in line for line in rules)
    assert any(line.lstrip().startswith("@media (prefers-color-scheme: dark)") for line in rules)


def test_a_theme_never_writes_a_mode_it_does_not_set() -> None:
    half = Theme("half", "Half", {BG: "#eee", "dash.color.text": "#111"}, {BG: "#111"})

    rules = [line for line in themes_of(half).css.splitlines() if 'data-theme="half"' in line]
    dark = [
        line
        for line in rules
        if '[data-mode="dark"]' in line
        or line.lstrip().startswith("@media (prefers-color-scheme: dark)")
    ]
    light = [line for line in rules if line not in dark]

    assert (len(dark), len(light)) == (2, 2)
    assert all("--dash-color-text" not in line for line in dark)
    assert all("--dash-color-text: #111;" in line for line in light)


def test_user_overrides_come_last_and_never_set_the_color_scheme() -> None:
    mine = Theme("overrides", "Mine", {BG: "#fff0f0"})

    css = themes_of(overrides=mine).css
    user = css[css.index("@layer dash-user {") :]

    assert "--dash-color-bg: #fff0f0;" in user
    assert not re.search(r"(?<!prefers-)color-scheme:", user)
    assert "[data-theme" not in user


def test_overrides_with_unknown_tokens_are_reported() -> None:
    mine = Theme("overrides", "Mine", {"nope.x": "#fff"})

    manifest = themes_of(overrides=mine).manifest()

    assert manifest["overrides"] == {"warnings": ["unknown token nope.x"]}
    assert themes_of().manifest()["overrides"] is None


def test_load_overrides_names_the_file_for_you_and_survives_a_bad_one(tmp_path: Path) -> None:
    good = tmp_path / "mine.json"
    good.write_text(json.dumps({"light": {"dash": {"color": {"bg": {"$value": "#fff0f0"}}}}}))
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")

    assert load_overrides("") is None
    assert load_overrides(str(tmp_path / "missing.json")) is None
    assert load_overrides(str(bad)) is None
    loaded = load_overrides(str(good))
    assert loaded is not None
    assert (loaded.name, dict(loaded.light)) == ("overrides", {BG: "#fff0f0"})


def test_plugin_tokens_and_themes_join_the_set() -> None:
    plugins = discover([f"{F}:themed"])

    themeset = plugins.themes()

    assert "--themed-glow: #ffee88;" in themeset.css
    assert "--themed-glow: #887700;" in themeset.css
    assert ':root[data-theme="sunny"]' in themeset.css
    assert {t["name"]: t["source"] for t in themeset.manifest()["themes"]} == {
        "high-contrast": "dash",
        "sunny": "themed",
    }
    assert themeset.warnings["sunny"] == []


@pytest.mark.parametrize(
    ("first", "second", "message"),
    [
        (None, "strays", "token other.glow must start with 'strays.'"),
        (None, "dashing", "not a valid plugin name"),
        ("hyphen", "dotted", "token variable --a-b-c is already taken"),
        (None, "doubled", "token variable names is already taken"),
        ("themed", "rival", "theme 'sunny' is already taken"),
        (None, "mimic", "theme 'high-contrast' is already taken"),
        (None, "copycat", "theme 'same' is already taken"),
    ],
)
def test_a_plugin_cannot_take_what_dash_or_another_plugin_owns(
    first: str | None, second: str, message: str
) -> None:
    refs = [f"{F}:{name}" for name in (first, second) if name]

    plugins = discover(refs)

    failed = plugins.loaded[-1]
    assert failed.plugin is None
    assert message in str(failed.error)
    assert len(plugins.active) == len(refs) - 1


def test_the_theme_is_served_as_json_and_css() -> None:
    client = make_client(discover([f"{F}:themed"]))

    manifest = client.get("/api/theme").json()
    css = client.get("/api/theme.css")

    assert css.headers["content-type"].startswith("text/css")
    assert css.headers["cache-control"] == "no-cache"
    assert css.text == discover([f"{F}:themed"]).themes().css
    assert "themed.glow" in {t["name"] for t in manifest["tokens"]}
    assert {t["name"] for t in manifest["themes"]} == {"high-contrast", "sunny"}


def test_with_no_plugins_dash_still_serves_its_own_theme() -> None:
    client = make_client(Plugins())

    assert client.get("/api/theme").json()["themes"][0]["name"] == "high-contrast"
    assert "--dash-color-bg" in client.get("/api/theme.css").text


def test_the_overrides_reach_the_stylesheet() -> None:
    client = make_client(Plugins(), Theme("overrides", "Mine", {BG: "#fff0f0"}))

    assert "--dash-color-bg: #fff0f0;" in client.get("/api/theme.css").text


def test_the_page_links_the_theme_before_its_own_styles() -> None:
    html = make_client(Plugins()).get("/").text

    assert html.index("/api/theme.css") < html.index("/static/style.css")
    assert make_client(Plugins()).get("/static/theme.js").status_code == 200


def test_the_stylesheet_only_uses_tokens_that_exist() -> None:
    css = (Path(__file__).parent.parent / "src/dash/static/style.css").read_text()
    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", css))
    known = {t.var for t in core_tokens()}

    assert used
    assert used <= known
