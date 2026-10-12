import asyncio
from typing import Any, cast

import fakeredis
import pytest
from fastapi.testclient import TestClient

from dash.agents import Catalog
from dash.db import Store
from dash.nango import Nango
from dash.queue import Queue
from dash.web import create_app
from tests.fakes import FakeEmbedder, FakeStore


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def client(store: FakeStore) -> TestClient:
    app = create_app(
        store=cast("Store", store),
        queue=Queue(fakeredis.FakeAsyncRedis(decode_responses=True)),
        embedder=FakeEmbedder(),
        nango=Nango("http://nango.invalid", ""),
    )
    return TestClient(app)


def test_index_and_health(client: TestClient) -> None:
    assert 'src="/static/app.js"' in client.get("/").text
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/static/app.js").status_code == 200


def test_send_message_enqueues_job(client: TestClient, store: FakeStore) -> None:
    conv = client.post("/api/conversations").json()

    response = client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "hi"})

    assert response.status_code == 202
    assert response.json()["job_id"].isalnum()
    assert [m.content for m in store.msgs] == ["hi"]
    assert client.get("/api/queue").json()["waiting"] == 1


def test_send_to_unknown_conversation_is_404(client: TestClient) -> None:
    url = "/api/conversations/00000000-0000-0000-0000-000000000000/messages"
    assert client.post(url, json={"content": "hi"}).status_code == 404


def test_memories_add_search_delete(client: TestClient) -> None:
    created = client.post("/api/memories", json={"content": "The user likes tea."}).json()

    hits = client.get("/api/memories", params={"q": "The user likes tea."}).json()
    assert hits[0]["content"] == "The user likes tea."
    assert hits[0]["distance"] == 0
    assert client.delete(f"/api/memories/{created['id']}").status_code == 204
    assert client.get("/api/memories").json() == []
    assert client.delete(f"/api/memories/{created['id']}").status_code == 404


def test_connections_need_nango(client: TestClient) -> None:
    assert client.get("/api/config").json()["nango"] is False
    assert client.get("/api/connections").status_code == 503


def test_bad_job_id_rejected(client: TestClient) -> None:
    assert client.get("/api/jobs/a:b/events").status_code == 400


@pytest.fixture
def agent_client(store: FakeStore) -> tuple[TestClient, Queue]:
    queue = Queue(fakeredis.FakeAsyncRedis(decode_responses=True))
    catalog = Catalog.parse(
        '{"hermes": {}, "claude": {"title": "Claude Code", "command": ["claude-agent-acp"]}}',
        "claude",
        {},
    )
    app = create_app(
        store=cast("Store", store),
        queue=queue,
        embedder=FakeEmbedder(),
        nango=Nango("http://nango.invalid", ""),
        catalog=catalog,
    )
    return TestClient(app), queue


def test_agents_are_listed(agent_client: tuple[TestClient, Queue]) -> None:
    client, _ = agent_client

    got = client.get("/api/agents").json()

    assert got["default"] == "claude"
    assert [(a["name"], a["transport"]) for a in got["agents"]] == [
        ("hermes", "http"),
        ("claude", "stdio"),
    ]


def test_a_conversation_is_bound_to_the_chosen_agent(
    agent_client: tuple[TestClient, Queue], store: FakeStore
) -> None:
    client, _ = agent_client

    picked = client.post("/api/conversations", json={"agent": "hermes"}).json()
    default = client.post("/api/conversations").json()

    assert (picked["agent"], default["agent"]) == ("hermes", "claude")
    listed = {c["id"]: c["agent"] for c in client.get("/api/conversations").json()}
    assert listed == {picked["id"]: "hermes", default["id"]: "claude"}
    assert client.post("/api/conversations", json={"agent": "nope"}).status_code == 400


def test_messages_carry_their_details(client: TestClient, store: FakeStore) -> None:
    conv = client.post("/api/conversations").json()
    conv_id = next(iter(store.convs))
    asyncio.run(store.add_message(conv_id, "assistant", "ok", {"stop": "cancelled"}))

    got = client.get(f"/api/conversations/{conv['id']}/messages").json()

    assert got == [
        {"id": 1, "role": "assistant", "content": "ok", "details": {"stop": "cancelled"}}
    ]


async def control_entries(queue: Queue, job_id: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    async for entry in queue.controls(job_id, block_ms=1):
        entries.append(entry)
        if len(entries) == 2:
            return entries
    return entries


def test_cancel_and_permission_answers_reach_the_worker(
    agent_client: tuple[TestClient, Queue],
) -> None:
    client, queue = agent_client

    assert client.post("/api/jobs/abc/cancel").status_code == 202
    answer = client.post("/api/jobs/abc/permissions/q1", json={"option_id": "yes"})

    assert answer.status_code == 202
    assert asyncio.run(control_entries(queue, "abc")) == [
        {"kind": "cancel"},
        {"kind": "permission", "id": "q1", "option_id": "yes"},
    ]
    assert client.post("/api/jobs/a-b/cancel").status_code == 400
    assert client.post("/api/jobs/abc/permissions/q-1", json={}).status_code == 400
