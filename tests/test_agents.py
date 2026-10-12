import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from dash.agents import (
    ACP,
    OPENAI,
    AcpAgent,
    Agents,
    AgentSpec,
    Catalog,
    ChatAgent,
    PermissionAsk,
    Plan,
    Session,
    Stop,
    Text,
    Thought,
    Tool,
    Turn,
    Update,
    build,
    carried_history,
)
from tests.fakes import FakeChat

FAKE_AGENT = [sys.executable, str(Path(__file__).parent / "acp_agent.py")]


def acp_spec(**overrides: object) -> AgentSpec:
    spec = AgentSpec(name="echo", title="Echo", kind=ACP, command=tuple(FAKE_AGENT))
    return AgentSpec(**{**spec.__dict__, **overrides})  # type: ignore[arg-type]


@pytest.fixture
async def echo() -> AsyncIterator[AcpAgent]:
    agent = AcpAgent(acp_spec())
    yield agent
    await agent.close()


def turn(text: str, session_id: str | None = None, **kwargs: object) -> Turn:
    return Turn("c1", session_id, [{"role": "user", "content": text}], **kwargs)  # type: ignore[arg-type]


async def collect(agent: AcpAgent | ChatAgent, t: Turn) -> list[Update]:
    return [u async for u in agent.run(t)]


def text_of(updates: list[Update]) -> str:
    return "".join(u.text for u in updates if isinstance(u, Text))


def session_of(updates: list[Update]) -> str:
    return next(u.session_id for u in updates if isinstance(u, Session))


def test_an_empty_catalog_is_one_hermes_chat_agent() -> None:
    catalog = Catalog.parse("", environ={})

    assert catalog.default == "hermes"
    assert catalog.spec(None).kind == OPENAI
    assert catalog.as_json()["agents"] == [
        {"name": "hermes", "title": "hermes", "kind": OPENAI, "transport": "http"}
    ]


def test_catalog_reads_stdio_and_websocket_agents() -> None:
    raw = """{
        "claude": {"title": "Claude Code", "command": ["claude-agent-acp"],
                   "pass_env": ["ANTHROPIC_API_KEY", "MISSING"], "env": {"X": 1}, "cwd": "/work"},
        "hermes": {"url": "ws://hermes-acp:8765", "token_env": "TOKEN", "memory": false},
        "api": {"base_url": "http://h/v1/", "api_key_env": "KEY", "model": "m"}
    }"""
    env = {"ANTHROPIC_API_KEY": "sk", "TOKEN": "t0k", "KEY": "k"}

    catalog = Catalog.parse(raw, "hermes", env)

    claude, hermes, api = catalog.specs
    assert (claude.kind, claude.command, claude.cwd) == (ACP, ("claude-agent-acp",), "/work")
    assert claude.env == {"ANTHROPIC_API_KEY": "sk", "X": "1"}
    assert (hermes.kind, hermes.url, hermes.memory) == (ACP, "ws://hermes-acp:8765", False)
    assert hermes.headers == {"Authorization": "Bearer t0k"}
    assert (api.kind, api.base_url, api.api_key, api.model) == (OPENAI, "http://h/v1", "k", "m")
    assert catalog.default == "hermes"
    assert [a["transport"] for a in catalog.as_json()["agents"]] == ["stdio", "websocket", "http"]
    assert "t0k" not in str(catalog.as_json())


@pytest.mark.parametrize(
    ("raw", "default"),
    [
        ('{"a": {"command": "x", "url": "ws://y"}}', ""),
        ('{"a": {}}', "b"),
        ("[]", ""),
        ("{}", ""),
    ],
)
def test_catalog_rejects_bad_settings(raw: str, default: str) -> None:
    with pytest.raises(ValueError, match=r"DASH|both"):
        Catalog.parse(raw, default, {})


def test_catalog_spec_raises_for_an_unknown_agent() -> None:
    with pytest.raises(KeyError):
        Catalog.parse("", environ={}).spec("nope")


def test_build_makes_the_agent_for_each_kind() -> None:
    chat = FakeChat([])
    assert isinstance(build(acp_spec(), chat=lambda _: chat), AcpAgent)
    made = build(AgentSpec("h", "H", OPENAI), chat=lambda _: chat)
    assert isinstance(made, ChatAgent)
    assert made.chat is chat


async def test_chat_agent_sends_context_and_history() -> None:
    chat = FakeChat(["hi ", "there"])
    agent = ChatAgent("hermes", "Hermes", chat)

    updates = await collect(agent, turn("hello", context="You remember tea."))

    assert updates == [Text("hi "), Text("there"), Stop("end_turn")]
    assert chat.seen[0] == [
        {"role": "system", "content": "You remember tea."},
        {"role": "user", "content": "hello"},
    ]
    assert await agent.cancel("s") is False
    await agent.close()


async def test_acp_turn_streams_thoughts_plan_tools_and_text(echo: AcpAgent) -> None:
    updates = await collect(echo, turn("hello", context="You remember tea."))

    assert isinstance(updates[0], Session)
    assert Thought("thinking") in updates
    assert Plan(({"content": "echo", "status": "pending", "priority": "medium"},)) in updates
    tools = [u for u in updates if isinstance(u, Tool)]
    assert [(t.id, t.title, t.kind, t.status) for t in tools] == [
        ("t1", "Read notes", "read", "in_progress"),
        ("t1", "Read notes", "read", "completed"),
    ]
    assert tools[-1].detail == "notes"
    assert text_of(updates) == "echo 1: You remember tea. | hello"
    assert updates[-1] == Stop("end_turn")


async def test_acp_session_is_reused_for_the_next_turn(echo: AcpAgent) -> None:
    first = await collect(echo, turn("one"))
    session_id = session_of(first)

    second = await collect(echo, turn("two", session_id))

    assert not any(isinstance(u, Session) for u in second)
    assert text_of(second) == "echo 2: two"


async def test_acp_memory_off_sends_only_the_user_text() -> None:
    agent = AcpAgent(acp_spec(memory=False))
    try:
        updates = await collect(agent, turn("hello", context="You remember tea."))
    finally:
        await agent.close()

    assert text_of(updates) == "echo 1: hello"


async def test_acp_session_is_loaded_without_replaying_old_updates(echo: AcpAgent) -> None:
    session_id = session_of(await collect(echo, turn("one")))
    echo._live.clear()  # pyright: ignore[reportPrivateUsage]

    updates = await collect(echo, turn("two", session_id))

    assert not any(isinstance(u, Session) for u in updates)
    assert text_of(updates) == "echo 2: two"


async def test_a_lost_session_starts_a_new_one_with_the_history(echo: AcpAgent) -> None:
    history = [
        {"role": "user", "content": "I like tea."},
        {"role": "assistant", "content": "Noted."},
        {"role": "user", "content": "What do I like?"},
    ]

    updates = await collect(echo, Turn("c1", "gone", history))

    assert session_of(updates) != "gone"
    assert "user: I like tea.\n\nassistant: Noted." in text_of(updates)
    assert text_of(updates).endswith("| What do I like?")


async def test_a_dead_agent_process_is_restarted(echo: AcpAgent) -> None:
    await collect(echo, turn("one"))
    process = echo._process  # pyright: ignore[reportPrivateUsage]
    assert process is not None
    process.kill()
    await process.wait()

    updates = await collect(echo, turn("two"))

    assert text_of(updates) == "echo 1: two"


@pytest.mark.parametrize(
    ("choice", "said"),
    [("yes", "allowed"), ("no", "denied"), (None, "denied"), ("bogus", "denied")],
)
async def test_acp_permission_question_goes_to_the_turn(
    echo: AcpAgent, choice: str | None, said: str
) -> None:
    asked: list[PermissionAsk] = []

    async def ask(question: PermissionAsk) -> str | None:
        asked.append(question)
        return choice

    updates = await collect(echo, turn("permission please", ask=ask))

    assert text_of(updates) == said
    assert asked[0].title == "Run rm -rf /tmp/x"
    assert [o["id"] for o in asked[0].options] == ["yes", "no"]
    assert asked[0].id.isalnum()


async def test_acp_cancel_ends_the_turn(echo: AcpAgent) -> None:
    updates: list[Update] = []

    async def read() -> None:
        async for update in echo.run(turn("slow")):
            updates.append(update)
            if isinstance(update, Session):
                assert await echo.cancel(update.session_id)

    await asyncio.wait_for(read(), 10)

    assert updates[-1] == Stop("cancelled")
    assert text_of(updates) == "stopped"


async def test_cancel_without_a_connection_or_session_is_refused(echo: AcpAgent) -> None:
    assert await echo.cancel("s") is False
    await collect(echo, turn("one"))
    assert await echo.cancel(None) is False


async def test_closing_a_turn_early_cancels_it_on_the_agent(echo: AcpAgent) -> None:
    run = echo.run(turn("slow"))
    seen = [await anext(run)]
    while not isinstance(seen[-1], Tool):
        seen.append(await anext(run))
    await run.aclose()
    session_id = session_of(seen)

    updates = await collect(echo, turn("next", session_id))

    assert text_of(updates) == "echo 2: next"


async def test_an_agent_that_will_not_start_raises() -> None:
    agent = AcpAgent(acp_spec(command=(sys.executable, "-c", "pass")))
    with pytest.raises(Exception):  # noqa: B017, PT011
        await collect(agent, turn("hi"))
    await agent.close()


async def test_a_websocket_agent_that_is_down_raises() -> None:
    agent = AcpAgent(acp_spec(command=(), url="ws://127.0.0.1:9/acp"))
    with pytest.raises(OSError):  # noqa: PT011
        await collect(agent, turn("hi"))
    await agent.close()


async def test_agents_registry_falls_back_to_the_default() -> None:
    a = ChatAgent("a", "A", FakeChat([]))
    b = ChatAgent("b", "B", FakeChat([]))
    agents = Agents([a, b], "b")

    assert agents.get(None) is b
    assert agents.get("a") is a
    with pytest.raises(KeyError):
        agents.get("c")
    await agents.close()


def test_carried_history_skips_the_current_message() -> None:
    assert carried_history([{"role": "user", "content": "now"}]) == ""
