import uuid
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Self, cast

from alembic import command
from alembic.config import Config
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Text,
    UniqueConstraint,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.engine import CursorResult, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

MIGRATIONS = Path(__file__).parent / "migrations"

# Titan Text Embeddings v2 at its default size. Changing it needs a migration and a re-embed.
EMBED_DIM = 1024


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, default="New conversation")
    agent: Mapped[str | None] = mapped_column(Text, default=None)
    session_id: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    source: Mapped[str] = mapped_column(Text, default="manual")
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Authorization(Base):
    """A credential set for an external provider, such as a GitHub App or installation."""

    __tablename__ = "authorizations"
    __table_args__ = (UniqueConstraint("provider", "kind", "external_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    provider: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("authorizations.id", ondelete="CASCADE"), index=True
    )
    account: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    secrets: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def async_url(url: str) -> str:
    # Most tooling hands out postgresql:// DSNs; SQLAlchemy needs the driver named.
    return make_url(url).set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    # Passed via attributes, not set_main_option, so a `%` in the password isn't interpolated.
    config.attributes["url"] = async_url(url)
    return config


def migrate(url: str) -> None:
    """Upgrade to head. Blocking, and runs its own event loop: call via `asyncio.to_thread`."""
    command.upgrade(alembic_config(url), "head")


class Store:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._session = async_sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def from_url(cls, url: str) -> Self:
        # Lazy: no connection is made until the first query.
        return cls(create_async_engine(async_url(url), pool_size=5, pool_pre_ping=True))

    @classmethod
    @asynccontextmanager
    async def connect(cls, url: str) -> AsyncGenerator[Self]:
        store = cls.from_url(url)
        try:
            yield store
        finally:
            await store.close()

    @property
    def sessions(self) -> async_sessionmaker[AsyncSession]:
        """Return the session factory for feature stores that share this engine."""
        return self._session

    async def close(self) -> None:
        await self._engine.dispose()

    async def conversations(self, limit: int = 50) -> Sequence[Conversation]:
        async with self._session() as session:
            rows = await session.scalars(
                select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
            )
            return rows.all()

    async def create_conversation(
        self, title: str | None = None, agent: str | None = None
    ) -> Conversation:
        conversation = Conversation(id=uuid.uuid4(), title=title or "New conversation", agent=agent)
        async with self._session() as session, session.begin():
            session.add(conversation)
        return conversation

    async def conversation(self, conversation_id: uuid.UUID) -> Conversation | None:
        async with self._session() as session:
            return await session.get(Conversation, conversation_id)

    async def messages(self, conversation_id: uuid.UUID) -> Sequence[Message]:
        async with self._session() as session:
            rows = await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id)
            )
            return rows.all()

    async def set_session(self, conversation_id: uuid.UUID, session_id: str) -> None:
        """Bind the conversation to the given agent session."""
        async with self._session() as session, session.begin():
            conversation = await session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.session_id = session_id

    async def add_message(
        self,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        details: dict[str, Any] | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id, role=role, content=content, details=details or {}
        )
        async with self._session() as session, session.begin():
            session.add(message)
            conversation = await session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.updated_at = func.now()
                # The first user message names the conversation.
                if role == "user" and conversation.title == "New conversation":
                    conversation.title = content.strip().splitlines()[0][:80] or conversation.title
        return message

    async def memories(self, limit: int = 200) -> Sequence[Memory]:
        async with self._session() as session:
            rows = await session.scalars(
                select(Memory).order_by(Memory.created_at.desc()).limit(limit)
            )
            return rows.all()

    async def search_memories(
        self, embedding: Sequence[float], limit: int
    ) -> list[tuple[Memory, float]]:
        """Nearest memories by cosine distance (0 = same, 2 = opposite)."""
        distance = Memory.embedding.cosine_distance(embedding)
        async with self._session() as session:
            rows = await session.execute(
                select(Memory, distance.label("distance")).order_by(distance).limit(limit)
            )
            return [(memory, float(dist)) for memory, dist in rows.tuples().all()]

    async def add_memory(
        self,
        content: str,
        embedding: Sequence[float],
        source: str = "manual",
        tags: Sequence[str] = (),
    ) -> Memory:
        memory = Memory(content=content, embedding=list(embedding), source=source, tags=list(tags))
        async with self._session() as session, session.begin():
            session.add(memory)
        return memory

    async def delete_memory(self, memory_id: int) -> bool:
        async with self._session() as session, session.begin():
            result = await session.execute(delete(Memory).where(Memory.id == memory_id))
            return bool(cast("CursorResult[Any]", result).rowcount)
