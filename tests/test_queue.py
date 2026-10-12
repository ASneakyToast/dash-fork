import asyncio

import fakeredis
import pytest

from dash.queue import ACTIVITY, JOBS, Job, Queue


@pytest.fixture
def queue() -> Queue:
    return Queue(fakeredis.FakeAsyncRedis(decode_responses=True))


async def test_enqueue_claim_ack(queue: Queue) -> None:
    await queue.ensure_group()
    job_id = await queue.enqueue("conv-1")

    job = await queue.claim("w1", block_ms=10)

    assert job is not None
    assert (job.job_id, job.conversation_id) == (job_id, "conv-1")
    assert await queue.status() == {"waiting": 0, "in_flight": 1, "workers": 1}
    await queue.ack(job)
    assert await queue.redis.xlen(JOBS) == 0
    assert await queue.claim("w1", block_ms=10) is None


async def test_ensure_group_twice_is_fine(queue: Queue) -> None:
    await queue.ensure_group()
    await queue.ensure_group()


async def test_events_replay_until_done(queue: Queue) -> None:
    await queue.emit("job", "delta", text="Hel")
    await queue.emit("job", "delta", text="lo")
    await queue.emit("job", "done", message_id=7)
    await queue.emit("job", "delta", text="after done is ignored")

    events = [e async for e in queue.events("job")]

    assert events == [
        {"kind": "delta", "text": "Hel"},
        {"kind": "delta", "text": "lo"},
        {"kind": "done", "message_id": 7},
    ]
    assert 0 < await queue.redis.ttl("dash:events:job") <= 3600


JOB = Job("1-0", "job-1", "conv-1")


async def test_publish_returns_the_entry_that_recent_activity_reads_back(queue: Queue) -> None:
    first = await queue.publish("started", JOB)
    second = await queue.publish("recalled", JOB, count=2)

    assert await queue.recent_activity() == [first, second]
    assert second.data == {"count": 2}
    assert (second.job_id, second.conversation_id) == ("job-1", "conv-1")
    assert second.as_json() == {
        "id": second.id,
        "at": second.at,
        "kind": "recalled",
        "job_id": "job-1",
        "conversation_id": "conv-1",
        "data": {"count": 2},
    }


async def test_recent_activity_is_the_newest_n_oldest_first(queue: Queue) -> None:
    [await queue.publish(str(n), JOB) for n in range(5)]

    assert [a.kind for a in await queue.recent_activity(3)] == ["2", "3", "4"]


async def test_activity_at_is_the_redis_timestamp(queue: Queue) -> None:
    activity = await queue.publish("started", JOB)

    assert activity.at == int(activity.id.split("-")[0]) / 1000
    assert activity.at > 0


async def test_activity_stream_is_capped(queue: Queue, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dash.queue.ACTIVITY_MAXLEN", 10)

    [await queue.publish("started", JOB) for _ in range(300)]

    assert await queue.redis.xlen(ACTIVITY) < 300


async def test_activity_replays_then_follows_then_pings(queue: Queue) -> None:
    await queue.publish("started", JOB)
    feed = queue.activity(block_ms=10)

    replayed = await anext(feed)
    assert replayed is not None
    assert replayed.kind == "started"
    assert await anext(feed) is None
    await queue.publish("done", JOB)
    followed = await asyncio.wait_for(anext(feed), 1)
    assert followed is not None
    assert followed.kind == "done"
    await feed.aclose()


async def test_activity_resumes_after_an_entry_without_replaying(queue: Queue) -> None:
    seen = await queue.publish("started", JOB)
    await queue.publish("done", JOB)
    feed = queue.activity(after=seen.id, block_ms=10)

    resumed = await anext(feed)

    assert resumed is not None
    assert resumed.kind == "done"
    await feed.aclose()


async def test_activity_on_an_empty_feed_pings(queue: Queue) -> None:
    feed = queue.activity(block_ms=10)

    assert await anext(feed) is None
    await queue.publish("started", JOB)
    got = await asyncio.wait_for(anext(feed), 1)
    assert got is not None
    assert got.kind == "started"
    await feed.aclose()
