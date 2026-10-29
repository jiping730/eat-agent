"""Structured AI estimation for user-entered meal records.

This module intentionally lives outside the conversation workflow. A meal
record is a small data-entry action, so calling ``/ask`` would create an
unwanted conversation and would force the frontend to parse prose.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

from utils.llm import ModelGateway, ModelGatewayError, get_model_gateway


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.IGNORECASE | re.DOTALL)
_CONFIDENCES = {"low", "medium", "high"}
_MEAL_LABELS = {
    "breakfast": "早餐",
    "lunch": "午餐",
    "dinner": "晚餐",
    "snack": "加餐",
}


@dataclass(frozen=True)
class NutritionEstimate:
    calories: int | None
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    confidence: str
    assumptions: list[str]
    source: str
    status: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "calories": self.calories,
            "protein_g": self.protein_g,
            "carbs_g": self.carbs_g,
            "fat_g": self.fat_g,
            "confidence": self.confidence,
            "assumptions": self.assumptions,
            "source": self.source,
            "status": self.status,
            "message": self.message,
        }


def _unavailable(message: str = "暂时无法估算热量") -> NutritionEstimate:
    return NutritionEstimate(
        calories=None,
        protein_g=None,
        carbs_g=None,
        fat_g=None,
        confidence="unavailable",
        assumptions=[],
        source="unavailable",
        status="unavailable",
        message=message,
    )


def _parse_json(content: str) -> Mapping[str, Any]:
    normalized = content.strip()
    fenced = _CODE_FENCE_RE.match(normalized)
    if fenced:
        normalized = fenced.group(1).strip()
    payload = json.loads(normalized)
    if not isinstance(payload, Mapping):
        raise ValueError("估算结果不是 JSON 对象")
    return payload


def _number(value: Any, *, integer: bool, maximum: float) -> int | float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or number > maximum:
        return None
    if integer:
        return int(round(number))
    return round(number, 1)


def _assumptions(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:160] for item in value if str(item).strip()][:8]


def _normalize_result(payload: Mapping[str, Any]) -> NutritionEstimate:
    calories = _number(payload.get("calories"), integer=True, maximum=10_000)
    if calories is None:
        return _unavailable("AI 没有返回可靠的热量估算")

    confidence = str(payload.get("confidence", "medium")).strip().lower()
    if confidence not in _CONFIDENCES:
        confidence = "medium"
    return NutritionEstimate(
        calories=int(calories),
        protein_g=_number(payload.get("protein_g"), integer=False, maximum=1_000),
        carbs_g=_number(payload.get("carbs_g"), integer=False, maximum=1_000),
        fat_g=_number(payload.get("fat_g"), integer=False, maximum=1_000),
        confidence=confidence,
        assumptions=_assumptions(payload.get("assumptions")),
        source="ai",
        status="estimated",
        message="热量为 AI 根据食物描述和常见份量估算的近似值",
    )


def _prompt(food_name: str, meal_type: str, note: str) -> str:
    meal_label = _MEAL_LABELS.get(meal_type, meal_type)
    return f"""你是轻食应用中的营养记录估算器。请为用户刚刚记录的这一餐估算热量和宏量营养素。

记录信息：
- 餐次：{meal_label}
- 食物：{food_name.strip()}
- 备注：{note.strip() or "用户未提供额外份量或做法"}

要求：
1. 普通用户通常不知道热量；即使没有写清克数，也请按最合理的常见一份进行估算，不要追问。
2. 将份量、烹饪方式等不确定性写入 assumptions，例如“按一小碗、少油估算”。
3. 只输出 JSON 对象，不要 Markdown、解释或医学结论。calories 必须是整数，单位为千卡；宏量营养素单位为克。
4. 这是生活记录的近似值，不要假装精确。JSON 必须包含 calories、protein_g、carbs_g、fat_g、confidence、assumptions 这几个字段；请根据本次记录实际计算，不要使用固定默认数字。
"""


def estimate_nutrition(
    food_name: str,
    meal_type: str,
    note: str = "",
    *,
    user_id: str | None = None,
    gateway: ModelGateway | Any | None = None,
) -> NutritionEstimate:
    """Return a safe estimate or an explicit unavailable result.

    A missing model key or malformed model output must never become a made-up
    calorie number in a health record.
    """

    if not food_name.strip():
        raise ValueError("食物名称不能为空")
    resolved_gateway = gateway or get_model_gateway()
    if hasattr(resolved_gateway, "available") and not resolved_gateway.available:
        return _unavailable("AI 服务未配置，记录已保存，可稍后重试估算")

    try:
        request = resolved_gateway.build_request(
            "nutrition_estimate",
            max_tokens=512,
            temperature=0.1,
        )
        result = resolved_gateway.complete(
            _prompt(food_name, meal_type, note),
            request=request,
            task="nutrition_estimate",
            user_id=user_id,
        )
        return _normalize_result(_parse_json(result.content))
    except (ModelGatewayError, ValueError, TypeError, json.JSONDecodeError):
        return _unavailable("AI 暂时无法完成估算，记录已保存，可稍后重试")
