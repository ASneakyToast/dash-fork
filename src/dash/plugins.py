"""The plugin API: what a plugin declares, and how dash finds, mounts and runs plugins."""

import asyncio
import importlib
import logging
import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Collection, Iterable, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, replace
from functools import partial
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.routing import APIRouter
from fastapi.staticfiles import StaticFiles

from dash.db import Store
from dash.queue import Activity, Queue
from dash.theme import CORE, Theme, ThemeSet, Token, builtin_themes, core_tokens

log = logging.getLogger(__name__)

API_VERSION = 1
ENTRY_POINT_GROUP = "dash.plugins"
HOOK_TIMEOUT_SECONDS = 5
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class Context:
    """What dash hands a plugin: the process it runs in, and the store and queue it shares."""

    process: Literal["api", "worker"]
    store: Store
    queue: Queue


@dataclass(frozen=True)
class Plugin:
    """What a plugin adds to dash. Every part except the name is optional."""

    name: str
    version: str = "0.0.0"
    api: int = API_VERSION
    routes: Callable[[Context], APIRouter] | None = None
    lifespan: Callable[[Context], AbstractAsyncContextManager[None]] | None = None
    on_activity: Callable[[Context, Activity], Awaitable[None]] | None = None
    static: Path | None = None
    script: str | None = None
    style: str | None = None
    tokens: Sequence[Token] = ()
    themes: Sequence[Theme] = ()


@dataclass(frozen=True)
class Loaded:
    """The outcome of loading one plugin: the plugin, or why it failed."""

    label: str
    plugin: Plugin | None = None
    error: str | None = None


def import_ref(ref: str) -> object:
    """Return the object that a `module:attribute` reference names."""
    module, _, attribute = ref.partition(":")
    if not module or not attribute:
        raise ValueError(f"{ref!r} is not module:attribute.")
    return getattr(importlib.import_module(module), attribute)


def build(target: object) -> Plugin:
    """Return the plugin that an entry point loaded, calling it first if it is a factory."""
    plugin = target if isinstance(target, Plugin) else target() if callable(target) else target
    if not isinstance(plugin, Plugin):
        raise TypeError(f"expected a Plugin, got {type(plugin).__name__}.")
    return plugin


def check(plugin: Plugin, loaded: Sequence[Plugin]) -> None:
    """Raise ValueError if dash cannot run the plugin."""
    if not NAME.fullmatch(plugin.name) or plugin.name == CORE:
        raise ValueError(f"{plugin.name!r} is not a valid plugin name.")
    if plugin.name in {other.name for other in loaded}:
        raise ValueError(f"another plugin is already called {plugin.name!r}.")
    if plugin.api != API_VERSION:
        raise ValueError(f"needs plugin API {plugin.api}, but dash has {API_VERSION}.")
    if plugin.static is not None and not plugin.static.is_dir():
        raise ValueError(f"static directory {plugin.static} does not exist.")
    if (plugin.script or plugin.style) and plugin.static is None:
        raise ValueError("script and style need a static directory.")
    check_theming(plugin, loaded)


def check_theming(plugin: Plugin, loaded: Sequence[Plugin]) -> None:
    """Raise ValueError if the plugin's tokens or themes clash with dash or another plugin."""
    stray = [t.name for t in plugin.tokens if t.owner != plugin.name]
    if stray:
        raise ValueError(f"token {stray[0]} must start with '{plugin.name}.'.")
    used_vars = {t.var for t in core_tokens()} | {t.var for p in loaded for t in p.tokens}
    clash = [t.var for t in plugin.tokens if t.var in used_vars]
    if clash or len({t.var for t in plugin.tokens}) < len(plugin.tokens):
        raise ValueError(f"token variable {clash[0] if clash else 'names'} is already taken.")
    used_themes = {t.name for t in builtin_themes()} | {t.name for p in loaded for t in p.themes}
    names = [t.name for t in plugin.themes]
    taken = used_themes & set(names) or {n for n in names if names.count(n) > 1}
    if taken:
        raise ValueError(f"theme {sorted(taken)[0]!r} is already taken.")


def load_one(label: str, load: Callable[[], object], loaded: Sequence[Plugin]) -> Loaded | None:
    """Load one plugin, returning the failure instead of raising it and None for a repeat."""
    try:
        plugin = build(load())
        if plugin in loaded:
            return None
        check(plugin, loaded)
    except Exception as ex:
        log.exception("plugin %s failed to load", label)
        return Loaded(label, error=f"{type(ex).__name__}: {ex}")
    log.info("plugin %s %s loaded", plugin.name, plugin.version)
    return Loaded(label, plugin)


def discover(refs: Iterable[str] = (), disabled: Collection[str] = ()) -> "Plugins":
    """Return the plugins from the `dash.plugins` entry points and the given references."""
    candidates: list[tuple[str, Callable[[], object]]] = [
        (point.name, point.load) for point in entry_points(group=ENTRY_POINT_GROUP)
    ] + [(ref, partial(import_ref, ref)) for ref in refs]
    loaded: list[Loaded] = []
    for label, load in candidates:
        if label in disabled:
            continue
        item = load_one(label, load, [x.plugin for x in loaded if x.plugin])
        if item:
            loaded.append(item)
    return Plugins(loaded)


class Plugins:
    """The plugins dash loaded, and the one place that runs them."""

    def __init__(self, loaded: Sequence[Loaded] = ()) -> None:
        self.loaded = list(loaded)

    @property
    def active(self) -> list[Plugin]:
        """Return the plugins that loaded."""
        return [item.plugin for item in self.loaded if item.plugin]

    def themes(self, overrides: Theme | None = None) -> ThemeSet:
        """Return the tokens and themes of dash and every plugin that loaded."""
        return ThemeSet(
            [*core_tokens(), *(token for plugin in self.active for token in plugin.tokens)],
            [
                *builtin_themes(),
                *(
                    replace(theme, source=plugin.name)
                    for plugin in self.active
                    for theme in plugin.themes
                ),
            ],
            overrides,
        )

    def manifest(self) -> list[dict[str, Any]]:
        """Return what the browser needs to know about each plugin."""
        return [
            {
                "name": item.plugin.name,
                "version": item.plugin.version,
                "status": "ok",
                "script": asset(item.plugin, item.plugin.script),
                "style": asset(item.plugin, item.plugin.style),
            }
            if item.plugin
            else {"name": item.label, "status": "error", "error": item.error}
            for item in self.loaded
        ]

    def mount(self, app: FastAPI, ctx: Context) -> None:
        """Add each plugin's routes and static files to the app under its own prefix."""
        for plugin in self.active:
            try:
                if plugin.routes:
                    app.include_router(
                        plugin.routes(ctx), prefix=f"/api/plugins/{plugin.name}", tags=[plugin.name]
                    )
                if plugin.static:
                    app.mount(
                        f"/plugins/{plugin.name}",
                        StaticFiles(directory=plugin.static),
                        name=f"plugin-{plugin.name}",
                    )
            except Exception:
                log.exception("plugin %s failed to mount", plugin.name)

    @asynccontextmanager
    async def lifespan(self, ctx: Context) -> AsyncGenerator[None]:
        """Run every plugin lifespan around the caller, skipping any that fail to start."""
        async with AsyncExitStack() as stack:
            for plugin in self.active:
                if plugin.lifespan is None:
                    continue
                try:
                    await stack.enter_async_context(plugin.lifespan(ctx))
                except Exception:
                    log.exception("plugin %s failed to start", plugin.name)
            yield

    async def dispatch(self, ctx: Context, activity: Activity) -> None:
        """Pass the activity to each plugin that listens, and log any handler that fails."""
        for plugin in self.active:
            if plugin.on_activity is None:
                continue
            try:
                async with asyncio.timeout(HOOK_TIMEOUT_SECONDS):
                    await plugin.on_activity(ctx, activity)
            except Exception:
                log.exception("plugin %s on_activity failed", plugin.name)


def asset(plugin: Plugin, name: str | None) -> str | None:
    """Return the URL of a file in the plugin's static directory."""
    return f"/plugins/{plugin.name}/{name}" if name else None
