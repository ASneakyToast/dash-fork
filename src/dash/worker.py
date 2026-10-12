"""Consumes `dash:jobs`: recall memories, run the conversation's agent, store new memories."""

import asyncio
import contextlib
import logging
import socket
import uuid
import weakref
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from redis.exceptions import RedisError

from dash.agents import (
    Agent,
    Agents,
    PermissionAsk,
    Plan,
    Session,
    Stop,
    Text,
    Thought,
    Tool,
    Turn,
)
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
HEARTBEAT_SECONDS = 60
CANCEL_GRACE_SECONDS = 15
THOUGHT_CHARS = 20_000


@dataclass
class Reply:
    """What the agent has said so far in one turn."""

    text: list[str] = field(default_factory=list[str])
    thoughts: list[str] = field(default_factory=list[str])
    tools: dict[str, Tool] = field(default_factory=dict[str, Tool])
    plan: list[dict[str, str]] = field(default_factory=list[dict[str, str]])
    permissions: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    session_id: str | None = None
    stop: str = "end_turn"
    cancelled: bool = False

    def details(self, agent: str) -> dict[str, Any]:
        """Return the details stored with the reply message."""
        found: dict[str, Any] = {
            "agent": agent,
            "stop": self.stop,
            "tools": [t.as_json() for t in self.tools.values()],
            "plan": self.plan,
            "permissions": self.permissions,
            "thoughts": "".join(self.thoughts)[:THOUGHT_CHARS],
        }
        return {k: v for k, v in found.items() if v}


class Worker:
    def __init__(
        self,
        *,
        store: Store,
        queue: Queue,
        agents: Agents,
        embedder: Embedder,
        extractor: Extractor,
        top_k: int,
        plugins: Plugins | None = None,
        concurrency: int = 1,
    ) -> None:
        self.store = store
        self.queue = queue
        self.agents = agents
        self.embedder = embedder
        self.extractor = extractor
        self.top_k = top_k
        self.concurrency = max(1, concurrency)
        self.plugins = plugins or Plugins()
        self.ctx = Context("worker", store, queue)
        self.name = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
        self.running: dict[str, Job] = {}
        self.asks: dict[tuple[str, str], asyncio.Future[str | None]] = {}
        self.locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    async def note(self, kind: str, job: Job, **data: object) -> None:
        """Publish a state change of the job to the activity feed and the plugins."""
        try:
            activity = await self.queue.publish(kind, job, **data)
        except RedisError:
            log.exception("activity publish failed")
            return
        await self.plugins.dispatch(self.ctx, activity)

    async def fail(self, job: Job, message: str) -> None:
        """Report the job as failed to the browser and the activity feed."""
        await self.queue.emit(job.job_id, "error", message=message)
        await self.note("failed", job, message=message)

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

    async def ask(self, job: Job, reply: Reply, question: PermissionAsk) -> str | None:
        """Show the agent's permission question in the browser and return the chosen option."""
        if reply.cancelled:
            return None
        future: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        self.asks[(job.job_id, question.id)] = future
        try:
            await self.queue.emit(job.job_id, "permission", **question.as_json())
            await self.note("waiting", job, title=question.title)
            choice = await future
        finally:
            self.asks.pop((job.job_id, question.id), None)
        reply.permissions.append(question.as_json() | {"option_id": choice})
        await self.queue.emit(job.job_id, "permission_done", id=question.id, option_id=choice)
        await self.note("answered", job, option_id=choice)
        return choice

    def answer(self, job: Job, ask_id: str | None, choice: str | None) -> None:
        """Resolve one waiting permission question of the job, or all of them for None."""
        waiting = [
            f
            for (job_id, key), f in self.asks.items()
            if job_id == job.job_id and ask_id in (None, key) and not f.done()
        ]
        for future in waiting:
            future.set_result(choice)

    async def watch(self, job: Job, agent: Agent, reply: Reply, reader: asyncio.Task[None]) -> None:
        """Apply the browser's cancel and permission answers to the running job."""
        async for control in self.queue.controls(job.job_id):
            if control["kind"] == "permission":
                self.answer(job, str(control.get("id")), control.get("option_id"))
            elif control["kind"] == "cancel" and not reply.cancelled:
                reply.cancelled = True
                self.answer(job, None, None)
                await self.note("cancelling", job)
                if await agent.cancel(reply.session_id):
                    await asyncio.sleep(CANCEL_GRACE_SECONDS)
                reader.cancel()

    async def read(self, job: Job, agent: Agent, turn: Turn, reply: Reply) -> None:
        """Run the agent's turn and stream what it says to the browser."""
        pending = {"delta": "", "thought": ""}

        async def flush(*kinds: str) -> None:
            for kind in kinds:
                if pending[kind]:
                    await self.queue.emit(job.job_id, kind, text=pending[kind])
                    pending[kind] = ""

        async def add(kind: str, text: str) -> None:
            await flush(*(k for k in pending if k != kind))
            pending[kind] += text
            if len(pending[kind]) >= FLUSH_CHARS:
                await flush(kind)

        async for update in agent.run(turn):
            match update:
                case Text(text=text):
                    reply.text.append(text)
                    await add("delta", text)
                case Thought(text=text):
                    reply.thoughts.append(text)
                    await add("thought", text)
                case Tool():
                    await flush(*pending)
                    reply.tools[update.id] = update
                    await self.queue.emit(job.job_id, "tool", tool=update.as_json())
                case Plan(entries=entries):
                    await flush(*pending)
                    reply.plan = list(entries)
                    await self.queue.emit(job.job_id, "plan", entries=reply.plan)
                case Session(session_id=session_id):
                    reply.session_id = session_id
                    await self.store.set_session(uuid.UUID(turn.conversation_id), session_id)
                case Stop(reason=reason):
                    reply.stop = reason
        await flush(*pending)

    async def converse(self, job: Job, agent: Agent, turn: Turn, reply: Reply) -> bool:
        """Fill the reply from the agent's turn. Return False after reporting a failure."""
        reader = asyncio.create_task(self.read(job, agent, turn, reply))
        watcher = asyncio.create_task(self.watch(job, agent, reply, reader))
        try:
            await reader
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if not reply.cancelled or (current is not None and current.cancelling()):
                raise
            reply.stop = "cancelled"
        except Exception as ex:
            log.exception("agent %s failed", agent.name)
            await self.fail(job, f"{agent.name}: {ex}")
            return False
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError, RedisError):
                await watcher
            self.answer(job, None, None)
        return True

    async def handle(self, job: Job) -> None:
        await self.note("started", job)
        conversation_id = uuid.UUID(job.conversation_id)
        conversation = await self.store.conversation(conversation_id)
        history = await self.store.messages(conversation_id)
        if conversation is None or not history or history[-1].role != "user":
            await self.fail(job, "No user message to answer.")
            return
        try:
            agent = self.agents.get(conversation.agent)
        except KeyError:
            await self.fail(job, f"Unknown agent {conversation.agent!r}.")
            return
        user_text = history[-1].content
        memories = await self.recall(user_text)
        if memories:
            await self.queue.emit(job.job_id, "memories", items=memories)
            await self.note("recalled", job, count=len(memories))

        reply = Reply(session_id=conversation.session_id)
        turn = Turn(
            conversation_id=job.conversation_id,
            session_id=conversation.session_id,
            history=[{"role": m.role, "content": m.content} for m in history],
            context=system_prompt(memories) or "",
            ask=partial(self.ask, job, reply),
        )
        if not await self.converse(job, agent, turn, reply):
            return

        text = "".join(reply.text)
        message = await self.store.add_message(
            conversation_id, "assistant", text, reply.details(agent.name)
        )
        await self.queue.emit(job.job_id, "done", message_id=message.id, stop=reply.stop)
        await self.note("done", job, stop=reply.stop)
        if reply.cancelled or not text:
            return
        stored = await self.remember(user_text, text)
        if stored:
            log.info("stored %d new memories", stored)
            await self.note("remembered", job, count=stored)

    async def process(self, job: Job) -> None:
        """Handle the job after any earlier job of its conversation, then acknowledge it."""
        lock = self.locks.setdefault(job.conversation_id, asyncio.Lock())
        async with lock:
            self.running[job.entry_id] = job
            try:
                await self.handle(job)
            except Exception as ex:
                log.exception("job %s failed", job.job_id)
                await self.fail(job, str(ex))
            finally:
                self.running.pop(job.entry_id, None)
            await self.queue.ack(job)

    async def heartbeat(self) -> None:
        """Keep the jobs this worker runs claimed, however long their turns take."""
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                await self.queue.touch(self.name, list(self.running))
            except RedisError:
                log.exception("heartbeat failed")

    async def run(self, stop: asyncio.Event | None = None) -> None:
        await self.queue.ensure_group()
        log.info("worker %s waiting for jobs, %d at a time", self.name, self.concurrency)
        tasks: set[asyncio.Task[None]] = set()
        beat = asyncio.create_task(self.heartbeat())
        try:
            while not (stop and stop.is_set()):
                if len(tasks) >= self.concurrency:
                    await asyncio.wait(tasks, timeout=1, return_when=asyncio.FIRST_COMPLETED)
                    continue
                try:
                    job = await self.queue.claim(self.name)
                except RedisError:
                    log.exception("queue unavailable, retrying")
                    await asyncio.sleep(RETRY_SECONDS)
                    continue
                if job is None or job.entry_id in self.running:
                    continue
                task = asyncio.create_task(self.process(job))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            beat.cancel()
