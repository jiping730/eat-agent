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


class TenantCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    slug: str | None = Field(default=None, min_length=2, max_length=120)


class TenantUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    slug: str | None = Field(default=None, min_length=2, max_length=120)


class TenantMemberRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    role: Literal["owner", "admin", "member"] = "member"


class TenantRoleUpdateRequest(BaseModel):
    role: Literal["owner", "admin", "member"]


class TenantSettingsUpdateRequest(BaseModel):
    model_alias: str | None = Field(default=None, max_length=128)
    grill_profile: dict[str, Any] | None = None
    knowledge_scope: list[str] | None = Field(default=None, max_length=20)
    usage_limit: dict[str, Any] | None = None


class TenantListResponse(BaseModel):
    items: list[dict[str, Any]]


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"]
    expires_in: int
    user: UserResponse


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="新会话", max_length=200)


class ConversationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)


class ConversationSummary(BaseModel):
    id: str
    title: str
    updated_at: str
    version: int
    archived_at: str | None = None


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


class NutritionEstimateRequest(BaseModel):
    """Input for estimating nutrition after a user saves a meal record."""

    food_name: str = Field(min_length=1, max_length=2_000)
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    note: str = Field(default="", max_length=2_000)


class NutritionEstimateResponse(BaseModel):
    """A deliberately approximate, structured nutrition estimate."""

    calories: int | None = Field(default=None, ge=0, le=10_000)
    protein_g: float | None = Field(default=None, ge=0, le=1_000)
    carbs_g: float | None = Field(default=None, ge=0, le=1_000)
    fat_g: float | None = Field(default=None, ge=0, le=1_000)
    confidence: Literal["low", "medium", "high", "unavailable"] = "unavailable"
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    source: Literal["ai", "unavailable"] = "unavailable"
    status: Literal["estimated", "unavailable"] = "unavailable"
    message: str = ""


class MemoryConsentRequest(BaseModel):
    granted: bool


class UserProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    height_cm: float | None = Field(default=None, ge=80, le=250)
    weight_kg: float | None = Field(default=None, ge=20, le=500)
    target_weight_kg: float | None = Field(default=None, ge=20, le=500)
    age: int | None = Field(default=None, ge=13, le=120)
    sex: Literal["female", "male", "other", "prefer_not_to_say"] | None = None
    activity_level: Literal["sedentary", "light", "moderate", "high"] | None = None
    health_goal: Literal["weight_control", "muscle_gain", "balanced_diet", "maintain"] | None = None
    allergies: list[str] = Field(default_factory=list, max_length=20)
    dietary_preferences: list[str] = Field(default_factory=list, max_length=20)
    disliked_foods: list[str] = Field(default_factory=list, max_length=50)
    common_ingredients: list[str] = Field(default_factory=list, max_length=50)
    meals_per_day: int | None = Field(default=None, ge=1, le=8)
    daily_budget: float | None = Field(default=None, ge=0, le=100_000)
    consent_granted: bool | None = None


class ProfileConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    granted: bool


class UserProfileResponse(BaseModel):
    tenant_id: str | None = None
    user_id: str
    profile: dict[str, Any]
    consent_granted: bool
    version: int
    created_at: str | None = None
    updated_at: str | None = None


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
    grill_progress: dict[str, Any] = Field(default_factory=dict)
    profile_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    model_info: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    mode: Literal["model", "offline", "unknown"] = "unknown"
    reason: str = ""
    confidence: str = ""
    next_step: str = ""


class ProfileSuggestionListResponse(BaseModel):
    items: list[dict[str, Any]]


class ExperienceSettingsResponse(BaseModel):
    tenant_id: str
    user_id: str
    show_model_info: bool
    show_sources: bool
    show_safety_details: bool
    answer_style: Literal["concise", "standard", "detailed"]
    pinned_shortcuts: list[str] = Field(default_factory=list)
    updated_at: str


class ExperienceSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    show_model_info: bool | None = None
    show_sources: bool | None = None
    show_safety_details: bool | None = None
    answer_style: Literal["concise", "standard", "detailed"] | None = None
    pinned_shortcuts: list[str] | None = Field(default=None, max_length=12)


class KnowledgeDocumentUploadRequest(BaseModel):
    source_name: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=200)
    access_groups: list[str] = Field(default_factory=lambda: ["public"], max_length=20)


class KnowledgeReviewRequest(BaseModel):
    approved: bool
    note: str | None = Field(default=None, max_length=2_000)


class KnowledgeDocumentListResponse(BaseModel):
    items: list[dict[str, Any]]


class KnowledgeBuildRequest(BaseModel):
    confirm: bool = True


class KnowledgeRollbackRequest(BaseModel):
    target: str = Field(min_length=1, max_length=128)


class KnowledgeRetrievalTestRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    top_k: int = Field(default=4, ge=1, le=10)
    access_groups: list[str] = Field(default_factory=lambda: ["public"], max_length=20)


class PersonalKnowledgeTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=1_000_000)
    title: str | None = Field(default=None, max_length=200)


class PersonalKnowledgeRetrievalTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2_000)
    top_k: int = Field(default=4, ge=1, le=10)
