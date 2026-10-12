import re
from pathlib import Path
from typing import cast

import fakeredis
import pytest
from dash_brood import TOKENS, plugin
from dash_brood.mood import SICK_WINDOW_SECONDS, mood
from fastapi.testclient import TestClient

from dash.db import Store
from dash.nango import Nango
from dash.plugins import discover
from dash.queue import Activity, Job, Queue
from dash.theme import core_tokens
from dash.web import create_app

NOW = 1_000_000.0
IDLE = {"waiting": 0, "in_flight": 0, "workers": 1}


class NoEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.0]


def failed(age: float) -> Activity:
    return Activity(f"{int((NOW - age) * 1000)}-0", "failed", "job", "conv", {})


@pytest.mark.parametrize(
    ("status", "recent", "expected"),
    [
        (IDLE, [], "content"),
        ({**IDLE, "in_flight": 1}, [], "busy"),
        ({**IDLE, "waiting": 2, "in_flight": 1}, [], "busy"),
        ({**IDLE, "waiting": 3}, [], "strained"),
        ({**IDLE, "workers": 0}, [], "asleep"),
        (IDLE, [failed(10)], "sick"),
        (IDLE, [failed(SICK_WINDOW_SECONDS + 1)], "content"),
        ({**IDLE, "waiting": 9}, [failed(10)], "sick"),
        ({**IDLE, "workers": 0, "waiting": 9}, [failed(10)], "asleep"),
    ],
)
def test_mood(status: dict[str, int], recent: list[Activity], expected: str) -> None:
    assert mood(status, recent, NOW) == expected


async def test_the_plugin_is_served_by_dash() -> None:
    queue = Queue(fakeredis.FakeAsyncRedis(decode_responses=True))
    await queue.ensure_group()
    await queue.enqueue("conv")
    await queue.enqueue("conv")
    await queue.claim("w1", block_ms=10)
    await queue.publish("failed", Job("1-0", "job", "conv"), message="boom")
    plugins = discover(["dash_brood:plugin"])
    app = create_app(
        store=cast("Store", None),
        queue=queue,
        embedder=NoEmbedder(),
        nango=Nango("http://nango.invalid", ""),
        plugins=plugins,
    )
    client = TestClient(app)

    mother = client.get("/api/plugins/brood/mother").json()

    assert mother["mood"] == "sick"
    assert (mother["waiting"], mother["in_flight"], mother["workers"]) == (1, 1, 1)
    assert client.get("/plugins/brood/brood.js").status_code == 200
    assert client.get("/plugins/brood/brood.css").status_code == 200
    assert client.get("/api/plugins").json()["plugins"][0]["name"] == "brood"


STATIC = Path(__file__).parent.parent / "src" / "dash_brood" / "static"


def test_the_palette_asks_for_exactly_the_tokens_the_plugin_declares() -> None:
    asked = set(re.findall(r'"(brood\.[a-z0-9.-]+)"', (STATIC / "palette.js").read_text()))

    assert asked == {token.name for token in TOKENS}


def test_the_plugin_adds_tokens_and_a_clean_theme_to_dash() -> None:
    themeset = discover(["dash_brood:plugin"]).themes()

    assert {t["name"]: t["source"] for t in themeset.manifest()["themes"]}["tidepool"] == "brood"
    assert themeset.warnings["tidepool"] == []
    assert "--brood-water-top: #4aa6d6;" in themeset.css
    assert "--brood-water-top: #134069;" in themeset.css


def test_tidepool_is_a_dark_only_theme_so_it_forces_dark_mode() -> None:
    [tidepool] = [t for t in plugin.themes if t.name == "tidepool"]

    assert tidepool.modes == ("dark",)


def test_no_color_is_hardcoded_outside_the_job_squids_and_the_palette() -> None:
    literal = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(\d")

    found = {
        name: len(literal.findall((STATIC / name).read_text()))
        for name in ("art.js", "brood.js", "brood.css", "model.js")
    }

    assert found == {"art.js": 0, "brood.js": 0, "brood.css": 0, "model.js": 0}


def test_the_stylesheet_only_uses_variables_that_exist() -> None:
    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", (STATIC / "brood.css").read_text()))
    known = {t.var for t in core_tokens()} | {t.var for t in TOKENS}

    assert used
    assert used <= known
