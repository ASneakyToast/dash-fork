from typing import cast

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient

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


def test_nango_errors_become_502(store: FakeStore) -> None:
    def deny(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    nango = Nango("http://nango.invalid", "bad-key")
    nango._client = httpx.AsyncClient(
        base_url="http://nango.invalid", transport=httpx.MockTransport(deny)
    )
    app = create_app(
        store=cast("Store", store),
        queue=Queue(fakeredis.FakeAsyncRedis(decode_responses=True)),
        embedder=FakeEmbedder(),
        nango=nango,
    )
    client = TestClient(app)
    for method, path in [("GET", "/api/connections"), ("POST", "/api/connections/session")]:
        res = client.request(method, path)
        assert res.status_code == 502
        assert "401" in res.json()["detail"]
