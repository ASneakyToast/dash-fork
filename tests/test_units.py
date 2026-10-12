import io
import json

import httpx
import pytest
from alembic import command
from alembic.script import ScriptDirectory

from dash.config import Settings
from dash.db import EMBED_DIM, alembic_config, async_url
from dash.hermes import parse_sse_line
from dash.memory import OpenAICompatible, memory_models, parse_facts, system_prompt

URL = "postgresql://dash:p%40ss@db:5432/dash"


def test_async_url_sets_driver_and_keeps_password() -> None:
    assert async_url(URL) == "postgresql+asyncpg://dash:p%40ss@db:5432/dash"


def test_single_migration_head() -> None:
    assert len(ScriptDirectory.from_config(alembic_config(URL)).get_heads()) == 1


def test_offline_upgrade_creates_vector_tables() -> None:
    config = alembic_config(URL)
    config.output_buffer = io.StringIO()

    command.upgrade(config, "head", sql=True)

    sql = config.output_buffer.getvalue()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "embedding VECTOR(1024) NOT NULL" in sql
    assert "USING hnsw (embedding vector_cosine_ops)" in sql
    assert "REFERENCES conversations (id) ON DELETE CASCADE" in sql


def test_parse_sse_line() -> None:
    chunk = 'data: {"choices":[{"delta":{"content":"hi"}}]}'
    assert parse_sse_line(chunk) == "hi"
    assert parse_sse_line("data: [DONE]") is None
    assert parse_sse_line(": keep-alive") is None
    assert parse_sse_line('data: {"choices":[{"delta":{"role":"assistant"}}]}') is None
    assert parse_sse_line('data: {"choices":[]}') is None


def test_parse_facts() -> None:
    assert parse_facts('Here: ["The user likes tea.", " ", 3]') == ["The user likes tea."]
    assert parse_facts("[]") == []
    assert parse_facts("no json") == []
    assert parse_facts("[not json]") == []
    assert parse_facts('{"a": [1]}') == []


def test_system_prompt() -> None:
    assert system_prompt([]) is None
    assert "- The user likes tea." in (system_prompt(["The user likes tea."]) or "")


async def test_openai_compatible_embed_asks_for_the_column_size() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer sk-test"
        body = json.loads(request.content)
        assert (body["model"], body["input"], body["dimensions"]) == ("embed", "tea", EMBED_DIM)
        return httpx.Response(200, json={"data": [{"embedding": [0.5] * EMBED_DIM}]})

    models = OpenAICompatible(
        "https://gateway.test/v1", "sk-test", "embed", "extract", httpx.MockTransport(handler)
    )

    assert await models.embed("tea") == [0.5] * EMBED_DIM


async def test_openai_compatible_extract_parses_facts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "extract"
        assert "<user>\nI like tea\n</user>" in body["messages"][0]["content"]
        reply = {"role": "assistant", "content": '["The user likes tea."]'}
        return httpx.Response(200, json={"choices": [{"message": reply}]})

    models = OpenAICompatible(
        "https://gateway.test/v1", "", "embed", "extract", httpx.MockTransport(handler)
    )

    assert await models.extract("I like tea", "Noted.") == ["The user likes tea."]


def test_memory_base_url_selects_openai_compatible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("MEMORY_BASE_URL", "https://gateway.test/v1/")

    assert isinstance(memory_models(Settings.from_env()), OpenAICompatible)
