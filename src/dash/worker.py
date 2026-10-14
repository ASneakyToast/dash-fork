"""Consumes `dash:jobs`: recall memories, stream a hermes reply, store new memories."""

import asyncio
import logging
import socket
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Protocol

from redis.exceptions import RedisError

from dash.db import Store
from dash.hermes import Delta
from dash.memory import (
    DUPLICATE_DISTANCE,
    RELEVANT_DISTANCE,
    Embedder,
    Extractor,
    system_prompt,
)
from dash.queue import Job, Queue

log = logging.getLogger(__name__)

# Coalesce deltas so a fast model doesn't write one Redis entry per token.
FLUSH_CHARS = 48
RETRY_SECONDS = 2


class Chat(Protocol):
    def stream(self, messages: Sequence[Mapping[str, str]]) -> AsyncIterator[Delta]: ...


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
    ) -> None:
        self.store = store
        self.queue = queue
        self.chat = chat
        self.embedder = embedder
        self.extractor = extractor
        self.top_k = top_k
        self.name = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"

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
        conversation_id = uuid.UUID(job.conversation_id)
        history = await self.store.messages(conversation_id)
        if not history or history[-1].role != "user":
            await self.queue.emit(job.job_id, "error", message="No user message to answer.")
            return
        user_text = history[-1].content
        memories = await self.recall(user_text)
        if memories:
            await self.queue.emit(job.job_id, "memories", items=memories)

        messages: list[dict[str, str]] = []
        system = system_prompt(memories)
        if system:
            messages.append({"role": "system", "content": system})
        messages += [{"role": m.role, "content": m.content} for m in history]

        reply: list[str] = []
        buffers = {"text": "", "reasoning": ""}
        events = {"text": "delta", "reasoning": "reasoning"}

        async def flush(kind: str) -> None:
            if buffers[kind]:
                await self.queue.emit(job.job_id, events[kind], text=buffers[kind])
                buffers[kind] = ""

        try:
            async for delta in self.chat.stream(messages):
                if delta.kind in buffers:
                    other = "reasoning" if delta.kind == "text" else "text"
                    await flush(other)
                    if delta.kind == "text":
                        reply.append(delta.text)
                    buffers[delta.kind] += delta.text
                    if len(buffers[delta.kind]) >= FLUSH_CHARS:
                        await flush(delta.kind)
                else:
                    await flush("reasoning")
                    await flush("text")
                    await self.queue.emit(job.job_id, delta.kind, **delta.data)
        except Exception as ex:
            log.exception("hermes call failed")
            await self.queue.emit(job.job_id, "error", message=f"hermes: {ex}")
            return
        await flush("reasoning")
        await flush("text")

        text = "".join(reply)
        message = await self.store.add_message(conversation_id, "assistant", text)
        await self.queue.emit(job.job_id, "done", message_id=message.id)
        stored = await self.remember(user_text, text)
        if stored:
            log.info("stored %d new memories", stored)

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
            await self.queue.ack(job)
