from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi.routing import APIRouter

from dash.plugins import Context, Plugin
from dash.queue import Activity

STATIC = Path(__file__).parent / "plugin_static"

started: list[str] = []
stopped: list[str] = []
seen: list[Activity] = []


def routes(ctx: Context) -> APIRouter:
    """Return a router that reports the process it runs in."""
    router = APIRouter()

    @router.get("/where")
    async def where() -> dict[str, str]:
        return {"process": ctx.process}

    return router


@asynccontextmanager
async def lifespan(ctx: Context) -> AsyncGenerator[None]:
    """Record that the plugin started and stopped."""
    started.append(ctx.process)
    yield
    stopped.append(ctx.process)


async def on_activity(ctx: Context, activity: Activity) -> None:
    """Record the activity."""
    seen.append(activity)


async def explode(ctx: Context, activity: Activity) -> None:
    """Raise ValueError."""
    raise ValueError("boom")


@asynccontextmanager
async def broken_lifespan(ctx: Context) -> AsyncGenerator[None]:
    """Raise RuntimeError before the plugin starts."""
    raise RuntimeError("no start")
    yield


def broken_routes(ctx: Context) -> APIRouter:
    """Raise RuntimeError instead of returning a router."""
    raise RuntimeError("no routes")


hello = Plugin(
    name="hello",
    version="1.2.3",
    routes=routes,
    lifespan=lifespan,
    on_activity=on_activity,
    static=STATIC,
    script="hello.js",
    style="hello.css",
)


def factory() -> Plugin:
    """Return a plugin, to show that an entry point may name a factory."""
    return Plugin(name="made")


future = Plugin(name="future", api=99)
shouting = Plugin(name="Not Valid")
twin = Plugin(name="hello")
lost = Plugin(name="lost", static=STATIC / "missing")
orphan = Plugin(name="orphan", script="x.js")
fragile = Plugin(
    name="fragile", routes=broken_routes, lifespan=broken_lifespan, on_activity=explode
)
not_a_plugin = "hello"
