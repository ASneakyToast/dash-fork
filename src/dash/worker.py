"""Consumes `dash:jobs`: recall memories, stream a hermes reply, store new memories."""

import asyncio
import logging
import socket
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Protocol

from redis.exceptions import RedisError

from dash.db import Store
from dash.memory import (
    DUPLICATE_DISTANCE,
    RELEVANT_DISTANCE,
    Embedder,
    Extractor,
    system_prompt,
)
from dash.plugins import Context, Plugins
from dash.queue import Job, Queue

log = logging.getLogger(__name__)

# Coalesce deltas so a fast model doesn't write one Redis entry per token.
FLUSH_CHARS = 48
RETRY_SECONDS = 2


class Chat(Protocol):
    def stream(self, messages: Sequence[Mapping[str, str]]) -> AsyncIterator[str]: ...


class Worker:
    def __init__(
        self,
        *,
        store: Store,
        queue: Queue,
        chat: Chat,
        embedder: Embedder,
        extractor: Extractor,
        top_k: int,
        plugins: Plugins | None = None,
    ) -> None:
        self.store = store
        self.queue = queue
        self.chat = chat
        self.embedder = embedder
        self.extractor = extractor
        self.top_k = top_k
        self.plugins = plugins or Plugins()
        self.ctx = Context("worker", store, queue)
        self.name = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"

    async def note(self, kind: str, job: Job, **data: object) -> None:
        """Publish a state change of the job to the activity feed and the plugins."""
        try:
            activity = await self.queue.publish(kind, job, **data)
        except RedisError:
            log.exception("activity publish failed")
            return
        await self.plugins.dispatch(self.ctx, activity)

    async def recall(self, text: str) -> list[str]:
        try:
            embedding = await self.embedder.embed(text)
            hits = await self.store.search_memories(embedding, self.top_k)
        except Exception:
            log.exception("memory recall failed")
            return []
        return [m.content for m, dist in hits if dist <= RELEVANT_DISTANCE]

    async def remember(self, user: str, assistant: str) -> int:
        stored = 0
        try:
            for fact in await self.extractor.extract(user, assistant):
                embedding = await self.embedder.embed(fact)
                nearest = await self.store.search_memories(embedding, 1)
                if nearest and nearest[0][1] < DUPLICATE_DISTANCE:
                    continue
                await self.store.add_memory(fact, embedding, source="conversation")
                stored += 1
        except Exception:
            log.exception("memory extraction failed")
        return stored

    async def handle(self, job: Job) -> None:
        await self.note("started", job)
        conversation_id = uuid.UUID(job.conversation_id)
        history = await self.store.messages(conversation_id)
        if not history or history[-1].role != "user":
            await self.queue.emit(job.job_id, "error", message="No user message to answer.")
            await self.note("failed", job, message="No user message to answer.")
            return
        user_text = history[-1].content
        memories = await self.recall(user_text)
        if memories:
            await self.queue.emit(job.job_id, "memories", items=memories)
            await self.note("recalled", job, count=len(memories))

        messages: list[dict[str, str]] = []
        system = system_prompt(memories)
        if system:
            messages.append({"role": "system", "content": system})
        messages += [{"role": m.role, "content": m.content} for m in history]

        reply: list[str] = []
        buffer = ""
        try:
            async for delta in self.chat.stream(messages):
                reply.append(delta)
                buffer += delta
                if len(buffer) >= FLUSH_CHARS:
                    await self.queue.emit(job.job_id, "delta", text=buffer)
                    buffer = ""
        except Exception as ex:
            log.exception("hermes call failed")
            await self.queue.emit(job.job_id, "error", message=f"hermes: {ex}")
            await self.note("failed", job, message=f"hermes: {ex}")
            return
        if buffer:
            await self.queue.emit(job.job_id, "delta", text=buffer)

        text = "".join(reply)
        message = await self.store.add_message(conversation_id, "assistant", text)
        await self.queue.emit(job.job_id, "done", message_id=message.id)
        await self.note("done", job)
        stored = await self.remember(user_text, text)
        if stored:
            log.info("stored %d new memories", stored)
            await self.note("remembered", job, count=stored)

    async def run(self, stop: asyncio.Event | None = None) -> None:
        await self.queue.ensure_group()
        log.info("worker %s waiting for jobs", self.name)
        while not (stop and stop.is_set()):
            try:
                job = await self.queue.claim(self.name)
            except RedisError:
                log.exception("queue unavailable, retrying")
                await asyncio.sleep(RETRY_SECONDS)
                continue
            if job is None:
                continue
            try:
                await self.handle(job)
            except Exception as ex:
                log.exception("job %s failed", job.job_id)
                await self.queue.emit(job.job_id, "error", message=str(ex))
                await self.note("failed", job, message=str(ex))
            await self.queue.ack(job)
