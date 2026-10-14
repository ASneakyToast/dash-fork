import asyncio
import uuid
from typing import Any, cast

import fakeredis
import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

from dash.db import Store
from dash.hermes import Delta
from dash.queue import Job, Queue
from dash.worker import Worker
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
