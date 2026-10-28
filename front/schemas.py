"""Typed request and response contracts for the small-platform API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    error: str
    error_code: str
    request_id: str | None = None


class CredentialsRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, max_length=512)


class UserResponse(BaseModel):
    id: str
    username: str
    roles: list[str] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"]
    expires_in: int
    user: UserResponse


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="新会话", max_length=200)


class ConversationSummary(BaseModel):
    id: str
    title: str
    updated_at: str
    version: int


class ConversationListResponse(BaseModel):
    items: list[ConversationSummary]


class ConversationMessage(BaseModel):
    id: int | None = None
    role: Literal["user", "assistant"]
    content: str
    request_id: str | None = None
    response_type: str | None = None
    target_field: str | None = None


class ConversationDetailResponse(BaseModel):
    id: str
    title: str
    version: int
    messages: list[ConversationMessage]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=20_000)
    conversation_id: str | None = Field(default=None, max_length=128)
    # 仅在开发/API-Key 兼容模式使用；JWT 模式由 Token 身份决定。
    user_id: str | None = Field(default=None, max_length=128)


class MemoryConsentRequest(BaseModel):
    granted: bool


class MessageFeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=2_000)


class AskResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    answer: str
    type: str
    target_field: str | None = None
    options: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    response_time: float = 0.0
    retrieval_count: int = 0
    conversation_id: str | None = None
    request_id: str | None = None
    grill: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
