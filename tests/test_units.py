import io

from alembic import command
from alembic.script import ScriptDirectory

from dash.db import alembic_config, async_url
from dash.hermes import Delta, parse_sse_frame
from dash.memory import parse_facts, system_prompt

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


def test_parse_sse_frame() -> None:
    assert parse_sse_frame(None, '{"choices":[{"delta":{"content":"hi"}}]}') == [
        Delta("text", "hi")
    ]
    assert parse_sse_frame(None, "[DONE]") == []
    assert parse_sse_frame(None, '{"choices":[{"delta":{"role":"assistant"}}]}') == []
    assert parse_sse_frame(None, '{"choices":[]}') == []
    assert parse_sse_frame(None, '{"choices":[{"delta":{"reasoning_content":"hmm"}}]}') == [
        Delta("reasoning", "hmm")
    ]
    tool = '{"tool":"terminal","label":"ls","toolCallId":"c1","status":"running"}'
    assert parse_sse_frame("hermes.tool.progress", tool) == [
        Delta(
            "tool",
            data={"tool": "terminal", "label": "ls", "toolCallId": "c1", "status": "running"},
        )
    ]
    assert parse_sse_frame("hermes.status", '{"message":"retrying"}') == [
        Delta("status", data={"message": "retrying"})
    ]
    assert parse_sse_frame("approval.request", '{"x":1}') == []


def test_parse_facts() -> None:
    assert parse_facts('Here: ["The user likes tea.", " ", 3]') == ["The user likes tea."]
    assert parse_facts("[]") == []
    assert parse_facts("no json") == []
    assert parse_facts("[not json]") == []
    assert parse_facts('{"a": [1]}') == []


def test_system_prompt() -> None:
    assert system_prompt([]) is None
    assert "- The user likes tea." in (system_prompt(["The user likes tea."]) or "")
