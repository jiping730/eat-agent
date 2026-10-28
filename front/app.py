"""FastAPI application for the small-platform API and browser UI."""

from __future__ import annotations

import hmac
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from core.auth import AuthenticationError, AuthPrincipal, AuthService, hash_refresh_token
from core.conversation_runtime import ConversationRuntime
from core.knowledge_base import KnowledgeBaseService
from core.logging_config import configure_logging, fingerprint, log_event
from core.observability import (
    bind_observation_context,
    configure_optional_observability,
    new_trace_id,
    record_http_request,
    record_rate_limit_rejection,
    reset_observation_context,
    set_app_info,
)
from core.profile import ProfileService, UserProfileUpdate
from core.persistence import ConversationAccessError
from core.experience import ConversationActionRequest, ExperienceSettings, list_shortcuts
from core.rate_limiter import SlidingWindowRateLimiter
from core.tenant import TenantContext, TenantService
from front.schemas import (
    AskRequest,
    AskResponse,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationUpdateRequest,
    CredentialsRequest,
    ErrorResponse,
    ExperienceSettingsResponse,
    ExperienceSettingsUpdateRequest,
    LogoutRequest,
    MemoryConsentRequest,
    MessageFeedbackRequest,
    KnowledgeBuildRequest,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentUploadRequest,
    KnowledgeRetrievalTestRequest,
    KnowledgeReviewRequest,
    KnowledgeRollbackRequest,
    ProfileConsentRequest,
    ProfileSuggestionListResponse,
    RefreshRequest,
    TokenResponse,
    UserProfileResponse,
    UserProfileUpdateRequest,
    UserResponse,
    TenantCreateRequest,
    TenantListResponse,
    TenantMemberRequest,
    TenantRoleUpdateRequest,
    TenantSettingsUpdateRequest,
    TenantUpdateRequest,
)

ROOT_DIR = Path(__file__).resolve().parent
app = FastAPI(title="轻松食 · 智能营养助手", version=settings.app_version)
app.mount("/static", StaticFiles(directory=ROOT_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))

origins = settings.cors_origin_list()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if isinstance(origins, list) else ["*"],
    allow_credentials=isinstance(origins, list),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

logger = configure_logging(settings.log_level)
startup_errors = settings.startup_errors()
if startup_errors:
    raise RuntimeError("生产安全配置无效: " + "; ".join(startup_errors))
configure_optional_observability()
runtime = ConversationRuntime()
knowledge_service = KnowledgeBaseService(runtime.store)
profile_service = ProfileService(runtime.store)
tenant_service = TenantService(runtime.store)
auth_service = AuthService()
rate_limiter = SlidingWindowRateLimiter(settings.rate_limit_per_minute, redis_url=settings.redis_url)
set_app_info(settings.app_version, settings.app_env)

PUBLIC_PATHS = {
    "/",
    "/health/live",
    "/health/ready",
    "/healthz",
    "/readyz",
    "/auth/register",
    "/auth/login",
    "/auth/refresh",
    "/auth/logout",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/admin/knowledge",
    "/profile",
}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "")


def _error_response(
    request: Request, message: str, status_code: int, error_code: str = "request_error"
) -> JSONResponse:
    payload = ErrorResponse(error=message, error_code=error_code, request_id=_request_id(request))
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def _platform_user_id(request: Request, data: dict | None = None) -> str:
    principal: AuthPrincipal | None = getattr(request.state, "principal", None)
    if principal and principal.auth_type == "jwt":
        requested_user_id = (data or {}).get("user_id")
        if requested_user_id is not None and requested_user_id != principal.user_id:
            raise PermissionError("不能使用其他用户身份")
        return principal.user_id

    requested_user_id = (data or {}).get("user_id") or request.headers.get("X-User-ID")
    if not isinstance(requested_user_id, str) or not requested_user_id.strip():
        raise ValueError("缺少用户身份")
    return requested_user_id.strip()


def _tenant_context(request: Request, user_id: str | None = None) -> TenantContext:
    resolved_user_id = user_id or _platform_user_id(request)
    requested_tenant_id = request.headers.get("X-Tenant-ID", "").strip() or None
    return tenant_service.resolve(resolved_user_id, requested_tenant_id)


def _legacy_knowledge_admin(request: Request) -> str:
    """Return the verified actor for knowledge administration endpoints."""

    principal: AuthPrincipal | None = getattr(request.state, "principal", None)
    configured_ids = {
        value.strip() for value in settings.knowledge_admin_user_ids.split(",") if value.strip()
    }
    if principal is not None:
        if principal.user_id in configured_ids or set(principal.roles).intersection(
            {"admin", "knowledge_admin", "service"}
        ):
            return principal.user_id
        raise PermissionError("当前用户没有知识库管理权限")
    header_user_id = request.headers.get("X-User-ID", "").strip()
    if header_user_id and header_user_id in configured_ids:
        return header_user_id
    raise PermissionError("需要知识库管理员身份")


def _knowledge_admin(request: Request) -> str:
    """Require an active tenant admin for knowledge-base administration."""

    user_id = _platform_user_id(request)
    context = _tenant_context(request, user_id)
    configured_ids = {
        value.strip() for value in settings.knowledge_admin_user_ids.split(",") if value.strip()
    }
    principal: AuthPrincipal | None = getattr(request.state, "principal", None)
    if context.is_admin or user_id in configured_ids:
        return user_id
    if principal is not None and set(principal.roles).intersection({"admin", "knowledge_admin", "service"}):
        return user_id
    raise PermissionError("需要租户管理员权限")


def _token_response(user, token_pair) -> dict:
    return {
        **token_pair.to_dict(),
        "user": {"id": user.id, "username": user.username, "roles": user.roles or []},
    }


def _stable_path(path: str) -> str:
    if path.startswith("/conversations/"):
        return "/conversations/:id"
    if path.startswith("/static/"):
        return "/static/:asset"
    if path.startswith("/messages/"):
        return "/messages/:id"
    return path


def _metrics_auth_error(request: Request) -> JSONResponse | None:
    if not settings.metrics_enabled:
        return _error_response(request, "metrics 未启用", 404, "metrics_disabled")
    expected = settings.metrics_api_key
    provided = request.headers.get("X-Metrics-Token", "")
    if not provided:
        authorization = request.headers.get("Authorization", "")
        if authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
    if settings.strict_security and not expected:
        return _error_response(request, "metrics 未配置访问密钥", 503, "metrics_misconfigured")
    if expected and not hmac.compare_digest(provided, expected):
        return _error_response(request, "metrics 未授权", 401, "metrics_unauthorized")
    return None


async def _call_with_rate_limit(request: Request, call_next):
    if request.url.path in {"/ask", "/ask/stream"}:
        client_key = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
        client_key = client_key.split(",")[0].strip()
        if not rate_limiter.allow(client_key):
            record_rate_limit_rejection()
            return _error_response(request, "请求过于频繁，请稍后再试", 429, "rate_limited")
    return await call_next(request)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.trace_id = request.headers.get("X-Trace-ID") or new_trace_id()
    request.state.request_started_at = time.perf_counter()
    request.state.principal = None
    context_token = bind_observation_context(
        request_id=request.state.request_id,
        trace_id=request.state.trace_id,
    )
    try:
        if request.url.path == "/metrics":
            early_response = _metrics_auth_error(request)
            response = early_response if early_response is not None else await call_next(request)
        elif request.url.path not in PUBLIC_PATHS and not request.url.path.startswith("/static/"):
            try:
                request.state.principal = auth_service.authenticate(
                    request.headers.get("Authorization"),
                    request.headers.get("X-API-Key"),
                )
            except AuthenticationError as exc:
                response = _error_response(request, str(exc), 401, "authentication_required")
            else:
                response = await _call_with_rate_limit(request, call_next)
        else:
            response = await call_next(request)

        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Trace-ID"] = request.state.trace_id
        elapsed = time.perf_counter() - request.state.request_started_at
        stable_path = _stable_path(request.url.path)
        record_http_request(request.method, stable_path, response.status_code, elapsed)
        log_event(
            logger,
            20,
            "request_completed",
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
            method=request.method,
            path=stable_path,
            status_code=response.status_code,
            response_time=round(elapsed, 4),
        )
        return response
    finally:
        reset_observation_context(context_token)


@app.exception_handler(ConversationAccessError)
async def handle_conversation_access_error(request: Request, error: ConversationAccessError):
    return _error_response(request, str(error), 403, "conversation_forbidden")


@app.exception_handler(PermissionError)
async def handle_permission_error(request: Request, error: PermissionError):
    return _error_response(request, str(error), 403, "permission_denied")


@app.exception_handler(KeyError)
async def handle_key_error(request: Request, error: KeyError):
    return _error_response(request, str(error).strip("'"), 404, "not_found")


@app.exception_handler(ValueError)
async def handle_value_error(request: Request, error: ValueError):
    return _error_response(request, str(error), 400, "invalid_request")


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, error: RequestValidationError):
    return _error_response(request, "请求参数校验失败", 422, "validation_error")


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(request: Request, error: StarletteHTTPException):
    return _error_response(request, str(error.detail), error.status_code, "http_error")


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, error: Exception):
    log_event(logger, 40, "request_failed", request_id=_request_id(request), error_type=type(error).__name__)
    return _error_response(request, "服务暂时不可用，请稍后再试", 500, "internal_error")


@app.get("/", include_in_schema=False)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})


@app.get("/admin/knowledge", include_in_schema=False)
def knowledge_admin_page(request: Request):
    return templates.TemplateResponse(request=request, name="knowledge.html", context={})


@app.get("/profile", include_in_schema=False)
def profile_page(request: Request):
    return templates.TemplateResponse(request=request, name="profile.html", context={})


@app.get("/health/live", include_in_schema=False)
@app.get("/healthz", include_in_schema=False)
def health_live():
    return {"status": "ok", "version": settings.app_version}


@app.get("/health/ready", include_in_schema=False)
@app.get("/readyz", include_in_schema=False)
def health_ready(request: Request):
    try:
        runtime.store.ping()
        runtime.coordinator.ping()
    except Exception as exc:
        log_event(logger, 40, "readiness_failed", request_id=_request_id(request), error_type=type(exc).__name__)
        if settings.redis_url:
            return JSONResponse(status_code=503, content={"status": "not_ready", "request_id": _request_id(request)})
    return {"status": "ready", "version": settings.app_version}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/auth/register", response_model=TokenResponse, status_code=201)
def register(data: CredentialsRequest, request: Request):
    username = data.username.strip()
    if not 3 <= len(username) <= 128:
        raise ValueError("用户名长度必须在 3 到 128 个字符之间")
    if not auth_service.jwt_enabled:
        return _error_response(request, "当前服务未启用用户认证", 503, "authentication_disabled")
    user_id = str(uuid.uuid4())
    try:
        user = runtime.store.create_user(
            user_id=user_id,
            username=username,
            password_hash=auth_service.hash_password(data.password),
        )
    except ValueError as exc:
        return _error_response(request, str(exc), 409, "username_conflict")
    tokens = auth_service.issue_tokens(user.id, tuple(user.roles or []))
    log_event(logger, 20, "auth_register_succeeded", user=fingerprint(user.id))
    runtime.store.save_refresh_token(
        user_id=user.id,
        token_hash=hash_refresh_token(tokens.refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days),
    )
    return _token_response(user, tokens)


@app.post("/auth/login", response_model=TokenResponse)
def login(data: CredentialsRequest, request: Request):
    if not auth_service.jwt_enabled:
        return _error_response(request, "当前服务未启用用户认证", 503, "authentication_disabled")
    user = runtime.store.get_user_by_username(data.username.strip())
    if user is None or not user.is_active or not auth_service.verify_password(user.password_hash, data.password):
        log_event(logger, 30, "auth_login_failed")
        return _error_response(request, "用户名或密码错误", 401, "invalid_credentials")
    runtime.store.get_or_create_personal_tenant(user.id)
    tokens = auth_service.issue_tokens(user.id, tuple(user.roles or []))
    log_event(logger, 20, "auth_login_succeeded", user=fingerprint(user.id))
    runtime.store.save_refresh_token(
        user_id=user.id,
        token_hash=hash_refresh_token(tokens.refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days),
    )
    return _token_response(user, tokens)


@app.post("/auth/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, request: Request):
    token_record = runtime.store.get_refresh_token(hash_refresh_token(data.refresh_token))
    if token_record is None:
        return _error_response(request, "刷新令牌无效或已过期", 401, "invalid_refresh_token")
    user = runtime.store.get_user(token_record.user_id)
    if user is None or not user.is_active:
        return _error_response(request, "用户不可用", 401, "user_unavailable")
    runtime.store.get_or_create_personal_tenant(user.id)
    runtime.store.revoke_refresh_token(hash_refresh_token(data.refresh_token))
    tokens = auth_service.issue_tokens(user.id, tuple(user.roles or []))
    log_event(logger, 20, "auth_refresh_succeeded", user=fingerprint(user.id))
    runtime.store.save_refresh_token(
        user_id=user.id,
        token_hash=hash_refresh_token(tokens.refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days),
    )
    return _token_response(user, tokens)


@app.post("/auth/logout")
def logout(data: LogoutRequest | None = None):
    if data and data.refresh_token:
        runtime.store.revoke_refresh_token(hash_refresh_token(data.refresh_token))
    return {"status": "ok"}


@app.get("/me", response_model=UserResponse)
def me(request: Request):
    user_id = _platform_user_id(request)
    user = runtime.store.get_user(user_id)
    if user is None:
        return _error_response(request, "用户不存在", 404, "user_not_found")
    return {"id": user.id, "username": user.username, "roles": user.roles or []}


@app.get("/me/tenants", response_model=TenantListResponse)
def list_my_tenants(request: Request):
    return {"items": tenant_service.list_for_user(_platform_user_id(request))}


@app.post("/tenants", status_code=201)
def create_tenant(data: TenantCreateRequest, request: Request):
    return tenant_service.create(_platform_user_id(request), data.name, data.slug)


@app.get("/tenants/{tenant_id}")
def get_tenant(tenant_id: str, request: Request):
    context = tenant_service.require_member(_platform_user_id(request), tenant_id)
    tenant = runtime.store.get_tenant(tenant_id)
    if tenant is None:
        raise KeyError("租户不存在")
    payload = runtime.store._tenant_payload(tenant)
    payload["role"] = context.role
    payload["members"] = runtime.store.list_members(tenant_id)
    return payload


@app.put("/tenants/{tenant_id}")
def update_tenant(tenant_id: str, data: TenantUpdateRequest, request: Request):
    tenant_service.require_role(_platform_user_id(request), tenant_id, {"owner", "admin"})
    return runtime.store.update_tenant(tenant_id, name=data.name, slug=data.slug)


@app.delete("/tenants/{tenant_id}")
def delete_tenant(tenant_id: str, request: Request):
    tenant_service.require_role(_platform_user_id(request), tenant_id, {"owner"})
    runtime.store.archive_tenant(tenant_id)
    return {"status": "deleted"}


@app.post("/tenants/{tenant_id}/members")
def add_tenant_member(tenant_id: str, data: TenantMemberRequest, request: Request):
    context = tenant_service.require_role(_platform_user_id(request), tenant_id, {"owner", "admin"})
    if data.role == "owner" and context.role != "owner":
        raise PermissionError("只有租户所有者可以授予 owner 角色")
    return runtime.store.add_or_update_member(tenant_id, user_id=data.user_id, role=data.role)


@app.put("/tenants/{tenant_id}/members/{user_id}")
def update_tenant_member(tenant_id: str, user_id: str, data: TenantRoleUpdateRequest, request: Request):
    context = tenant_service.require_role(_platform_user_id(request), tenant_id, {"owner", "admin"})
    if data.role == "owner" and context.role != "owner":
        raise PermissionError("只有租户所有者可以授予 owner 角色")
    return runtime.store.add_or_update_member(tenant_id, user_id=user_id, role=data.role)


@app.delete("/tenants/{tenant_id}/members/{user_id}")
def remove_tenant_member(tenant_id: str, user_id: str, request: Request):
    context = tenant_service.require_role(_platform_user_id(request), tenant_id, {"owner", "admin"})
    member = runtime.store.get_membership(tenant_id, user_id)
    if member is not None and member.role == "owner" and context.role != "owner":
        raise PermissionError("只有租户所有者可以移除 owner 角色")
    runtime.store.remove_member(tenant_id, user_id)
    return {"status": "removed"}


@app.get("/tenants/{tenant_id}/settings")
def get_tenant_settings(tenant_id: str, request: Request):
    tenant_service.require_member(_platform_user_id(request), tenant_id)
    return runtime.store.get_tenant_settings(tenant_id)


@app.put("/tenants/{tenant_id}/settings")
def update_tenant_settings(tenant_id: str, data: TenantSettingsUpdateRequest, request: Request):
    tenant_service.require_role(_platform_user_id(request), tenant_id, {"owner", "admin"})
    return runtime.store.update_tenant_settings(
        tenant_id,
        data.model_dump(mode="json", exclude_unset=True),
    )


@app.post("/memory/consent")
@app.post("/me/memory/consent")
def update_memory_consent(data: MemoryConsentRequest, request: Request):
    """Store explicit user consent; withdrawing it erases durable memory."""

    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    granted = runtime.memory_mgr.set_consent(user_id, data.granted, tenant_id)
    log_event(logger, 20, "memory_consent_updated", user=fingerprint(user_id), granted=granted)
    return {"status": "updated", "granted": granted}


@app.get("/memory")
@app.get("/memory/export")
@app.get("/me/memory/export")
def export_memory(request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    payload = runtime.memory_mgr.export_user_memory(user_id, tenant_id)
    payload["user_id"] = user_id
    return payload


@app.delete("/memory")
@app.delete("/me/memory")
def delete_memory(request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    deleted = runtime.memory_mgr.delete_user_memory(user_id, revoke_consent=True, tenant_id=tenant_id)
    log_event(logger, 20, "memory_deleted", user=fingerprint(user_id), record_count=deleted)
    return {"status": "deleted", "deleted_count": deleted, "consent": False}


@app.get("/me/profile", response_model=UserProfileResponse)
def get_profile(request: Request):
    user_id = _platform_user_id(request)
    return profile_service.get(user_id, _tenant_context(request, user_id).tenant_id)


@app.put("/me/profile", response_model=UserProfileResponse)
def update_profile(data: UserProfileUpdateRequest, request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    payload = UserProfileUpdate.model_validate(data.model_dump(mode="json", exclude_unset=True))
    return profile_service.update(user_id, payload, actor=user_id, tenant_id=tenant_id)


@app.post("/me/profile/consent", response_model=UserProfileResponse)
def update_profile_consent(data: ProfileConsentRequest, request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    return profile_service.set_consent(user_id, data.granted, actor=user_id, tenant_id=tenant_id)


@app.get("/me/profile/export", response_model=UserProfileResponse)
def export_profile(request: Request):
    user_id = _platform_user_id(request)
    return profile_service.get(user_id, _tenant_context(request, user_id).tenant_id)


@app.delete("/me/profile", response_model=UserProfileResponse)
def delete_profile(request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    return profile_service.delete(user_id, actor=user_id, tenant_id=tenant_id)


@app.get("/admin/knowledge/documents", response_model=KnowledgeDocumentListResponse)
def list_knowledge_documents(request: Request, status: str | None = None):
    _knowledge_admin(request)
    tenant_id = _tenant_context(request).tenant_id
    return {"items": knowledge_service.list_documents(status=status, tenant_id=tenant_id)}


@app.post("/admin/knowledge/documents", status_code=201)
def upload_knowledge_document(data: KnowledgeDocumentUploadRequest, request: Request):
    actor = _knowledge_admin(request)
    tenant_id = _tenant_context(request).tenant_id
    return knowledge_service.upload_document(
        source_name=data.source_name,
        content=data.content,
        title=data.title,
        access_groups=data.access_groups,
        actor=actor,
        tenant_id=tenant_id,
    )


@app.get("/admin/knowledge/documents/{document_id}")
def knowledge_document_detail(document_id: str, request: Request):
    _knowledge_admin(request)
    return knowledge_service.get_document(document_id, _tenant_context(request).tenant_id)


@app.post("/admin/knowledge/documents/{document_id}/review")
def review_knowledge_document(document_id: str, data: KnowledgeReviewRequest, request: Request):
    actor = _knowledge_admin(request)
    return knowledge_service.review_document(
        document_id,
        actor=actor,
        approved=data.approved,
        note=data.note,
        tenant_id=_tenant_context(request).tenant_id,
    )


@app.post("/admin/knowledge/documents/{document_id}/publish")
def publish_knowledge_document(document_id: str, request: Request):
    return knowledge_service.publish_document(
        document_id,
        actor=_knowledge_admin(request),
        tenant_id=_tenant_context(request).tenant_id,
    )


@app.post("/admin/knowledge/documents/{document_id}/unpublish")
def unpublish_knowledge_document(document_id: str, request: Request):
    return knowledge_service.unpublish_document(
        document_id,
        actor=_knowledge_admin(request),
        tenant_id=_tenant_context(request).tenant_id,
    )


@app.post("/admin/knowledge/index/build")
def build_knowledge_index(data: KnowledgeBuildRequest, request: Request):
    if not data.confirm:
        raise ValueError("必须确认构建索引")
    return knowledge_service.build_index(
        actor=_knowledge_admin(request), tenant_id=_tenant_context(request).tenant_id
    )


@app.get("/admin/knowledge/index/builds")
def list_knowledge_builds(request: Request, limit: int = 20):
    _knowledge_admin(request)
    return {"items": knowledge_service.list_builds(limit=limit, tenant_id=_tenant_context(request).tenant_id)}


@app.get("/admin/knowledge/index/builds/{build_id}")
def knowledge_build_detail(build_id: str, request: Request):
    _knowledge_admin(request)
    return knowledge_service.get_build(build_id, _tenant_context(request).tenant_id)


@app.post("/admin/knowledge/index/rollback")
def rollback_knowledge_index(data: KnowledgeRollbackRequest, request: Request):
    return knowledge_service.rollback(
        data.target,
        actor=_knowledge_admin(request),
        tenant_id=_tenant_context(request).tenant_id,
    )


@app.post("/admin/knowledge/retrieval/test")
def test_knowledge_retrieval(data: KnowledgeRetrievalTestRequest, request: Request):
    return knowledge_service.retrieval_test(
        data.query,
        actor=_knowledge_admin(request),
        top_k=data.top_k,
        access_groups=data.access_groups,
        tenant_id=_tenant_context(request).tenant_id,
    )


@app.get("/admin/knowledge/analytics")
def knowledge_analytics(request: Request):
    _knowledge_admin(request)
    return knowledge_service.analytics(tenant_id=_tenant_context(request).tenant_id)


@app.get("/conversations", response_model=ConversationListResponse)
def list_conversations(request: Request, q: str | None = None, archived: bool = False, limit: int = 50):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    return {
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "updated_at": item.updated_at.isoformat(),
                "version": item.version,
                "archived_at": item.archived_at.isoformat() if item.archived_at else None,
            }
            for item in runtime.store.list_conversations(
                user_id,
                tenant_id,
                query_text=q,
                include_archived=archived,
                limit=limit,
            )
        ]
    }


@app.post("/conversations", status_code=201)
def create_conversation(data: ConversationCreateRequest, request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    conversation = runtime.store.create_conversation(
        conversation_id=str(uuid.uuid4()),
        user_id=user_id,
        title=data.title,
        tenant_id=tenant_id,
    )
    return {"id": conversation.id, "title": conversation.title, "expires_at": conversation.expires_at.isoformat()}


@app.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def conversation_detail(conversation_id: str, request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    snapshot = runtime.store.load(conversation_id, user_id, include_metadata=True, tenant_id=tenant_id)
    return {
        "id": snapshot.conversation_id,
        "title": snapshot.title,
        "version": snapshot.version,
        "messages": snapshot.messages,
    }


@app.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, data: ConversationUpdateRequest, request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    conversation = runtime.store.rename_conversation(conversation_id, user_id, data.title, tenant_id)
    return {
        "id": conversation.id,
        "title": conversation.title,
        "updated_at": conversation.updated_at.isoformat(),
        "version": conversation.version,
    }


@app.post("/conversations/{conversation_id}/archive")
def archive_conversation(conversation_id: str, request: Request):
    user_id = _platform_user_id(request)
    runtime.store.archive_conversation(conversation_id, user_id, _tenant_context(request, user_id).tenant_id)
    return {"status": "archived"}


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, request: Request):
    user_id = _platform_user_id(request)
    runtime.store.delete_conversation(conversation_id, user_id, _tenant_context(request, user_id).tenant_id)
    return {"status": "deleted"}


@app.post("/conversations/{conversation_id}/grill/actions", response_model=AskResponse)
def grill_action(conversation_id: str, data: ConversationActionRequest, request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    response = runtime.apply_grill_action(
        user_id=user_id,
        conversation_id=conversation_id,
        action=data.action,
        field_name=data.field,
        request_id=_request_id(request),
        trace_id=_trace_id(request),
        tenant_id=tenant_id,
    )
    return response.to_dict()


@app.post("/ask", response_model=AskResponse)
def ask(data: AskRequest, request: Request):
    payload = data.model_dump()
    user_id = _platform_user_id(request, payload)
    tenant_id = _tenant_context(request, user_id).tenant_id
    response = runtime.ask(
        data.question,
        user_id=user_id,
        conversation_id=data.conversation_id,
        request_id=_request_id(request),
        trace_id=_trace_id(request),
        tenant_id=tenant_id,
    )
    return response.to_dict()


@app.post("/ask/stream")
def ask_stream(data: AskRequest, request: Request):
    payload = data.model_dump()
    user_id = _platform_user_id(request, payload)
    tenant_id = _tenant_context(request, user_id).tenant_id
    stream = runtime.ask_stream(
        data.question,
        user_id=user_id,
        conversation_id=data.conversation_id,
        request_id=_request_id(request),
        trace_id=_trace_id(request),
        tenant_id=tenant_id,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/me/profile/suggestions", response_model=ProfileSuggestionListResponse)
def list_profile_suggestions(request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    return {"items": profile_service.list_suggestions(user_id, tenant_id)}


@app.post("/me/profile/suggestions/{suggestion_id}/accept", response_model=UserProfileResponse)
def accept_profile_suggestion(suggestion_id: str, request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    return profile_service.accept_suggestion(suggestion_id, user_id, actor=user_id, tenant_id=tenant_id)


@app.post("/me/profile/suggestions/{suggestion_id}/dismiss")
def dismiss_profile_suggestion(suggestion_id: str, request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    return profile_service.dismiss_suggestion(suggestion_id, user_id, tenant_id)


@app.get("/me/experience-settings", response_model=ExperienceSettingsResponse)
def get_experience_settings(request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    return runtime.store.get_experience_settings(user_id, tenant_id)


@app.put("/me/experience-settings", response_model=ExperienceSettingsResponse)
def update_experience_settings(data: ExperienceSettingsUpdateRequest, request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    settings_payload = data.model_dump(mode="json", exclude_unset=True)
    current = runtime.store.get_experience_settings(user_id, tenant_id)
    current_preferences = {
        key: current[key]
        for key in ("show_model_info", "show_sources", "show_safety_details", "answer_style", "pinned_shortcuts")
    }
    merged = ExperienceSettings.model_validate({**current_preferences, **settings_payload})
    return runtime.store.update_experience_settings(user_id, merged.model_dump(mode="json"), tenant_id)


@app.get("/me/shortcuts")
def get_shortcuts(request: Request):
    user_id = _platform_user_id(request)
    tenant_id = _tenant_context(request, user_id).tenant_id
    current = runtime.store.get_experience_settings(user_id, tenant_id)
    return {"items": list_shortcuts(current.get("pinned_shortcuts", []))}


@app.post("/conversations/{conversation_id}/regenerate", response_model=AskResponse)
def regenerate(conversation_id: str, request: Request):
    user_id = _platform_user_id(request)
    response = runtime.regenerate(
        user_id=user_id,
        conversation_id=conversation_id,
        request_id=_request_id(request),
        trace_id=_trace_id(request),
        tenant_id=_tenant_context(request, user_id).tenant_id,
    )
    return response.to_dict()


@app.post("/messages/{message_id}/feedback")
def message_feedback(message_id: int, data: MessageFeedbackRequest, request: Request):
    user_id = _platform_user_id(request)
    feedback = runtime.store.save_feedback(
        message_id=message_id,
        user_id=user_id,
        rating=data.rating,
        comment=data.comment,
        tenant_id=_tenant_context(request, user_id).tenant_id,
    )
    return {"status": "saved", "id": feedback.id, "message_id": feedback.message_id, "rating": feedback.rating}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("front.app:app", host="0.0.0.0", port=5000)
