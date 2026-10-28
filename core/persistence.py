"""Durable conversation storage for P03.

The workflow remains responsible for reasoning. This module only persists the
conversation history and Grill context so a process or container restart does
not erase an in-progress conversation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import threading
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    inspect,
    or_,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
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


class TenantRecord(Base):
    """A small-platform workspace used as the isolation boundary."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    owner_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class TenantMembershipRecord(Base):
    """A user's role inside one tenant: owner, admin, or member."""

    __tablename__ = "tenant_memberships"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class TenantSettingsRecord(Base):
    """Small, JSON-backed tenant configuration; no separate config service."""

    __tablename__ = "tenant_settings"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    model_alias: Mapped[str | None] = mapped_column(String(128), nullable=True)
    grill_profile: Mapped[Any] = mapped_column(JSON, default=dict, nullable=False)
    knowledge_scope: Mapped[Any] = mapped_column(JSON, default=lambda: ["public"], nullable=False)
    usage_limit: Mapped[Any] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    roles: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


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
    tenant_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="新会话", nullable=False)
    current_goal: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grill_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=conversation_expiry)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


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

    __table_args__ = (UniqueConstraint("conversation_id", "request_id", "role", name="uq_messages_request_role"),)


class MessageFeedbackRecord(Base):
    __tablename__ = "message_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tenant_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    rating: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_message_feedback_user"),)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tenant_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (UniqueConstraint("conversation_id", "request_id", name="uq_idempotency_conversation_request"),)


class MemoryConsentRecord(Base):
    """Explicit per-user consent for durable assistant memory."""

    __tablename__ = "memory_consents"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class UserMemoryRecord(Base):
    """User-owned memory records that can be exported or erased."""

    __tablename__ = "user_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    user_input: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_output: Mapped[str] = mapped_column(Text, nullable=False)
    quality: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class UserProfileRecord(Base):
    """Explicit, user-owned long-term nutrition profile."""

    __tablename__ = "user_profiles"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(32), nullable=True)
    activity_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    health_goal: Mapped[str | None] = mapped_column(String(64), nullable=True)
    allergies: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    dietary_preferences: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    disliked_foods: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    common_ingredients: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    meals_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    consent_granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class UserProfileEventRecord(Base):
    """Content-safe audit trail for explicit profile changes."""

    __tablename__ = "user_profile_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_fields: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ProfileSuggestionRecord(Base):
    """A user-confirmable profile candidate extracted from an explicit turn."""

    __tablename__ = "profile_suggestions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    source_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class UserExperienceSettingsRecord(Base):
    """Non-sensitive per-user presentation preferences inside one tenant."""

    __tablename__ = "user_experience_settings"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    show_model_info: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_sources: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_safety_details: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    answer_style: Mapped[str] = mapped_column(String(32), nullable=False, default="standard")
    pinned_shortcuts: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class KnowledgeDocumentRecord(Base):
    """A managed knowledge document and its current lifecycle state."""

    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    scope: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="tenant", server_default="tenant")
    owner_user_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_name: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="draft")
    latest_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    access_groups: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["public"], nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "scope",
            "owner_user_id",
            "source_name",
            name="uq_knowledge_scope_owner_source_name",
        ),
    )


class KnowledgeDocumentVersionRecord(Base):
    """Immutable text snapshot for one managed document version."""

    __tablename__ = "knowledge_document_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_knowledge_document_version"),)


class KnowledgeBuildRecord(Base):
    """Durable progress and outcome for a knowledge index build."""

    __tablename__ = "knowledge_builds"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    scope: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="tenant", server_default="tenant")
    owner_user_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    index_version: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="building")
    phase: Mapped[str] = mapped_column(String(64), nullable=False, default="preparing")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    initiated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeRetrievalEventRecord(Base):
    """Minimal, content-safe retrieval analytics event."""

    __tablename__ = "knowledge_retrieval_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    scope: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="tenant", server_default="tenant")
    owner_user_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    query: Mapped[str] = mapped_column(String(2_000), nullable=False)
    access_groups: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["public"], nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_document_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    initiated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


@dataclass(frozen=True)
class ConversationSnapshot:
    conversation_id: str
    user_id: str
    messages: list[dict[str, Any]]
    grill_context: dict[str, Any]
    current_goal: str | None
    tenant_id: str | None = None
    title: str = "新会话"
    version: int = 1
    expires_at: datetime | None = None


class ConversationAccessError(PermissionError):
    """Raised when a conversation is accessed by a different user."""


class ConversationStore:
    """SQLAlchemy-backed store with SQLite support for local tests."""

    _tenant_init_lock = threading.RLock()

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
            if self.database_url.startswith("sqlite"):
                self._ensure_sqlite_compatibility()

    def _ensure_sqlite_compatibility(self) -> None:
        """Add newly introduced nullable columns to a pre-migration dev DB.

        Production databases are migration-owned.  Local development has
        historically used ``create_all`` and may contain an older app.db;
        adding only nullable columns keeps that workflow usable without
        pretending that ``create_all`` is a replacement for Alembic.
        """

        inspector = inspect(self.engine)
        with self.engine.begin() as connection:
            for table in Base.metadata.sorted_tables:
                if table.name not in inspector.get_table_names():
                    continue
                existing = {item["name"] for item in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name in existing:
                        continue
                    column_type = column.type.compile(dialect=self.engine.dialect)
                    default_sql = ""
                    if not column.nullable and column.server_default is not None:
                        default_value = getattr(column.server_default, "arg", None)
                        if isinstance(default_value, str):
                            escaped = default_value.replace("'", "''")
                            default_sql = f" DEFAULT '{escaped}'"
                        elif default_value is not None:
                            default_sql = f" DEFAULT {default_value}"
                    connection.exec_driver_sql(
                        f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}{default_sql}'
                    )
                    existing.add(column.name)
            connection.exec_driver_sql(
                'UPDATE "conversations" SET "expires_at" = ? WHERE "expires_at" IS NULL',
                (conversation_expiry().replace(tzinfo=None),),
            )

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")

    @staticmethod
    def _tenant_payload(tenant: TenantRecord, membership: TenantMembershipRecord | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "status": tenant.status,
            "owner_id": tenant.owner_id,
            "created_at": _as_utc(tenant.created_at).isoformat(),
            "updated_at": _as_utc(tenant.updated_at).isoformat(),
        }
        if membership is not None:
            payload.update({"role": membership.role, "membership_status": membership.status})
        return payload

    @staticmethod
    def _tenant_slug(value: str) -> str:
        normalized = "-".join(value.strip().lower().split())
        normalized = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in normalized)
        return normalized.strip("-_")[:120]

    def get_membership(self, tenant_id: str, user_id: str) -> TenantMembershipRecord | None:
        with self.session_factory() as session:
            return session.get(TenantMembershipRecord, (tenant_id, user_id))

    def get_tenant(self, tenant_id: str) -> TenantRecord | None:
        with self.session_factory() as session:
            return session.get(TenantRecord, tenant_id)

    def get_or_create_personal_tenant(self, user_id: str) -> str:
        """Return a stable personal workspace for legacy/user-only calls."""

        tenant_id = str(uuid5(NAMESPACE_URL, f"eat-agent:personal:{user_id}"))
        slug = f"personal-{tenant_id.replace('-', '')[:16]}"
        with self._tenant_init_lock:
            try:
                with self.session_factory.begin() as session:
                    tenant = session.get(TenantRecord, tenant_id)
                    if tenant is None:
                        now = utc_now()
                        tenant = TenantRecord(
                            id=tenant_id,
                            name="个人空间",
                            slug=slug,
                            status="active",
                            owner_id=user_id,
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(tenant)
                    membership = session.get(TenantMembershipRecord, (tenant_id, user_id))
                    if membership is None:
                        session.add(
                            TenantMembershipRecord(
                                tenant_id=tenant_id,
                                user_id=user_id,
                                role="owner",
                                status="active",
                                created_at=utc_now(),
                                updated_at=utc_now(),
                            )
                        )
                    # Lazily scope rows from a pre-P2 local database to the
                    # deterministic personal tenant of their original user.
                    for table in (
                        "conversations",
                        "message_feedback",
                        "idempotency_records",
                        "user_memories",
                        "user_profile_events",
                        "memory_consents",
                        "user_profiles",
                    ):
                        session.execute(
                            text(f"UPDATE {table} SET tenant_id = :tenant_id WHERE user_id = :user_id AND tenant_id IS NULL"),
                            {"tenant_id": tenant_id, "user_id": user_id},
                        )
                    for table, column in (
                        ("knowledge_documents", "created_by"),
                        ("knowledge_builds", "initiated_by"),
                        ("knowledge_retrieval_events", "initiated_by"),
                    ):
                        session.execute(
                            text(f"UPDATE {table} SET tenant_id = :tenant_id WHERE {column} = :user_id AND tenant_id IS NULL"),
                            {"tenant_id": tenant_id, "user_id": user_id},
                        )
            except IntegrityError:
                # Another process can win the first insert; the deterministic
                # id/slug makes the retry safe and idempotent.
                with self.session_factory.begin() as session:
                    if session.get(TenantRecord, tenant_id) is None:
                        raise
                    if session.get(TenantMembershipRecord, (tenant_id, user_id)) is None:
                        session.add(
                            TenantMembershipRecord(
                                tenant_id=tenant_id,
                                user_id=user_id,
                                role="owner",
                                status="active",
                                created_at=utc_now(),
                                updated_at=utc_now(),
                            )
                        )
        return tenant_id

    def resolve_tenant_id(self, user_id: str, tenant_id: str | None = None) -> str:
        if tenant_id:
            return tenant_id
        return self.get_or_create_personal_tenant(user_id)

    def _scope_tenant(self, user_id: str, tenant_id: str | None) -> str:
        return self.resolve_tenant_id(user_id, tenant_id)

    def list_user_tenants(self, user_id: str) -> list[dict[str, Any]]:
        self.get_or_create_personal_tenant(user_id)
        with self.session_factory() as session:
            rows = session.execute(
                select(TenantRecord, TenantMembershipRecord)
                .join(TenantMembershipRecord, TenantMembershipRecord.tenant_id == TenantRecord.id)
                .where(
                    TenantMembershipRecord.user_id == user_id,
                    TenantMembershipRecord.status == "active",
                    TenantRecord.status == "active",
                )
                .order_by(TenantRecord.created_at.asc())
            ).all()
            return [self._tenant_payload(tenant, membership) for tenant, membership in rows]

    def create_tenant(self, *, tenant_id: str, name: str, slug: str, owner_id: str) -> dict[str, Any]:
        normalized_name = name.strip()[:128]
        normalized_slug = self._tenant_slug(slug or normalized_name)
        if not normalized_name or not normalized_slug:
            raise ValueError("租户名称和标识不能为空")
        with self.session_factory.begin() as session:
            if session.scalar(select(TenantRecord).where(TenantRecord.slug == normalized_slug)) is not None:
                raise ValueError("租户标识已存在")
            now = utc_now()
            tenant = TenantRecord(
                id=tenant_id,
                name=normalized_name,
                slug=normalized_slug,
                status="active",
                owner_id=owner_id,
                created_at=now,
                updated_at=now,
            )
            session.add(tenant)
            session.add(
                TenantMembershipRecord(
                    tenant_id=tenant_id,
                    user_id=owner_id,
                    role="owner",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                TenantSettingsRecord(
                    tenant_id=tenant_id,
                    grill_profile={},
                    knowledge_scope=["public"],
                    usage_limit={},
                    created_at=now,
                    updated_at=now,
                )
            )
            return self._tenant_payload(tenant, session.get(TenantMembershipRecord, (tenant_id, owner_id)))

    def update_tenant(self, tenant_id: str, *, name: str | None = None, slug: str | None = None) -> dict[str, Any]:
        with self.session_factory.begin() as session:
            tenant = session.get(TenantRecord, tenant_id)
            if tenant is None:
                raise KeyError("租户不存在")
            if name is not None and name.strip():
                tenant.name = name.strip()[:128]
            if slug is not None and slug.strip():
                normalized_slug = self._tenant_slug(slug)
                conflict = session.scalar(
                    select(TenantRecord).where(TenantRecord.slug == normalized_slug, TenantRecord.id != tenant_id)
                )
                if conflict is not None:
                    raise ValueError("租户标识已存在")
                tenant.slug = normalized_slug
            tenant.updated_at = utc_now()
            return self._tenant_payload(tenant)

    def archive_tenant(self, tenant_id: str) -> None:
        with self.session_factory.begin() as session:
            tenant = session.get(TenantRecord, tenant_id)
            if tenant is None:
                raise KeyError("租户不存在")
            tenant.status = "deleted"
            tenant.updated_at = utc_now()

    def add_or_update_member(self, tenant_id: str, *, user_id: str, role: str) -> dict[str, Any]:
        if role not in {"owner", "admin", "member"}:
            raise ValueError("租户角色不合法")
        with self.session_factory.begin() as session:
            if session.get(TenantRecord, tenant_id) is None:
                raise KeyError("租户不存在")
            now = utc_now()
            member = session.get(TenantMembershipRecord, (tenant_id, user_id))
            if member is None:
                member = TenantMembershipRecord(
                    tenant_id=tenant_id, user_id=user_id, role=role, status="active", created_at=now, updated_at=now
                )
                session.add(member)
            else:
                member.role = role
                member.status = "active"
                member.updated_at = now
            return {"tenant_id": tenant_id, "user_id": user_id, "role": member.role, "status": member.status}

    def remove_member(self, tenant_id: str, user_id: str) -> None:
        with self.session_factory.begin() as session:
            member = session.get(TenantMembershipRecord, (tenant_id, user_id))
            if member is None:
                raise KeyError("租户成员不存在")
            if member.role == "owner":
                owners = session.scalars(
                    select(TenantMembershipRecord).where(
                        TenantMembershipRecord.tenant_id == tenant_id,
                        TenantMembershipRecord.role == "owner",
                        TenantMembershipRecord.status == "active",
                    )
                ).all()
                if len(owners) <= 1:
                    raise ValueError("租户至少需要保留一名所有者")
            session.delete(member)

    def list_members(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(TenantMembershipRecord)
                .where(TenantMembershipRecord.tenant_id == tenant_id, TenantMembershipRecord.status == "active")
                .order_by(TenantMembershipRecord.created_at.asc())
            ).all()
            return [
                {"tenant_id": item.tenant_id, "user_id": item.user_id, "role": item.role, "status": item.status}
                for item in rows
            ]

    def get_tenant_settings(self, tenant_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            settings_record = session.get(TenantSettingsRecord, tenant_id)
            if settings_record is None:
                return {
                    "tenant_id": tenant_id,
                    "model_alias": None,
                    "grill_profile": {},
                    "knowledge_scope": ["public"],
                    "usage_limit": {},
                }
            return {
                "tenant_id": tenant_id,
                "model_alias": settings_record.model_alias,
                "grill_profile": dict(settings_record.grill_profile or {}),
                "knowledge_scope": list(settings_record.knowledge_scope or ["public"]),
                "usage_limit": dict(settings_record.usage_limit or {}),
            }

    def update_tenant_settings(self, tenant_id: str, values: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory.begin() as session:
            if session.get(TenantRecord, tenant_id) is None:
                raise KeyError("租户不存在")
            record = session.get(TenantSettingsRecord, tenant_id)
            now = utc_now()
            if record is None:
                record = TenantSettingsRecord(tenant_id=tenant_id, created_at=now, updated_at=now)
                session.add(record)
            for key in ("model_alias", "grill_profile", "knowledge_scope", "usage_limit"):
                if key in values and values[key] is not None:
                    setattr(record, key, values[key])
            record.updated_at = now
            session.flush()
            return {
                "tenant_id": tenant_id,
                "model_alias": record.model_alias,
                "grill_profile": dict(record.grill_profile or {}),
                "knowledge_scope": list(record.knowledge_scope or ["public"]),
                "usage_limit": dict(record.usage_limit or {}),
            }

    def create_user(self, *, user_id: str, username: str, password_hash: str) -> UserRecord:
        with self.session_factory.begin() as session:
            if session.scalar(select(UserRecord).where(UserRecord.username == username)) is not None:
                raise ValueError("用户名已存在")
            user = UserRecord(id=user_id, username=username, password_hash=password_hash, roles=[])
            session.add(user)
        self.get_or_create_personal_tenant(user_id)
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

    def get_memory_consent(self, user_id: str, tenant_id: str | None = None) -> bool:
        """Return explicit consent; absence is always treated as denied."""

        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory() as session:
            record = session.get(MemoryConsentRecord, (resolved_tenant_id, user_id))
            return bool(record and record.granted)

    def set_memory_consent(self, user_id: str, granted: bool, tenant_id: str | None = None) -> bool:
        """Set consent and erase durable memories when consent is withdrawn."""

        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory.begin() as session:
            record = session.get(MemoryConsentRecord, (resolved_tenant_id, user_id))
            if record is None:
                session.add(
                    MemoryConsentRecord(
                        tenant_id=resolved_tenant_id, user_id=user_id, granted=bool(granted), updated_at=utc_now()
                    )
                )
            else:
                record.granted = bool(granted)
                record.updated_at = utc_now()
            if not granted:
                session.execute(
                    delete(UserMemoryRecord).where(
                        UserMemoryRecord.tenant_id == resolved_tenant_id,
                        UserMemoryRecord.user_id == user_id,
                    )
                )
        return bool(granted)

    def save_memory(
        self,
        *,
        user_id: str,
        user_input: str,
        assistant_output: str,
        quality: float = 1.0,
        tenant_id: str | None = None,
    ) -> int | None:
        """Persist one record only after explicit user consent."""

        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory.begin() as session:
            consent = session.get(MemoryConsentRecord, (resolved_tenant_id, user_id))
            if consent is None or not consent.granted:
                return None
            record = UserMemoryRecord(
                tenant_id=resolved_tenant_id,
                user_id=user_id,
                user_input=user_input,
                assistant_output=assistant_output,
                quality=max(0.0, min(1.0, float(quality))),
                created_at=utc_now(),
            )
            session.add(record)
            session.flush()
            return record.id

    def list_memory(self, user_id: str, *, limit: int = 100, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """Export only records belonging to the requesting user."""

        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory() as session:
            records = session.scalars(
                select(UserMemoryRecord)
                .where(
                    UserMemoryRecord.tenant_id == resolved_tenant_id,
                    UserMemoryRecord.user_id == user_id,
                )
                .order_by(UserMemoryRecord.created_at.asc(), UserMemoryRecord.id.asc())
                .limit(max(1, min(limit, 1_000)))
            ).all()
            return [
                {
                    "id": record.id,
                    "input": record.user_input,
                    "output": record.assistant_output,
                    "quality": record.quality,
                    "created_at": _as_utc(record.created_at).isoformat(),
                }
                for record in records
            ]

    def export_memory(self, user_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        return {
            "tenant_id": resolved_tenant_id,
            "user_id": user_id,
            "consent": self.get_memory_consent(user_id, resolved_tenant_id),
            "items": self.list_memory(user_id, tenant_id=resolved_tenant_id),
        }

    def delete_memory(self, user_id: str, *, revoke_consent: bool = True, tenant_id: str | None = None) -> int:
        """Delete the user's durable memory and optionally revoke consent."""

        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory.begin() as session:
            result: Any = session.execute(
                delete(UserMemoryRecord).where(
                    UserMemoryRecord.tenant_id == resolved_tenant_id,
                    UserMemoryRecord.user_id == user_id,
                )
            )
            if revoke_consent:
                record = session.get(MemoryConsentRecord, (resolved_tenant_id, user_id))
                if record is None:
                    session.add(
                        MemoryConsentRecord(
                            tenant_id=resolved_tenant_id, user_id=user_id, granted=False, updated_at=utc_now()
                        )
                    )
                else:
                    record.granted = False
                    record.updated_at = utc_now()
            return int(result.rowcount or 0)

    @staticmethod
    def _profile_payload(record: UserProfileRecord) -> dict[str, Any]:
        profile_fields = (
            "height_cm",
            "weight_kg",
            "target_weight_kg",
            "age",
            "sex",
            "activity_level",
            "health_goal",
            "allergies",
            "dietary_preferences",
            "disliked_foods",
            "common_ingredients",
            "meals_per_day",
            "daily_budget",
        )
        list_fields = {"allergies", "dietary_preferences", "disliked_foods", "common_ingredients"}
        profile = {
            name: list(getattr(record, name) or []) if name in list_fields else getattr(record, name)
            for name in profile_fields
        }
        return {
            "tenant_id": record.tenant_id,
            "user_id": record.user_id,
            "profile": profile,
            "consent_granted": bool(record.consent_granted),
            "version": record.version,
            "created_at": _as_utc(record.created_at).isoformat(),
            "updated_at": _as_utc(record.updated_at).isoformat(),
        }

    def get_user_profile(self, user_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory() as session:
            record = session.get(UserProfileRecord, (resolved_tenant_id, user_id))
            return self._profile_payload(record) if record is not None else None

    def save_user_profile(
        self,
        *,
        user_id: str,
        profile: dict[str, Any],
        consent_granted: bool,
        actor: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        profile_fields = (
            "height_cm",
            "weight_kg",
            "target_weight_kg",
            "age",
            "sex",
            "activity_level",
            "health_goal",
            "allergies",
            "dietary_preferences",
            "disliked_foods",
            "common_ingredients",
            "meals_per_day",
            "daily_budget",
        )
        list_fields = {"allergies", "dietary_preferences", "disliked_foods", "common_ingredients"}
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory.begin() as session:
            record = session.get(UserProfileRecord, (resolved_tenant_id, user_id))
            is_new = record is None
            if record is None:
                record = UserProfileRecord(
                    tenant_id=resolved_tenant_id, user_id=user_id, consent_granted=bool(consent_granted)
                )
                session.add(record)
                changed_fields = [name for name in profile_fields if profile.get(name) not in (None, [], "")]
                if consent_granted:
                    for name in profile_fields:
                        value = profile.get(name)
                        setattr(record, name, list(value or []) if name in list_fields else value)
            else:
                changed_fields = []
                for name in profile_fields:
                    raw_value = profile.get(name)
                    value = list(raw_value or []) if name in list_fields else raw_value
                    if getattr(record, name) != value:
                        changed_fields.append(name)
                    setattr(record, name, value)
                if bool(record.consent_granted) != bool(consent_granted):
                    changed_fields.append("consent_granted")
                record.consent_granted = bool(consent_granted)
                record.version += 1 if changed_fields else 0
                record.updated_at = utc_now()
            if record is not None and not consent_granted:
                for name in profile_fields:
                    setattr(record, name, [] if name in list_fields else None)
            if changed_fields or is_new:
                session.add(
                    UserProfileEventRecord(
                        tenant_id=resolved_tenant_id,
                        user_id=user_id,
                        action="updated",
                        changed_fields=sorted(set(changed_fields)),
                        actor=actor or user_id,
                    )
                )
            session.flush()
            return self._profile_payload(record)

    def set_user_profile_consent(
        self, user_id: str, granted: bool, *, actor: str | None = None, tenant_id: str | None = None
    ) -> dict[str, Any]:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        current = self.get_user_profile(user_id, resolved_tenant_id)
        profile = dict((current or {}).get("profile") or {})
        if not granted:
            profile = {}
        return self.save_user_profile(
            user_id=user_id,
            profile=profile,
            consent_granted=bool(granted),
            actor=actor,
            tenant_id=resolved_tenant_id,
        )

    def delete_user_profile(
        self, user_id: str, *, actor: str | None = None, tenant_id: str | None = None
    ) -> dict[str, Any]:
        return self.set_user_profile_consent(user_id, False, actor=actor, tenant_id=tenant_id)

    def export_user_profile(self, user_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        current = self.get_user_profile(user_id, resolved_tenant_id)
        if current is not None:
            return current
        return {
            "tenant_id": resolved_tenant_id,
            "user_id": user_id,
            "profile": {},
            "consent_granted": False,
            "version": 0,
            "created_at": None,
            "updated_at": None,
        }

    @staticmethod
    def _profile_suggestion_payload(record: ProfileSuggestionRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "tenant_id": record.tenant_id,
            "user_id": record.user_id,
            "conversation_id": record.conversation_id,
            "source_message_id": record.source_message_id,
            "field": record.field_name,
            "value": record.value_json,
            "label": record.label,
            "confidence": record.confidence,
            "status": record.status,
            "expires_at": _as_utc(record.expires_at).isoformat(),
            "created_at": _as_utc(record.created_at).isoformat(),
            "updated_at": _as_utc(record.updated_at).isoformat(),
            "message": "是否保存到你的个人档案？",
        }

    def create_profile_suggestion(
        self,
        *,
        user_id: str,
        field_name: str,
        value: Any,
        label: str,
        confidence: float,
        conversation_id: str | None = None,
        source_message_id: int | None = None,
        tenant_id: str | None = None,
        expires_days: int = 7,
    ) -> dict[str, Any]:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        expires_at = utc_now() + timedelta(days=max(1, expires_days))
        with self.session_factory.begin() as session:
            existing = session.scalar(
                select(ProfileSuggestionRecord)
                .where(
                    ProfileSuggestionRecord.tenant_id == resolved_tenant_id,
                    ProfileSuggestionRecord.user_id == user_id,
                    ProfileSuggestionRecord.field_name == field_name,
                    ProfileSuggestionRecord.status == "pending",
                    ProfileSuggestionRecord.expires_at > utc_now(),
                )
                .order_by(ProfileSuggestionRecord.created_at.desc())
            )
            if existing is not None:
                return self._profile_suggestion_payload(existing)
            record = ProfileSuggestionRecord(
                id=str(uuid4()),
                tenant_id=resolved_tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                field_name=field_name,
                value_json=value,
                label=label[:256],
                confidence=max(0.0, min(1.0, float(confidence))),
                status="pending",
                expires_at=expires_at,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(record)
            session.flush()
            return self._profile_suggestion_payload(record)

    def list_profile_suggestions(
        self, user_id: str, *, status: str = "pending", tenant_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        now = utc_now()
        with self.session_factory.begin() as session:
            expired = session.scalars(
                select(ProfileSuggestionRecord).where(
                    ProfileSuggestionRecord.tenant_id == resolved_tenant_id,
                    ProfileSuggestionRecord.user_id == user_id,
                    ProfileSuggestionRecord.status == "pending",
                    ProfileSuggestionRecord.expires_at <= now,
                )
            ).all()
            for record in expired:
                record.status = "expired"
                record.updated_at = now
            rows = session.scalars(
                select(ProfileSuggestionRecord)
                .where(
                    ProfileSuggestionRecord.tenant_id == resolved_tenant_id,
                    ProfileSuggestionRecord.user_id == user_id,
                    ProfileSuggestionRecord.status == status,
                )
                .order_by(ProfileSuggestionRecord.created_at.desc())
                .limit(max(1, min(limit, 100)))
            ).all()
            return [self._profile_suggestion_payload(item) for item in rows]

    def get_profile_suggestion(
        self, suggestion_id: str, user_id: str, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory() as session:
            record = session.scalar(
                select(ProfileSuggestionRecord).where(
                    ProfileSuggestionRecord.id == suggestion_id,
                    ProfileSuggestionRecord.tenant_id == resolved_tenant_id,
                    ProfileSuggestionRecord.user_id == user_id,
                )
            )
            if record is None:
                return None
            return self._profile_suggestion_payload(record)

    def update_profile_suggestion_status(
        self, suggestion_id: str, user_id: str, status: str, tenant_id: str | None = None
    ) -> dict[str, Any]:
        if status not in {"accepted", "dismissed", "expired"}:
            raise ValueError("档案建议状态不合法")
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory.begin() as session:
            record = session.scalar(
                select(ProfileSuggestionRecord).where(
                    ProfileSuggestionRecord.id == suggestion_id,
                    ProfileSuggestionRecord.tenant_id == resolved_tenant_id,
                    ProfileSuggestionRecord.user_id == user_id,
                )
            )
            if record is None:
                raise KeyError("档案建议不存在")
            if record.status != "pending":
                raise ValueError("档案建议已经处理")
            if _as_utc(record.expires_at) <= utc_now():
                record.status = "expired"
                record.updated_at = utc_now()
                raise ValueError("档案建议已过期")
            record.status = status
            record.updated_at = utc_now()
            return self._profile_suggestion_payload(record)

    @staticmethod
    def _experience_settings_payload(record: UserExperienceSettingsRecord) -> dict[str, Any]:
        return {
            "tenant_id": record.tenant_id,
            "user_id": record.user_id,
            "show_model_info": bool(record.show_model_info),
            "show_sources": bool(record.show_sources),
            "show_safety_details": bool(record.show_safety_details),
            "answer_style": record.answer_style,
            "pinned_shortcuts": list(record.pinned_shortcuts or []),
            "updated_at": _as_utc(record.updated_at).isoformat(),
        }

    def get_experience_settings(self, user_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory.begin() as session:
            record = session.get(UserExperienceSettingsRecord, (resolved_tenant_id, user_id))
            if record is None:
                record = UserExperienceSettingsRecord(
                    tenant_id=resolved_tenant_id,
                    user_id=user_id,
                    show_model_info=True,
                    show_sources=True,
                    show_safety_details=True,
                    answer_style="standard",
                    pinned_shortcuts=[],
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
                session.add(record)
                session.flush()
            return self._experience_settings_payload(record)

    def update_experience_settings(
        self, user_id: str, values: dict[str, Any], tenant_id: str | None = None
    ) -> dict[str, Any]:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        allowed = {"show_model_info", "show_sources", "show_safety_details", "answer_style", "pinned_shortcuts"}
        with self.session_factory.begin() as session:
            record = session.get(UserExperienceSettingsRecord, (resolved_tenant_id, user_id))
            if record is None:
                record = UserExperienceSettingsRecord(
                    tenant_id=resolved_tenant_id,
                    user_id=user_id,
                    show_model_info=True,
                    show_sources=True,
                    show_safety_details=True,
                    answer_style="standard",
                    pinned_shortcuts=[],
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
                session.add(record)
            for key in allowed:
                if key not in values or values[key] is None:
                    continue
                setattr(record, key, values[key])
            record.updated_at = utc_now()
            session.flush()
            return self._experience_settings_payload(record)

    def list_conversations(
        self,
        user_id: str,
        tenant_id: str | None = None,
        *,
        query_text: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
    ) -> list[ConversationRecord]:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory() as session:
            filters = [
                ConversationRecord.tenant_id == resolved_tenant_id,
                ConversationRecord.user_id == user_id,
                ConversationRecord.expires_at > utc_now(),
            ]
            if not include_archived:
                filters.append(ConversationRecord.archived_at.is_(None))
            normalized_query = (query_text or "").strip()
            if normalized_query:
                pattern = f"%{normalized_query}%"
                message_match = select(MessageRecord.conversation_id).where(MessageRecord.content.ilike(pattern))
                filters.append(
                    or_(
                        ConversationRecord.title.ilike(pattern),
                        ConversationRecord.id.ilike(pattern),
                        ConversationRecord.id.in_(message_match),
                    )
                )
            return list(
                session.scalars(
                    select(ConversationRecord)
                    .where(*filters)
                    .order_by(ConversationRecord.updated_at.desc())
                    .limit(max(1, min(limit, 100)))
                ).all()
            )

    def rename_conversation(
        self, conversation_id: str, user_id: str, title: str, tenant_id: str | None = None
    ) -> ConversationRecord:
        normalized_title = title.strip()[:200]
        if not normalized_title:
            raise ValueError("会话标题不能为空")
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory.begin() as session:
            conversation = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.tenant_id == resolved_tenant_id,
                    ConversationRecord.user_id == user_id,
                )
            )
            if conversation is None:
                if session.get(ConversationRecord, conversation_id) is not None:
                    raise ConversationAccessError("无权访问该会话")
                raise KeyError("会话不存在")
            conversation.title = normalized_title
            conversation.updated_at = utc_now()
            return conversation

    def create_conversation(
        self, *, conversation_id: str, user_id: str, title: str = "新会话", tenant_id: str | None = None
    ) -> ConversationRecord:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory.begin() as session:
            conversation = ConversationRecord(
                id=conversation_id,
                tenant_id=resolved_tenant_id,
                user_id=user_id,
                title=title[:200] or "新会话",
                grill_context={},
                expires_at=conversation_expiry(),
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(conversation)
            return conversation

    def archive_conversation(self, conversation_id: str, user_id: str, tenant_id: str | None = None) -> None:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory.begin() as session:
            conversation = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.tenant_id == resolved_tenant_id,
                    ConversationRecord.user_id == user_id,
                )
            )
            if conversation is None:
                if session.get(ConversationRecord, conversation_id) is not None:
                    raise ConversationAccessError("无权访问该会话")
                raise KeyError("会话不存在")
            conversation.archived_at = utc_now()

    def delete_conversation(self, conversation_id: str, user_id: str, tenant_id: str | None = None) -> None:
        """Permanently delete one user-owned conversation and its dependent data."""
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory.begin() as session:
            conversation = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.tenant_id == resolved_tenant_id,
                    ConversationRecord.user_id == user_id,
                )
            )
            if conversation is None:
                if session.get(ConversationRecord, conversation_id) is not None:
                    raise ConversationAccessError("无权访问该会话")
                raise KeyError("会话不存在")
            session.execute(
                delete(MessageFeedbackRecord).where(MessageFeedbackRecord.conversation_id == conversation_id)
            )
            session.execute(delete(MessageRecord).where(MessageRecord.conversation_id == conversation_id))
            session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.conversation_id == conversation_id))
            session.delete(conversation)

    def get_idempotent_response(
        self, conversation_id: str, user_id: str, request_id: str, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory() as session:
            record = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.conversation_id == conversation_id,
                    IdempotencyRecord.tenant_id == resolved_tenant_id,
                    IdempotencyRecord.user_id == user_id,
                    IdempotencyRecord.request_id == request_id,
                )
            )
            return dict(record.response_json) if record is not None else None

    def load(
        self, conversation_id: str, user_id: str, *, include_metadata: bool = False, tenant_id: str | None = None
    ) -> ConversationSnapshot:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory() as session:
            conversation = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.tenant_id == resolved_tenant_id,
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
                    tenant_id=resolved_tenant_id,
                    user_id=user_id,
                    title="新会话",
                    grill_context={},
                    expires_at=conversation_expiry(),
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
                session.add(conversation)
                session.commit()
                return ConversationSnapshot(conversation_id, user_id, [], {}, None, tenant_id=resolved_tenant_id)

            messages = session.scalars(
                select(MessageRecord).where(MessageRecord.conversation_id == conversation_id).order_by(MessageRecord.id)
            ).all()
            message_payloads: list[dict[str, Any]] = []
            for item in messages:
                payload: dict[str, Any] = {"role": item.role, "content": item.content}
                if include_metadata:
                    payload.update(
                        {
                            "id": item.id,
                            "request_id": item.request_id,
                            "response_type": item.response_type,
                            "target_field": item.target_field,
                        }
                    )
                message_payloads.append(payload)
            return ConversationSnapshot(
                conversation_id=conversation_id,
                user_id=user_id,
                messages=message_payloads,
                grill_context=dict(conversation.grill_context or {}),
                current_goal=conversation.current_goal,
                tenant_id=resolved_tenant_id,
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
        persist_user_message: bool = True,
        tenant_id: str | None = None,
    ) -> int:
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        now = utc_now()
        assistant_message_id: int | None = None
        with self.session_factory.begin() as session:
            conversation = session.scalar(
                select(ConversationRecord)
                .where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.tenant_id == resolved_tenant_id,
                    ConversationRecord.user_id == user_id,
                    ConversationRecord.archived_at.is_(None),
                    ConversationRecord.expires_at > utc_now(),
                )
                .with_for_update()
            )
            if conversation is None:
                existing = session.get(ConversationRecord, conversation_id)
                if existing is not None:
                    if _is_expired(existing.expires_at):
                        raise KeyError("会话已过期")
                    raise ConversationAccessError("无权访问该会话")
                conversation = ConversationRecord(
                    id=conversation_id,
                    tenant_id=resolved_tenant_id,
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

            if persist_user_message:
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
                assistant = MessageRecord(
                    conversation_id=conversation_id,
                    request_id=request_id,
                    role="assistant",
                    content=assistant_message,
                    response_type=response_type,
                    target_field=target_field,
                    created_at=now,
                )
                session.add(assistant)
                session.flush()
                assistant_message_id = assistant.id
            else:
                assistant_message_id = existing_assistant.id

            if response_payload is not None:
                existing_idempotency = session.scalar(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.conversation_id == conversation_id,
                        IdempotencyRecord.tenant_id == resolved_tenant_id,
                        IdempotencyRecord.request_id == request_id,
                    )
                )
                if existing_idempotency is None:
                    session.add(
                        IdempotencyRecord(
                            conversation_id=conversation_id,
                            tenant_id=resolved_tenant_id,
                            user_id=user_id,
                            request_id=request_id,
                            response_json=dict(response_payload),
                            created_at=now,
                        )
                    )
        if assistant_message_id is None:
            raise RuntimeError("assistant message was not persisted")
        return assistant_message_id

    def update_idempotent_response(
        self,
        *,
        conversation_id: str,
        request_id: str,
        response_payload: dict[str, Any],
        tenant_id: str | None = None,
    ) -> None:
        resolved_tenant_id = tenant_id
        with self.session_factory.begin() as session:
            record = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.conversation_id == conversation_id,
                    IdempotencyRecord.tenant_id == resolved_tenant_id,
                    IdempotencyRecord.request_id == request_id,
                )
            )
            if record is not None:
                record.response_json = dict(response_payload)

    def latest_user_message(
        self, conversation_id: str, user_id: str, tenant_id: str | None = None
    ) -> dict[str, Any]:
        """Return the latest user turn after enforcing conversation ownership."""

        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory() as session:
            conversation = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.tenant_id == resolved_tenant_id,
                    ConversationRecord.user_id == user_id,
                    ConversationRecord.expires_at > utc_now(),
                )
            )
            if conversation is None:
                existing = session.get(ConversationRecord, conversation_id)
                if existing is not None:
                    raise ConversationAccessError("无权访问该会话")
                raise KeyError("会话不存在")
            message = session.scalar(
                select(MessageRecord)
                .where(MessageRecord.conversation_id == conversation_id, MessageRecord.role == "user")
                .order_by(MessageRecord.id.desc())
            )
            if message is None:
                raise KeyError("没有可重新生成的用户消息")
            return {"id": message.id, "request_id": message.request_id, "content": message.content}

    def save_feedback(
        self,
        *,
        message_id: int,
        user_id: str,
        rating: str,
        comment: str | None = None,
        tenant_id: str | None = None,
    ) -> MessageFeedbackRecord:
        """Upsert feedback only for a message owned by the requesting user."""

        if rating not in {"up", "down"}:
            raise ValueError("反馈类型必须是 up 或 down")
        resolved_tenant_id = self._scope_tenant(user_id, tenant_id)
        with self.session_factory.begin() as session:
            message = session.scalar(
                select(MessageRecord)
                .join(ConversationRecord, ConversationRecord.id == MessageRecord.conversation_id)
                .where(
                    MessageRecord.id == message_id,
                    ConversationRecord.tenant_id == resolved_tenant_id,
                    ConversationRecord.user_id == user_id,
                    MessageRecord.role == "assistant",
                )
            )
            if message is None:
                raise KeyError("消息不存在")
            feedback = session.scalar(
                select(MessageFeedbackRecord).where(
                    MessageFeedbackRecord.message_id == message_id,
                    MessageFeedbackRecord.tenant_id == resolved_tenant_id,
                    MessageFeedbackRecord.user_id == user_id,
                )
            )
            if feedback is None:
                feedback = MessageFeedbackRecord(
                    message_id=message_id,
                    conversation_id=message.conversation_id,
                    tenant_id=resolved_tenant_id,
                    user_id=user_id,
                    rating=rating,
                    comment=comment,
                )
                session.add(feedback)
            else:
                feedback.rating = rating
                feedback.comment = comment
                feedback.updated_at = utc_now()
            session.flush()
            return feedback
