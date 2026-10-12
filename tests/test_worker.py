import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

import fakeredis
import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

from dash.agents import ACP, AcpAgent, Agents, AgentSpec, ChatAgent, PermissionAsk
from dash.db import Store
from dash.plugins import Plugins, discover
from dash.queue import Job, Queue
from dash.worker import Reply, Worker
from tests import plugin_fixtures
from tests.fakes import FakeChat, FakeEmbedder, FakeExtractor, FakeStore
from tests.test_agents import FAKE_AGENT


async def setup(
    chat: FakeChat, facts: list[str]
) -> tuple[Worker, FakeStore, Queue, uuid.UUID, Job]:
    store = FakeStore()
    queue = Queue(fakeredis.FakeAsyncRedis(decode_responses=True))
    worker = Worker(
        store=cast("Store", store),
        queue=queue,
        agents=Agents([ChatAgent("hermes", "Hermes", chat)]),
        embedder=FakeEmbedder(),
        extractor=FakeExtractor(facts),
        top_k=8,
    )
    conv = await store.create_conversation()
    await store.add_message(conv.id, "user", "what do I like?")
    return worker, store, queue, conv.id, Job("1-0", "job", str(conv.id))


async def events(queue: Queue) -> list[dict[str, Any]]:
    return [e async for e in queue.events("job")]


async def kinds(queue: Queue) -> list[str]:
    return [a.kind for a in await queue.recent_activity()]


async def test_reply_is_streamed_saved_and_memories_learned() -> None:
    chat = FakeChat(["You like ", "tea."])
    worker, store, queue, conv_id, job = await setup(chat, ["The user likes tea."])
    await store.add_memory("what do I like?", await FakeEmbedder().embed("what do I like?"))

    await worker.handle(job)

    got = await events(queue)
    assert got[0] == {"kind": "memories", "items": ["what do I like?"]}
    assert "".join(e["text"] for e in got if e["kind"] == "delta") == "You like tea."
    assert got[-1]["kind"] == "done"
    assert [m.content for m in await store.messages(conv_id)][-1] == "You like tea."
    assert chat.seen[0][0]["role"] == "system"
    assert "what do I like?" in chat.seen[0][0]["content"]
    assert [m.content for m in store.mems][-1] == "The user likes tea."


async def test_duplicate_fact_is_not_stored_twice() -> None:
    worker, store, _, _, job = await setup(FakeChat(["ok"]), ["The user likes tea."])
    await store.add_memory("The user likes tea.", await FakeEmbedder().embed("The user likes tea."))

    await worker.handle(job)

    assert [m.content for m in store.mems] == ["The user likes tea."]


async def test_hermes_failure_reports_error_and_saves_nothing() -> None:
    worker, store, queue, conv_id, job = await setup(FakeChat(["partial"], fail=True), [])

    await worker.handle(job)

    got = await events(queue)
    assert got[-1] == {"kind": "error", "message": "hermes: upstream down"}
    assert [m.role for m in await store.messages(conv_id)] == ["user"]


async def test_job_without_user_message_errors() -> None:
    worker, store, queue, conv_id, job = await setup(FakeChat(["x"]), [])
    await store.add_message(conv_id, "assistant", "already answered")

    await worker.handle(job)

    assert (await events(queue))[-1]["kind"] == "error"


async def test_run_survives_queue_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    worker, _, queue, _, _ = await setup(FakeChat(["x"]), [])
    stop = asyncio.Event()
    calls = 0

    async def flaky_claim(consumer: str, block_ms: int = 5000) -> Job | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RedisTimeoutError("read timed out")
        stop.set()
        return None

    monkeypatch.setattr(queue, "claim", flaky_claim)
    monkeypatch.setattr("dash.worker.RETRY_SECONDS", 0)

    await worker.run(stop)

    assert calls == 2


async def test_activity_follows_a_job_through_to_remembered() -> None:
    worker, store, queue, _, job = await setup(FakeChat(["ok"]), ["The user likes tea."])
    await store.add_memory("what do I like?", await FakeEmbedder().embed("what do I like?"))

    await worker.handle(job)

    assert await kinds(queue) == ["started", "recalled", "done", "remembered"]
    recalled = (await queue.recent_activity())[1]
    assert recalled.data == {"count": 1}
    assert (recalled.job_id, recalled.conversation_id) == ("job", job.conversation_id)


async def test_activity_reports_a_hermes_failure() -> None:
    worker, _, queue, _, job = await setup(FakeChat(["partial"], fail=True), [])

    await worker.handle(job)

    activity = await queue.recent_activity()
    assert [a.kind for a in activity] == ["started", "failed"]
    assert activity[-1].data == {"message": "hermes: upstream down"}


async def test_activity_reports_a_job_with_nothing_to_answer() -> None:
    worker, store, queue, conv_id, job = await setup(FakeChat(["x"]), [])
    await store.add_message(conv_id, "assistant", "already answered")

    await worker.handle(job)

    assert await kinds(queue) == ["started", "failed"]


async def test_run_reports_an_exception_that_escapes_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, _, queue, _, job = await setup(FakeChat(["x"]), [])
    stop = asyncio.Event()
    claims = [job, None]

    async def claim(consumer: str, block_ms: int = 5000) -> Job | None:
        got = claims.pop(0)
        if not claims:
            stop.set()
        return got

    async def broken(_: Job) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(queue, "claim", claim)
    monkeypatch.setattr(worker, "handle", broken)

    await worker.run(stop)

    assert await kinds(queue) == ["failed"]


async def test_a_queue_that_cannot_take_activity_does_not_fail_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, store, queue, conv_id, job = await setup(FakeChat(["ok"]), [])

    async def refuse(*_: object, **__: object) -> None:
        raise RedisTimeoutError("read timed out")

    monkeypatch.setattr(queue, "publish", refuse)

    await worker.handle(job)

    assert [m.content for m in await store.messages(conv_id)][-1] == "ok"
    assert (await events(queue))[-1]["kind"] == "done"


async def test_plugins_hear_the_worker_activity() -> None:
    plugin_fixtures.seen.clear()
    plugins = discover(["tests.plugin_fixtures:hello", "tests.plugin_fixtures:fragile"])
    worker, _, _, _, job = await setup(FakeChat(["ok"]), [])
    worker.plugins = plugins

    await worker.handle(job)

    assert [a.kind for a in plugin_fixtures.seen] == ["started", "done"]


async def test_a_worker_without_plugins_still_works() -> None:
    worker, _, _, _, job = await setup(FakeChat(["ok"]), [])

    await worker.handle(job)

    assert worker.plugins.active == []
    assert isinstance(worker.plugins, Plugins)


class HangingChat:
    """A chat that sends one piece and then waits forever."""

    async def stream(self, messages: object) -> AsyncIterator[str]:
        yield "partial"
        await asyncio.Event().wait()


async def acp_setup(
    text: str, facts: list[str] | None = None
) -> tuple[Worker, FakeStore, Queue, uuid.UUID, Job]:
    store = FakeStore()
    queue = Queue(fakeredis.FakeAsyncRedis(decode_responses=True))
    echo = AcpAgent(AgentSpec(name="echo", title="Echo", kind=ACP, command=tuple(FAKE_AGENT)))
    worker = Worker(
        store=cast("Store", store),
        queue=queue,
        agents=Agents([ChatAgent("hermes", "Hermes", FakeChat(["x"])), echo]),
        embedder=FakeEmbedder(),
        extractor=FakeExtractor(facts or []),
        top_k=8,
    )
    conv = await store.create_conversation(agent="echo")
    await store.add_message(conv.id, "user", text)
    return worker, store, queue, conv.id, Job("1-0", "job", str(conv.id))


async def first(queue: Queue, kind: str) -> dict[str, Any]:
    async for event in queue.events("job"):
        if event["kind"] == kind:
            return event
    raise AssertionError(kind)


async def test_an_acp_turn_is_streamed_saved_and_bound_to_its_session() -> None:
    worker, store, queue, conv_id, job = await acp_setup("hello", ["The user said hello."])
    try:
        await worker.handle(job)
    finally:
        await worker.agents.close()

    got = await events(queue)
    assert [e["kind"] for e in got] == ["thought", "plan", "tool", "tool", "delta", "done"]
    assert got[3]["tool"] == got[2]["tool"] | {"status": "completed", "detail": "notes"}
    assert got[-1]["stop"] == "end_turn"
    reply = (await store.messages(conv_id))[-1]
    assert reply.content == "echo 1: hello"
    assert reply.details["agent"] == "echo"
    assert reply.details["thoughts"] == "thinking"
    assert [t["status"] for t in reply.details["tools"]] == ["completed"]
    assert reply.details["plan"] == [{"content": "echo", "status": "pending", "priority": "medium"}]
    assert store.convs[conv_id].session_id
    assert [m.content for m in store.mems] == ["The user said hello."]


async def test_the_browser_answers_a_permission_question() -> None:
    worker, store, queue, conv_id, job = await acp_setup("permission please")
    try:
        task = asyncio.create_task(worker.handle(job))
        question = await asyncio.wait_for(first(queue, "permission"), 10)
        assert question["title"] == "Run rm -rf /tmp/x"
        assert "waiting" in await kinds(queue)
        await queue.control("job", "permission", id=question["id"], option_id="yes")
        await asyncio.wait_for(task, 10)
    finally:
        await worker.agents.close()

    got = await events(queue)
    assert {"kind": "permission_done", "id": question["id"], "option_id": "yes"} in got
    reply = (await store.messages(conv_id))[-1]
    assert reply.content == "allowed"
    assert [(a["title"], a["option_id"]) for a in reply.details["permissions"]] == [
        ("Run rm -rf /tmp/x", "yes")
    ]
    assert "answered" in await kinds(queue)


async def test_cancel_stops_an_acp_turn_and_learns_nothing() -> None:
    worker, store, queue, conv_id, job = await acp_setup("slow", ["The user is slow."])
    try:
        task = asyncio.create_task(worker.handle(job))
        await asyncio.wait_for(first(queue, "tool"), 10)
        await queue.control("job", "cancel")
        await asyncio.wait_for(task, 10)
    finally:
        await worker.agents.close()

    assert (await events(queue))[-1]["stop"] == "cancelled"
    reply = (await store.messages(conv_id))[-1]
    assert (reply.content, reply.details["stop"]) == ("stopped", "cancelled")
    assert store.mems == []
    assert "cancelling" in await kinds(queue)


async def test_cancel_stops_a_chat_turn_that_cannot_cancel_itself() -> None:
    store = FakeStore()
    queue = Queue(fakeredis.FakeAsyncRedis(decode_responses=True))
    worker = Worker(
        store=cast("Store", store),
        queue=queue,
        agents=Agents([ChatAgent("hermes", "Hermes", HangingChat())]),
        embedder=FakeEmbedder(),
        extractor=FakeExtractor(["never"]),
        top_k=8,
    )
    conv = await store.create_conversation()
    await store.add_message(conv.id, "user", "hi")
    job = Job("1-0", "job", str(conv.id))
    task = asyncio.create_task(worker.handle(job))
    await asyncio.sleep(0.05)

    await queue.control("job", "cancel")
    await asyncio.wait_for(task, 10)

    assert [m.content for m in await store.messages(conv.id)][-1] == "partial"
    assert store.mems == []


async def test_cancel_cuts_off_an_agent_that_ignores_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dash.worker.CANCEL_GRACE_SECONDS", 0.1)
    monkeypatch.setattr("dash.agents.CANCEL_GRACE_SECONDS", 0.1)
    worker, store, queue, conv_id, job = await acp_setup("stubborn")
    try:
        task = asyncio.create_task(worker.handle(job))
        await asyncio.wait_for(first(queue, "tool"), 10)
        await queue.control("job", "cancel")
        await asyncio.wait_for(task, 10)
    finally:
        await worker.agents.close()

    assert (await store.messages(conv_id))[-1].details["stop"] == "cancelled"


async def test_a_question_after_stop_is_denied_without_asking() -> None:
    worker, _, queue, _, job = await acp_setup("x")
    reply = Reply(cancelled=True)

    assert await worker.ask(job, reply, PermissionAsk("q", "t", ())) is None
    assert await events_now(queue) == []


async def events_now(queue: Queue) -> list[str]:
    entries = cast("list[tuple[str, dict[str, str]]]", await queue.redis.xrange("dash:events:job"))
    return [fields["kind"] for _, fields in entries]


async def test_cancel_before_the_session_exists_stops_reading() -> None:
    worker, store, queue, conv_id, job = await acp_setup("slow")
    await queue.control("job", "cancel")
    try:
        await asyncio.wait_for(worker.handle(job), 10)
    finally:
        await worker.agents.close()

    assert (await store.messages(conv_id))[-1].details["stop"] == "cancelled"


async def test_a_conversation_with_an_unknown_agent_errors() -> None:
    worker, store, queue, conv_id, job = await setup(FakeChat(["x"]), [])
    store.convs[conv_id].agent = "gone"

    await worker.handle(job)

    assert (await events(queue))[-1] == {"kind": "error", "message": "Unknown agent 'gone'."}


async def test_run_handles_jobs_side_by_side(monkeypatch: pytest.MonkeyPatch) -> None:
    worker, store, queue, _, job = await setup(FakeChat(["x"]), [])
    worker.concurrency = 2
    other = await store.create_conversation()
    jobs = [job, Job("2-0", "job2", str(other.id)), None]
    stop = asyncio.Event()
    both = asyncio.Barrier(2)

    async def claim(consumer: str, block_ms: int = 5000) -> Job | None:
        got = jobs.pop(0) if jobs else None
        if got is None:
            await asyncio.sleep(0.01)
        return got

    async def handle(_: Job) -> None:
        await asyncio.wait_for(both.wait(), 5)
        stop.set()

    monkeypatch.setattr(queue, "claim", claim)
    monkeypatch.setattr(worker, "handle", handle)

    await asyncio.wait_for(worker.run(stop), 10)

    assert worker.running == {}


async def test_heartbeat_keeps_running_jobs_claimed(monkeypatch: pytest.MonkeyPatch) -> None:
    worker, _, queue, _, _ = await setup(FakeChat(["x"]), [])
    touched: list[list[str]] = []
    enough = asyncio.Event()

    async def touch(consumer: str, entry_ids: list[str]) -> None:
        touched.append(entry_ids)
        if len(touched) == 2:
            raise RedisTimeoutError("down")
        if len(touched) == 3:
            enough.set()

    monkeypatch.setattr(queue, "touch", touch)
    monkeypatch.setattr("dash.worker.HEARTBEAT_SECONDS", 0)
    worker.running["5-0"] = Job("5-0", "j", "c")

    beat = asyncio.create_task(worker.heartbeat())
    await asyncio.wait_for(enough.wait(), 5)
    beat.cancel()

    assert touched[0] == ["5-0"]
