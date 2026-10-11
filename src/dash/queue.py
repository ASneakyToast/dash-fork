"""Redis streams job queue.

`dash:jobs` holds one entry per user turn, read by the `workers` consumer group.
Each job also gets its own `dash:events:<job>` stream. The worker appends deltas
there and the API replays it to the browser over SSE, so a page reload mid-reply
picks up from the start.

`dash:activity` is one capped stream for all jobs. The worker appends an entry each time
a job changes state, and plugins read it to show what dash is doing.
"""

import contextlib
import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

JOBS = "dash:jobs"
ACTIVITY = "dash:activity"
ACTIVITY_MAXLEN = 500
GROUP = "workers"
EVENTS_TTL_SECONDS = 3600
# A job a dead worker held this long goes to another worker.
CLAIM_IDLE_MS = 5 * 60 * 1000
# Must stay above the longest XREAD block below.
SOCKET_TIMEOUT_SECONDS = 30


def events_key(job_id: str) -> str:
    return f"dash:events:{job_id}"


@dataclass(frozen=True)
class Job:
    entry_id: str
    job_id: str
    conversation_id: str


@dataclass(frozen=True)
class Activity:
    """One state change of a job, as the worker reported it."""

    id: str
    kind: str
    job_id: str
    conversation_id: str
    data: dict[str, Any]

    @property
    def at(self) -> float:
        """Return the Unix time in seconds when the entry was added."""
        return int(self.id.partition("-")[0]) / 1000

    def as_json(self) -> dict[str, Any]:
        """Return the entry as the JSON that the API sends."""
        return {
            "id": self.id,
            "at": self.at,
            "kind": self.kind,
            "job_id": self.job_id,
            "conversation_id": self.conversation_id,
            "data": self.data,
        }


def activity_from(entry_id: str, fields: dict[str, str]) -> Activity:
    """Return the activity stored in a stream entry."""
    return Activity(
        entry_id,
        fields["kind"],
        fields["job_id"],
        fields["conversation_id"],
        json.loads(fields["data"]),
    )


class Queue:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @classmethod
    def from_url(cls, url: str) -> "Queue":
        # redis-py defaults to a 5 s socket timeout, which kills blocking XREADs early.
        return cls(
            Redis.from_url(url, decode_responses=True, socket_timeout=SOCKET_TIMEOUT_SECONDS)  # pyright: ignore[reportUnknownMemberType]
        )

    async def close(self) -> None:
        await self.redis.aclose()

    async def enqueue(self, conversation_id: str) -> str:
        job_id = uuid.uuid4().hex
        await self.redis.xadd(JOBS, {"job_id": job_id, "conversation_id": conversation_id})
        return job_id

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(JOBS, GROUP, id="0", mkstream=True)
        except ResponseError as ex:
            if "BUSYGROUP" not in str(ex):
                raise

    async def claim(self, consumer: str, block_ms: int = 5000) -> Job | None:
        """Next job for this consumer: first any abandoned one, then a new one."""
        claimed: list[Any] = await self.redis.xautoclaim(
            JOBS, GROUP, consumer, CLAIM_IDLE_MS, "0-0", count=1
        )
        entries = cast("list[tuple[str, dict[str, str]]]", claimed[1])
        if not entries:
            read = cast(
                "list[tuple[str, list[tuple[str, dict[str, str]]]]] | None",
                await self.redis.xreadgroup(GROUP, consumer, {JOBS: ">"}, count=1, block=block_ms),
            )
            entries = read[0][1] if read else []
        if not entries:
            return None
        entry_id, fields = entries[0]
        return Job(entry_id, fields["job_id"], fields["conversation_id"])

    async def ack(self, job: Job) -> None:
        await self.redis.xack(JOBS, GROUP, job.entry_id)
        await self.redis.xdel(JOBS, job.entry_id)

    async def emit(self, job_id: str, kind: str, **data: object) -> None:
        key = events_key(job_id)
        await self.redis.xadd(key, {"kind": kind, "data": json.dumps(data)})
        await self.redis.expire(key, EVENTS_TTL_SECONDS)

    async def publish(self, kind: str, job: Job, **data: object) -> Activity:
        """Append an entry for the job to the shared activity stream and return it."""
        encoded = json.dumps(data)
        entry_id = await self.redis.xadd(
            ACTIVITY,
            {
                "kind": kind,
                "job_id": job.job_id,
                "conversation_id": job.conversation_id,
                "data": encoded,
            },
            maxlen=ACTIVITY_MAXLEN,
            approximate=True,
        )
        return Activity(str(entry_id), kind, job.job_id, job.conversation_id, json.loads(encoded))

    async def recent_activity(self, count: int = 50) -> list[Activity]:
        """Return the newest activity entries, oldest first."""
        newest = cast(
            "list[tuple[str, dict[str, str]]]",
            await self.redis.xrevrange(ACTIVITY, count=count),
        )
        return [activity_from(entry_id, fields) for entry_id, fields in reversed(newest)]

    async def activity(
        self, after: str | None = None, replay: int = 50, block_ms: int = 15000
    ) -> AsyncGenerator[Activity | None]:
        """Yield recent activity, then each new entry, and None whenever the feed is idle."""
        if after is None:
            recent = await self.recent_activity(replay)
            for item in recent:
                yield item
            last = recent[-1].id if recent else "0"
        else:
            last = after
        while True:
            read = cast(
                "list[tuple[str, list[tuple[str, dict[str, str]]]]] | None",
                await self.redis.xread({ACTIVITY: last}, block=block_ms),
            )
            if not read:
                yield None
                continue
            for entry_id, fields in read[0][1]:
                last = entry_id
                yield activity_from(entry_id, fields)

    async def events(self, job_id: str, block_ms: int = 15000) -> AsyncIterator[dict[str, Any]]:
        """Replay then follow a job's events until `done` or `error`."""
        key = events_key(job_id)
        last = "0"
        while True:
            read = cast(
                "list[tuple[str, list[tuple[str, dict[str, str]]]]] | None",
                await self.redis.xread({key: last}, block=block_ms),
            )
            if not read:
                yield {"kind": "ping"}
                continue
            for entry_id, fields in read[0][1]:
                last = entry_id
                event = {"kind": fields["kind"], **json.loads(fields["data"])}
                yield event
                if event["kind"] in ("done", "error"):
                    return

    async def status(self) -> dict[str, int]:
        waiting = int(await self.redis.xlen(JOBS))
        try:
            pending: dict[str, Any] = await self.redis.xpending(JOBS, GROUP)
            in_flight = int(pending["pending"])
        except ResponseError:
            in_flight = 0
        consumers = 0
        with contextlib.suppress(ResponseError):
            consumers = len(cast("list[Any]", await self.redis.xinfo_consumers(JOBS, GROUP)))
        return {"waiting": waiting - in_flight, "in_flight": in_flight, "workers": consumers}
