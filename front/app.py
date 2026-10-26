import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, g, jsonify, request, render_template
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from config import settings
from core.conversation_runtime import ConversationRuntime
from core.logging_config import configure_logging, log_event
from core.persistence import ConversationAccessError
from core.rate_limiter import SlidingWindowRateLimiter


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = settings.max_request_bytes
CORS(app, origins=settings.cors_origin_list())

logger = configure_logging(settings.log_level)
runtime = ConversationRuntime()
rate_limiter = SlidingWindowRateLimiter(settings.rate_limit_per_minute)


def _error_response(message: str, status_code: int):
    return jsonify({"error": message, "request_id": getattr(g, "request_id", None)}), status_code


@app.before_request
def before_request():
    g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    g.request_started_at = time.perf_counter()

    if request.path in {"/", "/healthz", "/readyz"} or request.path.startswith("/static/"):
        return None

    if settings.app_api_key and request.headers.get("X-API-Key") != settings.app_api_key:
        return _error_response("未授权", 401)

    if request.path == "/ask":
        client_key = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        if not rate_limiter.allow(client_key):
            return _error_response("请求过于频繁，请稍后再试", 429)
    return None


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
    return jsonify({"status": "ready", "version": settings.app_version})


@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error_response("请求体必须是 JSON 对象", 400)

    question = data.get("question", "")
    if not isinstance(question, str) or not question.strip():
        return _error_response("question 不能为空", 400)

    user_id = data.get("user_id")
    conversation_id = data.get("conversation_id") or user_id
    if user_id is not None and not isinstance(user_id, str):
        return _error_response("user_id 必须是字符串", 400)
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
