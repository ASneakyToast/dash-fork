import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from dash.config import Settings
from dash.db import Memory, Store
from dash.memory import Embedder
from dash.nango import Nango
from dash.queue import Queue

STATIC = Path(__file__).parent / "static"


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


class NewMemory(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    tags: list[str] = Field(default_factory=list[str])


def memory_json(memory: Memory, distance: float | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": memory.id,
        "content": memory.content,
        "source": memory.source,
        "tags": memory.tags,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
    }
    if distance is not None:
        out["distance"] = round(distance, 4)
    return out


def create_app(
    *,
    store: Store,
    queue: Queue,
    embedder: Embedder,
    nango: Nango,
    public: dict[str, str] | None = None,
    routers: Sequence[APIRouter] = (),
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
) -> FastAPI:
    app = FastAPI(title="dash", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/config")
    async def config() -> dict[str, Any]:
        return {"nango": nango.enabled, **(public or {})}

    @app.get("/api/conversations")
    async def conversations() -> list[dict[str, Any]]:
        return [
            {"id": str(c.id), "title": c.title, "updated_at": c.updated_at.isoformat()}
            for c in await store.conversations()
        ]

    @app.post("/api/conversations", status_code=201)
    async def create_conversation() -> dict[str, str]:
        conversation = await store.create_conversation()
        return {"id": str(conversation.id), "title": conversation.title}

    @app.get("/api/conversations/{conversation_id}/messages")
    async def messages(conversation_id: uuid.UUID) -> list[dict[str, Any]]:
        return [
            {"id": m.id, "role": m.role, "content": m.content}
            for m in await store.messages(conversation_id)
        ]

    @app.post("/api/conversations/{conversation_id}/messages", status_code=202)
    async def send(conversation_id: uuid.UUID, body: NewMessage) -> dict[str, str]:
        if await store.conversation(conversation_id) is None:
            raise HTTPException(404, "No such conversation.")
        await store.add_message(conversation_id, "user", body.content)
        job_id = await queue.enqueue(str(conversation_id))
        return {"job_id": job_id}

    @app.get("/api/jobs/{job_id}/events")
    async def events(job_id: str, request: Request) -> StreamingResponse:
        if not job_id.isalnum():
            raise HTTPException(400, "Bad job id.")

        async def stream() -> AsyncIterator[str]:
            async for event in queue.events(job_id):
                if await request.is_disconnected():
                    return
                if event["kind"] == "ping":
                    yield ": ping\n\n"
                else:
                    yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.get("/api/queue")
    async def queue_status() -> dict[str, int]:
        return await queue.status()

    @app.get("/api/memories")
    async def memories(q: str = "") -> list[dict[str, Any]]:
        if q.strip():
            hits = await store.search_memories(await embedder.embed(q), 50)
            return [memory_json(m, d) for m, d in hits]
        return [memory_json(m) for m in await store.memories()]

    @app.post("/api/memories", status_code=201)
    async def add_memory(body: NewMemory) -> dict[str, Any]:
        embedding = await embedder.embed(body.content)
        return memory_json(await store.add_memory(body.content, embedding, "manual", body.tags))

    @app.delete("/api/memories/{memory_id}", status_code=204)
    async def delete_memory(memory_id: int) -> None:
        if not await store.delete_memory(memory_id):
            raise HTTPException(404, "No such memory.")

    def need_nango() -> None:
        if not nango.enabled:
            raise HTTPException(503, "Nango is not configured.")

    @app.get("/api/connections")
    async def connections() -> dict[str, Any]:
        need_nango()
        try:
            return {
                "integrations": await nango.integrations(),
                "connections": await nango.connections(),
            }
        except httpx.HTTPError as ex:
            raise HTTPException(502, f"Nango: {ex}") from ex

    @app.post("/api/connections/session")
    async def connect_session() -> dict[str, str]:
        need_nango()
        return {"token": await nango.connect_session()}

    @app.delete("/api/connections/{provider_config_key}/{connection_id}", status_code=204)
    async def disconnect(provider_config_key: str, connection_id: str) -> None:
        need_nango()
        await nango.delete_connection(connection_id, provider_config_key)

    for router in routers:
        app.include_router(router)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def create_production_app() -> FastAPI:
    """uvicorn factory: wires real Postgres, Redis, memory models and Nango from the environment."""
    from dash.github import GitHubApi, GitHubStore, create_router
    from dash.memory import memory_models

    settings = Settings.from_env()
    store = Store.from_url(settings.database_url)
    queue = Queue.from_url(settings.redis_url)
    nango = Nango(settings.nango_url, settings.nango_secret_key)
    memory = memory_models(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        yield
        await store.close()
        await queue.close()
        await nango.close()
        await memory.close()

    return create_app(
        store=store,
        queue=queue,
        embedder=memory,
        nango=nango,
        public={
            "nango_host": settings.nango_public_url or settings.nango_url,
            "nango_connect_url": settings.nango_connect_url,
        },
        routers=[
            create_router(
                store=GitHubStore(store.sessions),
                api=GitHubApi(),
                public_url=settings.public_url,
            )
        ],
        lifespan=lifespan,
    )
