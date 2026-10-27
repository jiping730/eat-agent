"""Deterministic request routing for the small platform.

The router deliberately separates *what the user wants to achieve* from
*how the user wants the platform to help*.  A goal such as losing weight is
not, by itself, a request for a meal plan.  Keeping this decision outside of
the Grill engine prevents every domain goal from being turned into a form.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import BaseModel, Field

from config import settings


class RequestIntent(BaseModel):
    """Normalized intent consumed by the workflow and persisted in context."""

    domain: str = "general"
    operation: str = "answer"
    task: str | None = None
    goal: str | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    slots: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    continuation: bool = False


_SEARCH_MARKERS = ("搜索", "查一下", "查找", "检索", "网上", "网络", "最新", "新闻")
_CALCULATE_MARKERS = ("计算", "算一下", "总热量", "摄入多少", "摄入量", "合计", "加起来")
_LOOKUP_MARKERS = ("查询", "查", "多少热量", "多少卡", "卡路里", "热量是多少", "热量")
_PLAN_MARKERS = ("安排", "制定", "规划", "计划", "餐单", "菜单", "食谱", "搭配", "推荐")
_ADVICE_MARKERS = (
    "建议",
    "怎么做",
    "怎么",
    "如何",
    "怎么办",
    "原则",
    "方法",
    "技巧",
    "应该",
    "想知道",
    "想了解",
)
_EXECUTE_MARKERS = ("执行", "开始执行", "提交", "确认生成", "直接生成")
_MEAL_MARKERS = ("早餐", "午餐", "晚餐", "夜宵", "餐食", "吃什么", "菜", "食谱", "餐单", "菜单")
_NUTRITION_MARKERS = (
    "减肥",
    "减脂",
    "控制体重",
    "增肌",
    "健康饮食",
    "饮食目标",
    "体重管理",
    "热量",
    "卡路里",
    "营养",
)


def _contains(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _goal_for(text: str, domain: str) -> str | None:
    if domain == "nutrition":
        if _contains(text, ("减肥", "减脂", "控制体重", "体重管理")):
            return "weight_control"
        if "增肌" in text:
            return "muscle_gain"
        if _contains(text, ("健康饮食", "均衡饮食")):
            return "balanced_diet"
    if domain == "general":
        if _contains(text, ("提高英语", "学英语", "英语学习")):
            return "improve_language"
        if _contains(text, ("改善睡眠", "睡眠")):
            return "improve_sleep"
        if _contains(text, ("做项目", "项目规划", "开发项目")):
            return "build_project"
    return None


def _slots_for(text: str) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    meal_values = {
        "早餐": "breakfast",
        "午餐": "lunch",
        "中餐": "lunch",
        "晚餐": "dinner",
        "夜宵": "late_night",
    }
    for marker, value in meal_values.items():
        if marker in text:
            slots["meal_type"] = value
            break
    if "没有忌口" in text or "无忌口" in text or "没有过敏" in text:
        slots["allergy_info"] = "none"
    return slots


def _previous_intent(previous_context: Mapping[str, Any] | None) -> tuple[str | None, str, str]:
    context = previous_context or {}
    task = context.get("intent") or context.get("active_task")
    operation = context.get("operation") or ("plan" if task in {"meal_planner", "calorie_query"} else "answer")
    domain = context.get("domain") or ("nutrition" if task in {"meal_planner", "calorie_query"} else "general")
    return task, operation, domain


def classify_request(
    text: str,
    previous_context: Mapping[str, Any] | None = None,
) -> RequestIntent:
    """Classify a request without an extra model call.

    Strong operation markers win over continuation.  If the previous turn is
    waiting for a Grill field and the new message has no new operation, the
    message is treated as the answer to that field.
    """

    normalized = (text or "").strip()
    previous = previous_context or {}
    previous_task, previous_operation, previous_domain = _previous_intent(previous)
    has_pending = bool(previous.get("pending_field") and previous_task)

    if _contains(normalized, _SEARCH_MARKERS):
        return RequestIntent(
            domain="general",
            operation="lookup",
            task="web_search",
            goal=None,
            confidence=0.98,
        )

    domain = (
        "nutrition" if _contains(normalized, _NUTRITION_MARKERS) or _contains(normalized, _MEAL_MARKERS) else "general"
    )
    goal = _goal_for(normalized, domain)

    # A calculation is more specific than a generic calorie lookup.
    if _contains(normalized, _CALCULATE_MARKERS):
        if domain == "general" and _contains(normalized, ("热量", "卡路里", "摄入")):
            domain = "nutrition"
        return RequestIntent(
            domain=domain,
            operation="calculate",
            task="calorie_query" if domain == "nutrition" else None,
            goal=goal,
            entities={"topic": "calorie"} if domain == "nutrition" else {},
            slots=_slots_for(normalized),
            confidence=0.97,
        )

    if _contains(normalized, _LOOKUP_MARKERS):
        if domain == "general" and _contains(normalized, ("热量", "卡路里")):
            domain = "nutrition"
        return RequestIntent(
            domain=domain,
            operation="lookup",
            task="calorie_query" if domain == "nutrition" else None,
            goal=goal,
            entities={"topic": "calorie"} if domain == "nutrition" else {},
            slots=_slots_for(normalized),
            confidence=0.97,
        )

    if _contains(normalized, _EXECUTE_MARKERS):
        return RequestIntent(
            domain=domain,
            operation="execute",
            task="meal_planner" if domain == "nutrition" and _contains(normalized, _MEAL_MARKERS) else None,
            goal=goal,
            slots=_slots_for(normalized),
            confidence=0.94,
        )

    # Planning verbs are intentionally checked before broad advice words.
    if _contains(normalized, _PLAN_MARKERS) or (
        domain == "nutrition"
        and _contains(normalized, _MEAL_MARKERS)
        and _contains(normalized, ("帮我", "我要", "给我"))
    ):
        return RequestIntent(
            domain=domain,
            operation="plan",
            task="meal_planner" if domain == "nutrition" and _contains(normalized, _MEAL_MARKERS) else None,
            goal=goal,
            entities={"topic": "meal"} if domain == "nutrition" and _contains(normalized, _MEAL_MARKERS) else {},
            slots=_slots_for(normalized),
            confidence=0.96,
        )

    if _contains(normalized, _ADVICE_MARKERS) or (
        _contains(normalized, ("想", "希望", "我要", "我想", "想要")) and not _contains(normalized, _MEAL_MARKERS)
    ):
        return RequestIntent(
            domain=domain,
            operation="advice",
            task=None,
            goal=goal,
            entities={"topic": "nutrition"} if domain == "nutrition" else {},
            slots=_slots_for(normalized),
            confidence=0.93,
        )

    if has_pending:
        return RequestIntent(
            domain=previous_domain,
            operation=(
                previous_operation if previous_operation in {"plan", "lookup", "calculate", "execute"} else "plan"
            ),
            task=previous_task,
            goal=goal or previous.get("goal"),
            slots=_slots_for(normalized),
            confidence=0.9,
            continuation=True,
        )

    if domain == "nutrition" and _contains(normalized, _MEAL_MARKERS):
        return RequestIntent(
            domain=domain,
            operation="plan",
            task="meal_planner",
            goal=goal,
            entities={"topic": "meal"},
            slots=_slots_for(normalized),
            confidence=0.9,
        )

    return RequestIntent(
        domain=domain,
        operation="answer",
        task=None,
        goal=goal,
        slots=_slots_for(normalized),
        confidence=0.75 if domain == "general" else 0.85,
    )


def classify_request_with_model(
    text: str,
    previous_context: Mapping[str, Any] | None = None,
    *,
    user_id: str | None = None,
    gateway: Any | None = None,
) -> RequestIntent:
    """Use the low-cost model only when deterministic routing is uncertain.

    Explicit nutrition and Grill routes remain deterministic.  The model is a
    bounded fallback for ambiguous natural-language requests, and malformed or
    unavailable model output always falls back to the local classifier.
    """

    deterministic = classify_request(text, previous_context)
    if not settings.llm_intent_enabled or deterministic.confidence >= settings.llm_intent_min_confidence:
        return deterministic

    from utils.llm import ModelGateway

    resolved_gateway = gateway or ModelGateway()
    if not resolved_gateway.available:
        return deterministic
    prompt = f"""你是一个请求路由器。只输出合法 JSON，不要输出 Markdown 或解释。
根据用户请求选择领域和操作，不要把“想减肥/想增肌”自动改写为制定餐单。
允许的 domain：general、nutrition。
允许的 operation：answer、advice、lookup、calculate、plan、execute。
允许的 task：null、meal_planner、calorie_query、web_search。
JSON 字段：domain、operation、task、goal、entities、slots、confidence、continuation。

历史上下文：{dict(previous_context or {})}
用户请求：{text}
"""
    try:
        response = resolved_gateway.complete(prompt, task="intent", user_id=user_id)
        content = response.content.strip()
        if content.startswith("```"):
            content = content.strip("`").removeprefix("json").strip()
        payload = json.loads(content)
        candidate = RequestIntent.model_validate(payload)
        if candidate.domain not in {"general", "nutrition"}:
            return deterministic
        if candidate.operation not in {"answer", "advice", "lookup", "calculate", "plan", "execute"}:
            return deterministic
        if candidate.task not in {None, "meal_planner", "calorie_query", "web_search"}:
            return deterministic
        return candidate
    except Exception:
        return deterministic
