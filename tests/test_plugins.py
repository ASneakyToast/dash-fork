import asyncio
from importlib.metadata import EntryPoint
from typing import cast

import fakeredis
import pytest
from fastapi.testclient import TestClient

from dash.db import Store
from dash.nango import Nango
from dash.plugins import API_VERSION, Context, Loaded, Plugin, Plugins, discover
from dash.queue import Job, Queue
from dash.web import create_app
from tests import plugin_fixtures
from tests.fakes import FakeEmbedder, FakeStore

F = "tests.plugin_fixtures"


@pytest.fixture(autouse=True)
def reset() -> None:
    plugin_fixtures.started.clear()
    plugin_fixtures.stopped.clear()
    plugin_fixtures.seen.clear()


def make_queue() -> Queue:
    return Queue(fakeredis.FakeAsyncRedis(decode_responses=True))


def make_client(plugins: Plugins) -> TestClient:
    app = create_app(
        store=cast("Store", FakeStore()),
        queue=make_queue(),
        embedder=FakeEmbedder(),
        nango=Nango("http://nango.invalid", ""),
        plugins=plugins,
    )
    return TestClient(app)


def statuses(plugins: Plugins) -> dict[str, str]:
    return {entry["name"]: entry["status"] for entry in plugins.manifest()}


def test_refs_load_a_plugin_or_a_factory() -> None:
    plugins = discover([f"{F}:hello", f"{F}:factory"])

    assert [p.name for p in plugins.active] == ["hello", "made"]


@pytest.mark.parametrize(
    ("ref", "message"),
    [
        (f"{F}:future", "needs plugin API 99"),
        (f"{F}:shouting", "not a valid plugin name"),
        (f"{F}:lost", "does not exist"),
        (f"{F}:orphan", "need a static directory"),
        (f"{F}:not_a_plugin", "expected a Plugin"),
        (f"{F}:missing", "has no attribute"),
        ("tests.nope:plugin", "No module named"),
        ("no-colon", "is not module:attribute"),
    ],
)
def test_a_bad_plugin_is_reported_and_does_not_stop_the_good_ones(ref: str, message: str) -> None:
    plugins = discover([ref, f"{F}:hello"])

    [bad, good] = plugins.manifest()
    assert bad["status"] == "error"
    assert message in bad["error"]
    assert good["status"] == "ok"
    assert [p.name for p in plugins.active] == ["hello"]


def test_a_second_plugin_with_the_same_name_is_refused() -> None:
    plugins = discover([f"{F}:hello", f"{F}:twin"])

    assert [item.plugin is not None for item in plugins.loaded] == [True, False]
    assert "already called 'hello'" in str(plugins.loaded[1].error)


def test_the_same_plugin_listed_twice_loads_once() -> None:
    plugins = discover([f"{F}:hello", f"{F}:hello"])

    assert [item.label for item in plugins.loaded] == [f"{F}:hello"]


def test_disabled_plugins_are_not_imported() -> None:
    plugins = discover(["tests.nope:plugin", f"{F}:hello"], disabled=["tests.nope:plugin"])

    assert [item.label for item in plugins.loaded] == [f"{F}:hello"]


def test_entry_points_are_discovered(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(*, group: str) -> list[EntryPoint]:
        return [EntryPoint("hello", f"{F}:hello", group)]

    monkeypatch.setattr("dash.plugins.entry_points", fake)

    assert [p.name for p in discover().active] == ["hello"]


def test_manifest_gives_the_browser_urls() -> None:
    plugins = discover([f"{F}:hello"])

    assert plugins.manifest() == [
        {
            "name": "hello",
            "version": "1.2.3",
            "status": "ok",
            "script": "/plugins/hello/hello.js",
            "style": "/plugins/hello/hello.css",
        }
    ]


def test_routes_static_and_manifest_are_mounted_under_the_plugin_name() -> None:
    client = make_client(discover([f"{F}:hello"]))

    assert client.get("/api/plugins/hello/where").json() == {"process": "api"}
    assert client.get("/plugins/hello/hello.js").status_code == 200
    assert client.get("/plugins/hello/../../etc/passwd").status_code == 404
    body = client.get("/api/plugins").json()
    assert body["api"] == API_VERSION
    assert body["plugins"][0]["name"] == "hello"


def test_lifespan_runs_with_the_app() -> None:
    with make_client(discover([f"{F}:hello"])):
        assert plugin_fixtures.started == ["api"]
        assert plugin_fixtures.stopped == []

    assert plugin_fixtures.stopped == ["api"]


def test_a_plugin_that_fails_to_mount_or_start_does_not_break_dash() -> None:
    plugins = discover([f"{F}:fragile", f"{F}:hello"])

    with make_client(plugins) as client:
        assert statuses(plugins) == {"fragile": "ok", "hello": "ok"}
        assert client.get("/api/plugins/hello/where").status_code == 200
        assert client.get("/healthz").status_code == 200
        assert plugin_fixtures.started == ["api"]


def test_with_no_plugins_the_manifest_is_empty_and_no_plugin_files_are_served() -> None:
    client = make_client(Plugins())

    assert client.get("/api/plugins").json() == {"api": API_VERSION, "plugins": []}
    assert client.get("/plugins/hello/hello.js").status_code == 404


async def test_on_activity_reaches_every_listener_and_one_failure_does_not_stop_the_rest() -> None:
    plugins = discover([f"{F}:fragile", f"{F}:hello"])
    queue = make_queue()
    ctx = Context("worker", cast("Store", FakeStore()), queue)
    activity = await queue.publish("started", Job("1-0", "job", "conv"))

    await plugins.dispatch(ctx, activity)

    assert plugin_fixtures.seen == [activity]


async def test_a_listener_that_hangs_is_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    async def hang(ctx: Context, activity: object) -> None:
        await asyncio.sleep(60)

    monkeypatch.setattr("dash.plugins.HOOK_TIMEOUT_SECONDS", 0.01)
    plugins = Plugins([Loaded("slow", Plugin(name="slow", on_activity=hang))])
    queue = make_queue()
    ctx = Context("worker", cast("Store", FakeStore()), queue)

    await plugins.dispatch(ctx, await queue.publish("started", Job("1-0", "job", "conv")))
