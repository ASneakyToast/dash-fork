import itertools
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from dash.db import Authorization, Conversation, Memory, Message
from dash.github.api import Installation, NewApp
from dash.github.db import APP, INSTALLATION, PROVIDER

CLIENT_SECRET = "fake-client-secret"  # noqa: S105


class FakeStore:
    """In-memory Store. Distance is 0 for an exact text match, else 1."""

    def __init__(self) -> None:
        self.convs: dict[uuid.UUID, Conversation] = {}
        self.msgs: list[Message] = []
        self.mems: list[Memory] = []
        self._ids = itertools.count(1)

    async def conversations(self, limit: int = 50) -> list[Conversation]:
        return list(self.convs.values())[:limit]

    async def create_conversation(
        self, title: str | None = None, agent: str | None = None
    ) -> Conversation:
        c = Conversation(id=uuid.uuid4(), title=title or "New conversation", agent=agent)
        c.updated_at = datetime.now(UTC)
        self.convs[c.id] = c
        return c

    async def conversation(self, conversation_id: uuid.UUID) -> Conversation | None:
        return self.convs.get(conversation_id)

    async def messages(self, conversation_id: uuid.UUID) -> list[Message]:
        return [m for m in self.msgs if m.conversation_id == conversation_id]

    async def set_session(self, conversation_id: uuid.UUID, session_id: str) -> None:
        self.convs[conversation_id].session_id = session_id

    async def add_message(
        self,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        details: dict[str, Any] | None = None,
    ) -> Message:
        m = Message(
            id=next(self._ids),
            conversation_id=conversation_id,
            role=role,
            content=content,
            details=details or {},
        )
        self.msgs.append(m)
        return m

    async def memories(self, limit: int = 200) -> list[Memory]:
        return self.mems[:limit]

    async def search_memories(
        self, embedding: Sequence[float], limit: int
    ) -> list[tuple[Memory, float]]:
        hits = [(m, 0.0 if m.embedding == list(embedding) else 1.0) for m in self.mems]
        return sorted(hits, key=lambda h: h[1])[:limit]

    async def add_memory(
        self,
        content: str,
        embedding: Sequence[float],
        source: str = "manual",
        tags: Sequence[str] = (),
    ) -> Memory:
        m = Memory(
            id=next(self._ids),
            content=content,
            embedding=list(embedding),
            source=source,
            tags=list(tags),
            created_at=datetime.now(UTC),
        )
        self.mems.append(m)
        return m

    async def delete_memory(self, memory_id: int) -> bool:
        before = len(self.mems)
        self.mems = [m for m in self.mems if m.id != memory_id]
        return len(self.mems) < before


class FakeEmbedder:
    """Every text gets its own fixed vector, so equal texts are distance 0."""

    async def embed(self, text: str) -> list[float]:
        return [float(len(text)), float(sum(map(ord, text)) % 997)]


class FakeExtractor:
    def __init__(self, facts: list[str]) -> None:
        self.facts = facts

    async def extract(self, user: str, assistant: str) -> list[str]:
        return self.facts


class FakeChat:
    def __init__(self, chunks: list[str], fail: bool = False) -> None:
        self.chunks = chunks
        self.fail = fail
        self.seen: list[list[dict[str, str]]] = []

    async def stream(self, messages: Sequence[Mapping[str, str]]) -> AsyncIterator[str]:
        self.seen.append([dict(m) for m in messages])
        for chunk in self.chunks:
            yield chunk
        if self.fail:
            raise RuntimeError("upstream down")


class FakeGitHubStore:
    """An in-memory GitHubStore."""

    def __init__(self) -> None:
        self.rows: list[Authorization] = []
        self._ids = itertools.count(1)

    async def apps(self) -> list[Authorization]:
        """Return every stored app."""
        return [r for r in self.rows if r.kind == APP]

    async def installations(self) -> list[Authorization]:
        """Return every stored installation."""
        return [r for r in self.rows if r.kind == INSTALLATION]

    async def save_app(self, app: NewApp) -> Authorization:
        """Store the given app and return its row."""
        row = Authorization(
            id=next(self._ids),
            provider=PROVIDER,
            kind=APP,
            external_id=str(app.id),
            account=app.owner,
            details={
                "slug": app.slug,
                "name": app.name,
                "html_url": app.html_url,
                "client_id": app.client_id,
            },
            secrets={"pem": app.pem, "client_secret": app.client_secret},
        )
        self.rows.append(row)
        return row

    async def save_installations(
        self, app: Authorization, installations: Sequence[Installation]
    ) -> None:
        """Replace the installations of the given app."""
        self.rows = [r for r in self.rows if r.parent_id != app.id] + [
            Authorization(
                id=next(self._ids),
                provider=PROVIDER,
                kind=INSTALLATION,
                external_id=str(i.id),
                parent_id=app.id,
                account=i.account,
                details={"html_url": i.html_url},
                secrets={},
            )
            for i in installations
        ]

    async def delete_app(self, app_id: int) -> bool:
        """Delete the given app and its installations. Return True if it existed."""
        before = len(self.rows)
        self.rows = [r for r in self.rows if app_id not in (r.id, r.parent_id)]
        return len(self.rows) < before


class FakeGitHubApi:
    """A GitHub API that returns fixed apps and installations."""

    def __init__(self, installations: list[Installation]) -> None:
        self.installs = installations
        self.codes: list[str] = []

    async def convert_manifest(self, code: str) -> NewApp:
        """Return a fixed new app for the given code."""
        self.codes.append(code)
        return NewApp(
            id=123,
            slug="dash-test",
            name="dash test",
            owner="octocat",
            html_url="https://github.com/apps/dash-test",
            client_id="Iv1.abc",
            client_secret=CLIENT_SECRET,
            webhook_secret=None,
            pem="fake-pem",
        )

    async def installations(self, app: Authorization) -> list[Installation]:
        """Return the fixed installations."""
        return self.installs
