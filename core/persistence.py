"""Durable conversation storage for P03.

The workflow remains responsible for reasoning. This module only persists the
conversation history and Grill context so a process or container restart does
not erase an in-progress conversation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from config import settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Normalize database datetimes before comparing them with utc_now().

    SQLite does not preserve timezone information for SQLAlchemy DateTime
    columns, while PostgreSQL does. Keeping this normalization at the storage
    boundary makes expiry and token checks behave identically in local tests
    and in production.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_expired(value: datetime) -> bool:
    return _as_utc(value) <= utc_now()


def conversation_expiry() -> datetime:
    return utc_now() + timedelta(days=max(1, settings.conversation_ttl_days))


class Base(DeclarativeBase):
    pass


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    roles: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class RefreshTokenRecord(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ConversationRecord(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="新会话", nullable=False)
    current_goal: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grill_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=conversation_expiry)
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

    __table_args__ = (
        UniqueConstraint("conversation_id", "request_id", "role", name="uq_messages_request_role"),
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("conversation_id", "request_id", name="uq_idempotency_conversation_request"),
    )


@dataclass(frozen=True)
class ConversationSnapshot:
    conversation_id: str
    user_id: str
    messages: list[dict[str, str]]
    grill_context: dict[str, Any]
    current_goal: str | None
    title: str = "新会话"
    version: int = 1
    expires_at: datetime | None = None


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

    def create_user(self, *, user_id: str, username: str, password_hash: str) -> UserRecord:
        with self.session_factory.begin() as session:
            if session.scalar(select(UserRecord).where(UserRecord.username == username)) is not None:
                raise ValueError("用户名已存在")
            user = UserRecord(id=user_id, username=username, password_hash=password_hash, roles=[])
            session.add(user)
            return user

    def get_user_by_username(self, username: str) -> UserRecord | None:
        with self.session_factory() as session:
            return session.scalar(select(UserRecord).where(UserRecord.username == username))

    def get_user(self, user_id: str) -> UserRecord | None:
        with self.session_factory() as session:
            return session.get(UserRecord, user_id)

    def save_refresh_token(self, *, user_id: str, token_hash: str, expires_at: datetime) -> None:
        with self.session_factory.begin() as session:
            session.add(RefreshTokenRecord(user_id=user_id, token_hash=token_hash, expires_at=expires_at))

    def get_refresh_token(self, token_hash: str) -> RefreshTokenRecord | None:
        with self.session_factory() as session:
            token = session.scalar(select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == token_hash))
            if token is None or token.revoked_at is not None or _is_expired(token.expires_at):
                return None
            return token

    def revoke_refresh_token(self, token_hash: str) -> None:
        with self.session_factory.begin() as session:
            token = session.scalar(select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == token_hash))
            if token is not None:
                token.revoked_at = utc_now()

    def list_conversations(self, user_id: str) -> list[ConversationRecord]:
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(ConversationRecord)
                    .where(
                        ConversationRecord.user_id == user_id,
                        ConversationRecord.archived_at.is_(None),
                        ConversationRecord.expires_at > utc_now(),
                    )
                    .order_by(ConversationRecord.updated_at.desc())
                ).all()
            )

    def create_conversation(self, *, conversation_id: str, user_id: str, title: str = "新会话") -> ConversationRecord:
        with self.session_factory.begin() as session:
            conversation = ConversationRecord(
                id=conversation_id,
                user_id=user_id,
                title=title[:200] or "新会话",
                grill_context={},
                expires_at=conversation_expiry(),
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(conversation)
            return conversation

    def archive_conversation(self, conversation_id: str, user_id: str) -> None:
        with self.session_factory.begin() as session:
            conversation = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.user_id == user_id,
                )
            )
            if conversation is None:
                if session.get(ConversationRecord, conversation_id) is not None:
                    raise ConversationAccessError("无权访问该会话")
                raise KeyError("会话不存在")
            conversation.archived_at = utc_now()

    def delete_conversation(self, conversation_id: str, user_id: str) -> None:
        """Permanently delete one user-owned conversation and its dependent data."""
        with self.session_factory.begin() as session:
            conversation = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.user_id == user_id,
                )
            )
            if conversation is None:
                if session.get(ConversationRecord, conversation_id) is not None:
                    raise ConversationAccessError("无权访问该会话")
                raise KeyError("会话不存在")
            session.execute(delete(MessageRecord).where(MessageRecord.conversation_id == conversation_id))
            session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.conversation_id == conversation_id))
            session.delete(conversation)

    def get_idempotent_response(self, conversation_id: str, user_id: str, request_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            record = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.conversation_id == conversation_id,
                    IdempotencyRecord.user_id == user_id,
                    IdempotencyRecord.request_id == request_id,
                )
            )
            return dict(record.response_json) if record is not None else None

    def load(self, conversation_id: str, user_id: str) -> ConversationSnapshot:
        with self.session_factory() as session:
            conversation = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.user_id == user_id,
                    ConversationRecord.expires_at > utc_now(),
                )
            )
            if conversation is None:
                existing = session.get(ConversationRecord, conversation_id)
                if existing is not None:
                    if _is_expired(existing.expires_at):
                        raise KeyError("会话已过期")
                    raise ConversationAccessError("无权访问该会话")
                conversation = ConversationRecord(
                    id=conversation_id,
                    user_id=user_id,
                    title="新会话",
                    grill_context={},
                    expires_at=conversation_expiry(),
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
                title=conversation.title,
                version=conversation.version,
                expires_at=conversation.expires_at,
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
        response_payload: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        with self.session_factory.begin() as session:
            conversation = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.user_id == user_id,
                    ConversationRecord.archived_at.is_(None),
                    ConversationRecord.expires_at > utc_now(),
                ).with_for_update()
            )
            if conversation is None:
                existing = session.get(ConversationRecord, conversation_id)
                if existing is not None:
                    if _is_expired(existing.expires_at):
                        raise KeyError("会话已过期")
                    raise ConversationAccessError("无权访问该会话")
                conversation = ConversationRecord(
                    id=conversation_id,
                    user_id=user_id,
                    title=user_message[:200] or "新会话",
                    expires_at=conversation_expiry(),
                    created_at=now,
                    updated_at=now,
                )
                session.add(conversation)

            conversation.current_goal = current_goal
            conversation.grill_context = dict(grill_context or {})
            conversation.updated_at = now
            conversation.version += 1

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

            if response_payload is not None:
                existing_idempotency = session.scalar(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.conversation_id == conversation_id,
                        IdempotencyRecord.request_id == request_id,
                    )
                )
                if existing_idempotency is None:
                    session.add(
                        IdempotencyRecord(
                            conversation_id=conversation_id,
                            user_id=user_id,
                            request_id=request_id,
                            response_json=dict(response_payload),
                            created_at=now,
                        )
                    )
