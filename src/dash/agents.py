"""Agents that answer a turn: an OpenAI-compatible chat API, or any agent that speaks ACP.

An ACP agent is reached over stdio (dash starts the process) or over a WebSocket (the
agent runs somewhere else, next to its own data). Each dash conversation is bound to one
agent and, for ACP, to one session on that agent.
"""

import asyncio
import contextlib
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

from acp import PROTOCOL_VERSION, Client, connect_to_agent, text_block
from acp.client.connection import ClientSideConnection
from acp.exceptions import RequestError
from acp.schema import (
    AgentCapabilities,
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AllowedOutcome,
    ClientCapabilities,
    ContentToolCallContent,
    DeniedOutcome,
    FileEditToolCallContent,
    Implementation,
    PermissionOption,
    RequestPermissionResponse,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    ToolCallUpdate,
)
from acp.stdio import spawn_agent_process

log = logging.getLogger(__name__)

ACP = "acp"
OPENAI = "openai"
STDIO_LIMIT = 16 * 1024 * 1024
DETAIL_CHARS = 2000
CARRY_MESSAGES = 20
CARRY_CHARS = 20_000
CONNECTION_ERRORS = (ConnectionError, OSError, EOFError)
CANCEL_GRACE_SECONDS = 10


@dataclass(frozen=True)
class Text:
    """A piece of the agent's reply."""

    text: str


@dataclass(frozen=True)
class Thought:
    """A piece of the agent's reasoning."""

    text: str


@dataclass(frozen=True)
class Tool:
    """The latest known state of one tool call."""

    id: str
    title: str
    kind: str
    status: str
    detail: str = ""
    paths: tuple[str, ...] = ()

    def as_json(self) -> dict[str, Any]:
        """Return the tool call as the JSON that the API sends."""
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "status": self.status,
            "detail": self.detail,
            "paths": list(self.paths),
        }


@dataclass(frozen=True)
class Plan:
    """The agent's current plan."""

    entries: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class Session:
    """The agent started a new session for the conversation."""

    session_id: str


@dataclass(frozen=True)
class Stop:
    """The turn ended."""

    reason: str


Update = Text | Thought | Tool | Plan | Session | Stop


@dataclass(frozen=True)
class PermissionAsk:
    """A question from the agent that the user must answer before a tool runs."""

    id: str
    title: str
    options: tuple[dict[str, str], ...]

    def as_json(self) -> dict[str, Any]:
        """Return the question as the JSON that the API sends."""
        return {"id": self.id, "title": self.title, "options": list(self.options)}


Ask = Callable[[PermissionAsk], Awaitable[str | None]]


async def deny(_: PermissionAsk) -> None:
    """Answer no to every permission question."""


@dataclass(frozen=True)
class Turn:
    """One user message for an agent to answer."""

    conversation_id: str
    session_id: str | None
    history: Sequence[Mapping[str, str]]
    context: str = ""
    ask: Ask = deny

    @property
    def text(self) -> str:
        """Return the user message this turn answers."""
        return self.history[-1]["content"] if self.history else ""


class Agent(Protocol):
    name: str
    title: str
    kind: str

    def run(self, turn: Turn) -> AsyncIterator[Update]: ...

    async def cancel(self, session_id: str | None) -> bool: ...

    async def close(self) -> None: ...


class Chat(Protocol):
    def stream(self, messages: Sequence[Mapping[str, str]]) -> AsyncIterator[str]: ...


@dataclass(frozen=True)
class AgentSpec:
    """How to reach one agent, as configured in `DASH_AGENTS`."""

    name: str
    title: str
    kind: str
    command: tuple[str, ...] = ()
    url: str = ""
    headers: Mapping[str, str] = field(default_factory=dict[str, str])
    env: Mapping[str, str] = field(default_factory=dict[str, str])
    cwd: str = ""
    memory: bool = True
    base_url: str = ""
    api_key: str = ""
    model: str = ""

    def as_json(self) -> dict[str, Any]:
        """Return the public part of the spec, without secrets."""
        transport = "stdio" if self.command else "websocket" if self.url else "http"
        return {"name": self.name, "title": self.title, "kind": self.kind, "transport": transport}


def parse_spec(name: str, raw: Mapping[str, Any], environ: Mapping[str, str]) -> AgentSpec:
    """Return the agent spec for one `DASH_AGENTS` entry. Raise ValueError if it is invalid."""
    command = raw.get("command") or ()
    if isinstance(command, str):
        command = (command,)
    url = str(raw.get("url") or "")
    kind = ACP if command or url else OPENAI
    if command and url:
        raise ValueError(f"Agent {name!r} sets both command and url.")
    token_env = raw.get("token_env")
    raw_headers = cast("dict[str, Any]", raw.get("headers") or {})
    headers = {str(k): str(v) for k, v in raw_headers.items()}
    if token_env:
        headers["Authorization"] = f"Bearer {environ.get(token_env, '')}"
    env = {key: environ[key] for key in raw.get("pass_env") or () if key in environ}
    env |= {str(k): str(v) for k, v in cast("dict[str, Any]", raw.get("env") or {}).items()}
    api_key_env = raw.get("api_key_env")
    return AgentSpec(
        name=name,
        title=str(raw.get("title") or name),
        kind=kind,
        command=tuple(str(part) for part in command),
        url=url,
        headers=headers,
        env=env,
        cwd=str(raw.get("cwd") or ""),
        memory=bool(raw.get("memory", True)),
        base_url=str(raw.get("base_url") or "").rstrip("/"),
        api_key=environ.get(api_key_env, "") if api_key_env else "",
        model=str(raw.get("model") or ""),
    )


@dataclass(frozen=True)
class Catalog:
    """The configured agents and the one that new conversations use."""

    specs: tuple[AgentSpec, ...]
    default: str

    @classmethod
    def parse(
        cls, raw: str, default: str = "", environ: Mapping[str, str] | None = None
    ) -> "Catalog":
        """Return the catalog in a `DASH_AGENTS` JSON object. Empty means one hermes agent."""
        environ = os.environ if environ is None else environ
        entries: Any = json.loads(raw) if raw.strip() else {"hermes": {}}
        if not isinstance(entries, dict) or not entries:
            raise ValueError("DASH_AGENTS must be a JSON object of agent name to settings.")
        found = cast("dict[str, Any]", entries)
        specs = tuple(parse_spec(str(name), spec or {}, environ) for name, spec in found.items())
        chosen = default or specs[0].name
        if chosen not in {s.name for s in specs}:
            raise ValueError(f"DASH_DEFAULT_AGENT {chosen!r} is not in DASH_AGENTS.")
        return cls(specs, chosen)

    def spec(self, name: str | None) -> AgentSpec:
        """Return the spec of the named agent, or of the default one for None."""
        wanted = name or self.default
        found = [s for s in self.specs if s.name == wanted]
        if not found:
            raise KeyError(wanted)
        return found[0]

    def as_json(self) -> dict[str, Any]:
        """Return the catalog as the JSON that the API sends."""
        return {"default": self.default, "agents": [s.as_json() for s in self.specs]}


class ChatAgent:
    """An agent behind an OpenAI-compatible chat API. dash sends the whole history each turn."""

    kind = OPENAI

    def __init__(self, name: str, title: str, chat: Chat) -> None:
        self.name = name
        self.title = title
        self.chat = chat

    async def run(self, turn: Turn) -> AsyncGenerator[Update]:
        """Yield the reply as text pieces, then the stop."""
        system = [{"role": "system", "content": turn.context}] if turn.context else []
        async for delta in self.chat.stream([*system, *turn.history]):
            yield Text(delta)
        yield Stop("end_turn")

    async def cancel(self, session_id: str | None) -> bool:
        """Return False: the caller must stop reading the reply itself."""
        return False

    async def close(self) -> None:
        """Close the chat client if it has a close method."""
        closer = getattr(self.chat, "close", None)
        if closer is not None:
            await closer()


def tool_detail(content: Sequence[Any] | None) -> str:
    """Return a short text summary of a tool call's output."""
    texts = [
        item.content.text
        for item in content or ()
        if isinstance(item, ContentToolCallContent) and isinstance(item.content, TextContentBlock)
    ]
    diffs = [
        f"edit {item.path}" for item in content or () if isinstance(item, FileEditToolCallContent)
    ]
    return "\n".join([*diffs, *texts])[:DETAIL_CHARS]


def carried_history(history: Sequence[Mapping[str, str]]) -> str:
    """Return the earlier turns as text, for an agent that lost the session."""
    earlier = list(history[:-1])[-CARRY_MESSAGES:]
    lines = [f"{m['role']}: {m['content']}" for m in earlier]
    text = "\n\n".join(lines)[-CARRY_CHARS:]
    return f"Earlier in this conversation (the session was restarted):\n\n{text}" if text else ""


@dataclass
class _Route:
    """Where a live session's updates and permission questions go."""

    updates: asyncio.Queue[Update | None]
    ask: Ask
    tools: dict[str, Tool] = field(default_factory=dict[str, Tool])


class _Handler:
    """The client side of an ACP connection: routes each update to the turn that waits for it."""

    def __init__(self, agent: "AcpAgent") -> None:
        self.agent = agent

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        """Turn one ACP session update into a dash update for the waiting turn."""
        route = self.agent.routes.get(session_id)
        if route is None:
            return
        converted = convert(update, route)
        if converted is not None:
            route.updates.put_nowait(converted)

    async def request_permission(
        self,
        session_id: str,
        tool_call: ToolCallUpdate,
        options: list[PermissionOption],
        **kwargs: Any,
    ) -> RequestPermissionResponse:
        """Ask the user through the waiting turn and return their choice."""
        route = self.agent.routes.get(session_id)
        if route is None:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        ask = PermissionAsk(
            id=uuid.uuid4().hex,
            title=tool_call.title
            or route.tools.get(tool_call.tool_call_id, Tool("", "", "", "")).title
            or "The agent wants to run a tool.",
            options=tuple({"id": o.option_id, "name": o.name, "kind": o.kind} for o in options),
        )
        choice = await route.ask(ask)
        if choice not in {o.option_id for o in options}:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=choice)
        )


def convert(update: Any, route: _Route) -> Update | None:
    """Return the dash update for one ACP session update, or None for one dash does not show."""
    match update:
        case AgentMessageChunk(content=TextContentBlock(text=text)):
            return Text(text)
        case AgentThoughtChunk(content=TextContentBlock(text=text)):
            return Thought(text)
        case ToolCallStart():
            tool = Tool(
                id=update.tool_call_id,
                title=update.title,
                kind=update.kind or "other",
                status=update.status or "pending",
                detail=tool_detail(update.content),
                paths=tuple(loc.path for loc in update.locations or ()),
            )
        case ToolCallProgress():
            old = route.tools.get(update.tool_call_id, Tool(update.tool_call_id, "", "other", ""))
            tool = Tool(
                id=old.id,
                title=update.title or old.title,
                kind=update.kind or old.kind,
                status=update.status or old.status,
                detail=tool_detail(update.content) if update.content is not None else old.detail,
                paths=tuple(loc.path for loc in update.locations)
                if update.locations
                else old.paths,
            )
        case AgentPlanUpdate():
            return Plan(
                tuple(
                    {"content": e.content, "status": e.status, "priority": e.priority}
                    for e in update.entries
                )
            )
        case _:
            return None
    route.tools[tool.id] = tool
    return tool


class AcpAgent:
    """An agent that speaks ACP. One connection serves every session dash has open on it."""

    kind = ACP

    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec
        self.name = spec.name
        self.title = spec.title
        self.routes: dict[str, _Route] = {}
        self._conn: ClientSideConnection | None = None
        self._caps = AgentCapabilities()
        self._live: set[str] = set()
        self._stack = AsyncExitStack()
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None

    @property
    def cwd(self) -> str:
        """Return the working directory sent with each session."""
        return self.spec.cwd or str(Path.cwd())

    async def _open(self) -> ClientSideConnection:
        if self.spec.command:
            conn, self._process = await self._stack.enter_async_context(
                spawn_agent_process(
                    cast("Client", _Handler(self)),
                    self.spec.command[0],
                    *self.spec.command[1:],
                    env=self.spec.env,
                    cwd=self.spec.cwd or None,
                    transport_kwargs={"stderr": None, "limit": STDIO_LIMIT},
                    use_unstable_protocol=True,
                )
            )
            return conn
        from acp.ws import create_websocket_stream

        transport = await create_websocket_stream(self.spec.url, headers=dict(self.spec.headers))
        conn = connect_to_agent(
            cast("Client", _Handler(self)), transport, use_unstable_protocol=True
        )
        self._stack.push_async_callback(conn.close)
        return conn

    async def connect(self) -> ClientSideConnection:
        """Return a live connection, opening and initializing one if needed."""
        async with self._lock:
            if self._process is not None and self._process.returncode is not None:
                await self._reset()
            if self._conn is None:
                conn = await self._open()
                try:
                    init = await conn.initialize(
                        protocol_version=PROTOCOL_VERSION,
                        client_capabilities=ClientCapabilities(),
                        client_info=Implementation(name="dash", title="dash", version="0.1.0"),
                    )
                except BaseException:
                    await self._reset()
                    raise
                self._caps = init.agent_capabilities or AgentCapabilities()
                self._conn = conn
                log.info("connected to agent %s", self.name)
            return self._conn

    async def _reset(self) -> None:
        self._conn = None
        self._process = None
        self._live.clear()
        stack, self._stack = self._stack, AsyncExitStack()
        with contextlib.suppress(Exception):
            await stack.aclose()

    async def _restore(self, conn: ClientSideConnection, session_id: str) -> bool:
        sessions = self._caps.session_capabilities
        try:
            if self._caps.load_session:
                await conn.load_session(cwd=self.cwd, session_id=session_id)
            elif sessions is not None and sessions.resume is not None:
                await conn.resume_session(cwd=self.cwd, session_id=session_id)
            else:
                return False
        except RequestError:
            log.warning("agent %s could not restore session %s", self.name, session_id)
            return False
        return True

    async def session(self, conn: ClientSideConnection, turn: Turn) -> tuple[str, bool]:
        """Return the session for the turn and True if it is a new one."""
        wanted = turn.session_id
        if wanted and (wanted in self._live or await self._restore(conn, wanted)):
            self._live.add(wanted)
            return wanted, False
        created = await conn.new_session(cwd=self.cwd, mcp_servers=[])
        self._live.add(created.session_id)
        return created.session_id, True

    def blocks(self, turn: Turn, new: bool) -> list[Any]:
        """Return the prompt blocks for the turn."""
        carried = carried_history(turn.history) if new and turn.session_id else ""
        context = turn.context if self.spec.memory else ""
        return [text_block(part) for part in (context, carried, turn.text) if part]

    async def run(self, turn: Turn) -> AsyncGenerator[Update]:
        """Yield the agent's updates for the turn, then the stop."""
        try:
            conn = await self.connect()
            session_id, new = await self.session(conn, turn)
        except CONNECTION_ERRORS:
            async with self._lock:
                await self._reset()
            raise
        if session_id != turn.session_id:
            yield Session(session_id)
        route = _Route(asyncio.Queue(), turn.ask)
        self.routes[session_id] = route
        prompt = asyncio.create_task(
            conn.prompt(session_id=session_id, prompt=self.blocks(turn, new))
        )
        prompt.add_done_callback(lambda _: route.updates.put_nowait(None))
        try:
            while (update := await route.updates.get()) is not None:
                yield update
            try:
                result = prompt.result()
            except CONNECTION_ERRORS:
                async with self._lock:
                    await self._reset()
                raise
            yield Stop(result.stop_reason)
        finally:
            try:
                if not prompt.done():
                    with contextlib.suppress(Exception):
                        await conn.cancel(session_id=session_id)
                        await asyncio.wait_for(asyncio.shield(prompt), CANCEL_GRACE_SECONDS)
            finally:
                prompt.cancel()
                self.routes.pop(session_id, None)

    async def cancel(self, session_id: str | None) -> bool:
        """Ask the agent to end the session's turn. Return True if it was asked."""
        if self._conn is None or session_id is None:
            return False
        try:
            await self._conn.cancel(session_id=session_id)
        except CONNECTION_ERRORS:
            return False
        return True

    async def close(self) -> None:
        """Close the connection and stop the agent process."""
        async with self._lock:
            await self._reset()


def build(spec: AgentSpec, *, chat: Callable[[AgentSpec], Chat]) -> Agent:
    """Return the agent for a spec. `chat` makes the client for an OpenAI-compatible one."""
    if spec.kind == ACP:
        return AcpAgent(spec)
    return ChatAgent(spec.name, spec.title, chat(spec))


class Agents:
    """The agents the worker can run, by name."""

    def __init__(self, agents: Sequence[Agent], default: str | None = None) -> None:
        self.by_name = {a.name: a for a in agents}
        self.default = default or agents[0].name

    def get(self, name: str | None) -> Agent:
        """Return the named agent, or the default one for None. Raise KeyError if unknown."""
        return self.by_name[name or self.default]

    async def close(self) -> None:
        """Close every agent."""
        await asyncio.gather(*(a.close() for a in self.by_name.values()), return_exceptions=True)
