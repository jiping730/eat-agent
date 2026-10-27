import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, g, jsonify, request, render_template
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from config import settings
from core.auth import AuthenticationError, AuthPrincipal, AuthService, hash_refresh_token
from core.conversation_runtime import ConversationRuntime
from core.logging_config import configure_logging, log_event
from core.persistence import ConversationAccessError
from core.rate_limiter import SlidingWindowRateLimiter


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = settings.max_request_bytes
CORS(app, origins=settings.cors_origin_list())

logger = configure_logging(settings.log_level)
runtime = ConversationRuntime()
auth_service = AuthService()
rate_limiter = SlidingWindowRateLimiter(settings.rate_limit_per_minute, redis_url=settings.redis_url)

PUBLIC_PATHS = {
    "/",
    "/healthz",
    "/readyz",
    "/auth/register",
    "/auth/login",
    "/auth/refresh",
    "/auth/logout",
}


def _error_response(message: str, status_code: int):
    return jsonify({"error": message, "request_id": getattr(g, "request_id", None)}), status_code


@app.before_request
def before_request():
    g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    g.request_started_at = time.perf_counter()
    g.principal = None

    if request.path in PUBLIC_PATHS or request.path.startswith("/static/"):
        return None

    try:
        g.principal = auth_service.authenticate(
            request.headers.get("Authorization"),
            request.headers.get("X-API-Key"),
        )
    except AuthenticationError as exc:
        return _error_response(str(exc), 401)

    if request.path == "/ask":
        client_key = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        if not rate_limiter.allow(client_key):
            return _error_response("请求过于频繁，请稍后再试", 429)
    return None


def _request_json() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return data


def _platform_user_id(data: dict | None = None) -> str:
    principal: AuthPrincipal | None = getattr(g, "principal", None)
    if principal and principal.auth_type == "jwt":
        requested_user_id = (data or {}).get("user_id")
        if requested_user_id is not None and requested_user_id != principal.user_id:
            raise PermissionError("不能使用其他用户身份")
        return principal.user_id

    requested_user_id = (data or {}).get("user_id") or request.headers.get("X-User-ID") or request.args.get("user_id")
    if not isinstance(requested_user_id, str) or not requested_user_id.strip():
        raise ValueError("缺少用户身份")
    return requested_user_id.strip()


def _token_response(user, token_pair):
    return {
        **token_pair.to_dict(),
        "user": {"id": user.id, "username": user.username, "roles": user.roles or []},
    }


@app.after_request
def after_request(response):
    request_id = getattr(g, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    elapsed = time.perf_counter() - getattr(g, "request_started_at", time.perf_counter())
    log_event(
        logger,
        20,
        "request_completed",
        request_id=request_id,
        method=request.method,
        path=request.path,
        status_code=response.status_code,
        response_time=round(elapsed, 4),
    )
    return response


@app.errorhandler(HTTPException)
def handle_http_error(error: HTTPException):
    return _error_response(error.description or "请求失败", error.code or 500)


@app.errorhandler(ConversationAccessError)
def handle_conversation_access_error(error: ConversationAccessError):
    return _error_response(str(error), 403)


@app.errorhandler(PermissionError)
def handle_permission_error(error: PermissionError):
    return _error_response(str(error), 403)


@app.errorhandler(ValueError)
def handle_value_error(error: ValueError):
    return _error_response(str(error), 400)


@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    log_event(logger, 40, "request_failed", request_id=getattr(g, "request_id", None), error_type=type(error).__name__)
    return _error_response("服务暂时不可用，请稍后再试", 500)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "version": settings.app_version})


@app.route("/readyz")
def readyz():
    try:
        runtime.store.ping()
    except Exception as exc:
        log_event(logger, 40, "readiness_failed", request_id=g.request_id, error_type=type(exc).__name__)
        return jsonify({"status": "not_ready", "request_id": g.request_id}), 503
    try:
        runtime.coordinator.ping()
    except Exception as exc:
        if settings.redis_url:
            log_event(logger, 40, "redis_readiness_failed", request_id=g.request_id, error_type=type(exc).__name__)
            return jsonify({"status": "not_ready", "request_id": g.request_id}), 503
    return jsonify({"status": "ready", "version": settings.app_version})


@app.route("/auth/register", methods=["POST"])
def register():
    data = _request_json()
    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not 3 <= len(username.strip()) <= 128:
        return _error_response("用户名长度必须在 3 到 128 个字符之间", 400)
    if not isinstance(password, str) or len(password) < 8:
        return _error_response("密码至少需要 8 个字符", 400)
    if not auth_service.jwt_enabled:
        return _error_response("当前服务未启用用户认证", 503)

    user_id = str(uuid.uuid4())
    try:
        user = runtime.store.create_user(
            user_id=user_id,
            username=username.strip(),
            password_hash=auth_service.hash_password(password),
        )
    except ValueError as exc:
        return _error_response(str(exc), 409)
    tokens = auth_service.issue_tokens(user.id, tuple(user.roles or []))
    runtime.store.save_refresh_token(
        user_id=user.id,
        token_hash=hash_refresh_token(tokens.refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days),
    )
    return jsonify(_token_response(user, tokens)), 201


@app.route("/auth/login", methods=["POST"])
def login():
    data = _request_json()
    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return _error_response("用户名和密码不能为空", 400)
    if not auth_service.jwt_enabled:
        return _error_response("当前服务未启用用户认证", 503)
    user = runtime.store.get_user_by_username(username.strip())
    if user is None or not user.is_active or not auth_service.verify_password(user.password_hash, password):
        return _error_response("用户名或密码错误", 401)
    tokens = auth_service.issue_tokens(user.id, tuple(user.roles or []))
    runtime.store.save_refresh_token(
        user_id=user.id,
        token_hash=hash_refresh_token(tokens.refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days),
    )
    return jsonify(_token_response(user, tokens))


@app.route("/auth/refresh", methods=["POST"])
def refresh():
    data = _request_json()
    refresh_token = data.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        return _error_response("refresh_token 不能为空", 400)
    token_record = runtime.store.get_refresh_token(hash_refresh_token(refresh_token))
    if token_record is None:
        return _error_response("刷新令牌无效或已过期", 401)
    user = runtime.store.get_user(token_record.user_id)
    if user is None or not user.is_active:
        return _error_response("用户不可用", 401)
    runtime.store.revoke_refresh_token(hash_refresh_token(refresh_token))
    tokens = auth_service.issue_tokens(user.id, tuple(user.roles or []))
    runtime.store.save_refresh_token(
        user_id=user.id,
        token_hash=hash_refresh_token(tokens.refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days),
    )
    return jsonify(_token_response(user, tokens))


@app.route("/auth/logout", methods=["POST"])
def logout():
    data = request.get_json(silent=True) or {}
    refresh_token = data.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token:
        runtime.store.revoke_refresh_token(hash_refresh_token(refresh_token))
    return jsonify({"status": "ok"})


@app.route("/me")
def me():
    user_id = _platform_user_id()
    user = runtime.store.get_user(user_id)
    if user is None:
        return _error_response("用户不存在", 404)
    return jsonify({"id": user.id, "username": user.username, "roles": user.roles or []})


@app.route("/conversations", methods=["GET", "POST"])
def conversations():
    data = request.get_json(silent=True) if request.method == "POST" else None
    data = data if isinstance(data, dict) else {}
    user_id = _platform_user_id(data)
    if request.method == "GET":
        return jsonify(
            {
                "items": [
                    {
                        "id": item.id,
                        "title": item.title,
                        "updated_at": item.updated_at.isoformat(),
                        "version": item.version,
                    }
                    for item in runtime.store.list_conversations(user_id)
                ]
            }
        )

    conversation = runtime.store.create_conversation(
        conversation_id=str(uuid.uuid4()),
        user_id=user_id,
        title=str(data.get("title") or "新会话"),
    )
    return jsonify({"id": conversation.id, "title": conversation.title}), 201


@app.route("/conversations/<conversation_id>", methods=["GET", "DELETE"])
def conversation_detail(conversation_id: str):
    user_id = _platform_user_id()
    if request.method == "DELETE":
        runtime.store.archive_conversation(conversation_id, user_id)
        return jsonify({"status": "archived"})
    snapshot = runtime.store.load(conversation_id, user_id)
    return jsonify(
        {
            "id": snapshot.conversation_id,
            "title": snapshot.title,
            "version": snapshot.version,
            "messages": snapshot.messages,
        }
    )


@app.route("/ask", methods=["POST"])
def ask():
    data = _request_json()

    question = data.get("question", "")
    if not isinstance(question, str) or not question.strip():
        return _error_response("question 不能为空", 400)

    user_id = _platform_user_id(data)
    conversation_id = data.get("conversation_id") or user_id
    if conversation_id is not None and not isinstance(conversation_id, str):
        return _error_response("conversation_id 必须是字符串", 400)

    response = runtime.ask(
        question,
        user_id=user_id,
        conversation_id=conversation_id,
        request_id=g.request_id,
    )
    return jsonify(response.to_dict())


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
