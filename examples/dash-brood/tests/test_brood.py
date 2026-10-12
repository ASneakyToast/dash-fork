from typing import cast

import fakeredis
import pytest
from dash_brood.mood import SICK_WINDOW_SECONDS, mood
from fastapi.testclient import TestClient

from dash.db import Store
from dash.nango import Nango
from dash.plugins import discover
from dash.queue import Activity, Job, Queue
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
