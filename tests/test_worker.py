import asyncio
import uuid
from typing import Any, cast

import fakeredis
import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

from dash.db import Store
from dash.hermes import Delta
from dash.plugins import Plugins, discover
from dash.queue import Job, Queue
from dash.worker import Worker
from tests import plugin_fixtures
from tests.fakes import FakeChat, FakeEmbedder, FakeExtractor, FakeStore


async def setup(
    chat: FakeChat, facts: list[str]
) -> tuple[Worker, FakeStore, Queue, uuid.UUID, Job]:
    store = FakeStore()
    queue = Queue(fakeredis.FakeAsyncRedis(decode_responses=True))
    worker = Worker(
        store=cast("Store", store),
        queue=queue,
        chat=chat,
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


async def test_reasoning_and_tool_progress_are_streamed_in_order() -> None:
    tool = {"tool": "terminal", "label": "ls", "toolCallId": "c1", "status": "running"}
    chat = FakeChat(
        [
            Delta("reasoning", "Let me look."),
            Delta("tool", data=tool),
            "Two files.",
            Delta("status", data={"message": "ok"}),
        ]
    )
    worker, store, queue, conv_id, job = await setup(chat, [])

    await worker.handle(job)

    got = [e for e in await events(queue) if e["kind"] != "done"]
    assert got == [
        {"kind": "reasoning", "text": "Let me look."},
        {"kind": "tool", **tool},
        {"kind": "delta", "text": "Two files."},
        {"kind": "status", "message": "ok"},
    ]
    saved = (await store.messages(conv_id))[-1]
    assert saved.content == "Two files."
    assert saved.events == got


async def test_saved_events_merge_text_runs() -> None:
    chat = FakeChat(["a" * 40, "b" * 40, Delta("tool", data={"tool": "t"}), "c"])
    worker, store, _, conv_id, job = await setup(chat, [])

    await worker.handle(job)

    saved = (await store.messages(conv_id))[-1]
    assert saved.events == [
        {"kind": "delta", "text": "a" * 40 + "b" * 40},
        {"kind": "tool", "tool": "t"},
        {"kind": "delta", "text": "c"},
    ]


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
