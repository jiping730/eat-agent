"""Durable conversation storage for P03.

The workflow remains responsible for reasoning. This module only persists the
conversation history and Grill context so a process or container restart does
not erase an in-progress conversation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from config import settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ConversationRecord(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    current_goal: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grill_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class MessageRecord(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    response_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


@dataclass(frozen=True)
class ConversationSnapshot:
    conversation_id: str
    user_id: str
    messages: list[dict[str, str]]
    grill_context: dict[str, Any]
    current_goal: str | None


class ConversationAccessError(PermissionError):
    """Raised when a conversation is accessed by a different user."""


class ConversationStore:
    """SQLAlchemy-backed store with SQLite support for local tests."""

    def __init__(self, database_url: str | None = None, *, auto_create_schema: bool | None = None) -> None:
        self.database_url = database_url or settings.database_url
        connect_args = {"check_same_thread": False} if self.database_url.startswith("sqlite") else {}
        self.engine = create_engine(self.database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        # Explicit SQLite URLs are used by local development and unit tests.
        # They should remain self-contained even when the process environment
        # is production-like and disables automatic schema creation for
        # PostgreSQL. Production PostgreSQL continues to be migration-owned.
        if auto_create_schema is None:
            should_create = settings.auto_create_schema or (
                database_url is not None and self.database_url.startswith("sqlite")
            )
        else:
            should_create = auto_create_schema
        if should_create:
            Base.metadata.create_all(self.engine)

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")

    def load(self, conversation_id: str, user_id: str) -> ConversationSnapshot:
        with self.session_factory() as session:
            conversation = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.user_id == user_id,
                )
            )
            if conversation is None:
                existing = session.get(ConversationRecord, conversation_id)
                if existing is not None:
                    raise ConversationAccessError("无权访问该会话")
                conversation = ConversationRecord(
                    id=conversation_id,
                    user_id=user_id,
                    grill_context={},
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
                session.add(conversation)
                session.commit()
                return ConversationSnapshot(conversation_id, user_id, [], {}, None)

            messages = session.scalars(
                select(MessageRecord)
                .where(MessageRecord.conversation_id == conversation_id)
                .order_by(MessageRecord.id)
            ).all()
            return ConversationSnapshot(
                conversation_id=conversation_id,
                user_id=user_id,
                messages=[{"role": item.role, "content": item.content} for item in messages],
                grill_context=dict(conversation.grill_context or {}),
                current_goal=conversation.current_goal,
            )

    def save_turn(
        self,
        *,
        conversation_id: str,
        user_id: str,
        request_id: str,
        user_message: str,
        assistant_message: str,
        grill_context: dict[str, Any],
        current_goal: str | None,
        response_type: str,
        target_field: str | None,
    ) -> None:
        now = utc_now()
        with self.session_factory.begin() as session:
            conversation = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.user_id == user_id,
                )
            )
            if conversation is None:
                existing = session.get(ConversationRecord, conversation_id)
                if existing is not None:
                    raise ConversationAccessError("无权访问该会话")
                conversation = ConversationRecord(
                    id=conversation_id,
                    user_id=user_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(conversation)

            conversation.current_goal = current_goal
            conversation.grill_context = dict(grill_context or {})
            conversation.updated_at = now

            existing_user = session.scalar(
                select(MessageRecord).where(
                    MessageRecord.conversation_id == conversation_id,
                    MessageRecord.request_id == request_id,
                    MessageRecord.role == "user",
                )
            )
            if existing_user is None:
                session.add(
                    MessageRecord(
                        conversation_id=conversation_id,
                        request_id=request_id,
                        role="user",
                        content=user_message,
                        created_at=now,
                    )
                )

            existing_assistant = session.scalar(
                select(MessageRecord).where(
                    MessageRecord.conversation_id == conversation_id,
                    MessageRecord.request_id == request_id,
                    MessageRecord.role == "assistant",
                )
            )
            if existing_assistant is None:
                session.add(
                    MessageRecord(
                        conversation_id=conversation_id,
                        request_id=request_id,
                        role="assistant",
                        content=assistant_message,
                        response_type=response_type,
                        target_field=target_field,
                        created_at=now,
                    )
                )
