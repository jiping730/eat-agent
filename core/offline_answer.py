"""Deterministic answer fallback used when the model path is unavailable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from config import settings


@dataclass(frozen=True)
class OfflineAnswer:
    answer: str
    reason: str
    confidence: str
    next_step: str

    def to_dict(self) -> dict[str, str]:
        return {
            "mode": "offline",
            "reason": self.reason,
            "confidence": self.confidence,
            "next_step": self.next_step,
        }


class OfflineAnswerService:
    """Keep rule-based fallbacks explicit and free of invented exact numbers."""

    @staticmethod
    def reason_for(error: Exception) -> str:
        name = type(error).__name__.lower()
        if "timeout" in name or "timedout" in name:
            return "timeout"
        if not settings.zhipuai_api_key and not settings.openai_api_key:
            return "llm_unavailable"
        if "modelunavailable" in name:
            return "llm_unavailable"
        return "llm_error"

    def answer(
        self,
        *,
        operation: str,
        request_intent: Mapping[str, Any],
        current_goal: str | None,
        fields: Mapping[str, Any] | None = None,
        tool_outputs: Mapping[str, Any] | None = None,
        error: Exception,
    ) -> OfflineAnswer:
        fields = fields or {}
        tool_outputs = tool_outputs or {}
        reason = self.reason_for(error)
        if operation == "advice":
            if request_intent.get("domain") == "nutrition" and request_intent.get("goal") == "weight_control":
                answer = (
                    "如果目标是减脂，先从可持续的热量控制开始：每餐保证适量蛋白质，增加蔬菜和高纤维主食，"
                    "减少含糖饮料、油炸和高热量零食；不要极端节食，并结合规律睡眠和适度运动。"
                    "如果你愿意，我还可以继续为你制定具体餐单。"
                )
            elif request_intent.get("domain") == "nutrition":
                answer = "建议先明确你的饮食目标，再从均衡摄入、适量蛋白质、足量蔬菜和控制高糖高油食物开始，逐步调整更容易坚持。"
            else:
                answer = "可以先明确目标和当前情况，再拆成几个可执行的小步骤，设定一个容易坚持的节奏，并根据结果逐步调整。"
        elif operation == "plan" and current_goal != "meal_planner":
            answer = "可以制定方案。请告诉我你希望达成的目标、当前情况和主要限制条件，我会据此拆解步骤。"
        elif current_goal == "meal_planner":
            answer = (
                f"我按{fields.get('meal_type', '当前餐次')}、{fields.get('health_goal', '均衡饮食')}、"
                f"{fields.get('allergy_info', '未说明忌口')}为你安排。"
                "建议选择一份优质蛋白、两份蔬菜和适量主食；如果你愿意，我还可以继续细化菜品和克重。"
            )
        else:
            answer = str(tool_outputs.get("calorie_query") or "当前无法连接模型，暂时只能提供通用建议；请稍后重试或检查模型配置。")
        next_step = (
            "配置 ZHIPUAI_API_KEY 或 OPENAI_API_KEY 后可获得更完整的个性化回答。"
            if reason == "llm_unavailable"
            else "可以稍后重试；在模型恢复前，精确营养数值请以食品标签或已发布知识来源为准。"
        )
        return OfflineAnswer(answer=answer, reason=reason, confidence="medium", next_step=next_step)
