"""Runtime clarification engine for the nutrition assistant.

This module is a deterministic state machine inspired by grill-me/grilling.
It is independent from LangGraph, Flask, and model providers, so it can be
tested without network access and later enhanced with typed LLM adapters.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


FieldPriority = Literal["critical", "preferred"]
FieldSource = Literal["user", "inferred", "preference", "default"]
GrillAction = Literal["execute", "clarify", "offer_candidates", "pending_confirmation", "fallback"]


class Candidate(BaseModel):
    label: str
    value: Any
    description: str = ""


class FieldSpec(BaseModel):
    name: str
    description: str
    priority: FieldPriority = "preferred"
    aliases: list[str] = Field(default_factory=list)
    known_values: dict[str, str] = Field(default_factory=dict)
    default_value: Any = None
    has_default: bool = False
    safety_critical: bool = False
    allow_free_text: bool = False
    question: str | None = None


class TaskProfile(BaseModel):
    task_type: str
    version: str = "1"
    fields: list[FieldSpec]
    max_clarifications: int = 3
    max_total_rounds: int = 5
    candidate_count: int = 3
    confirmation_required: bool = False


class GrillContext(BaseModel):
    status: Literal["idle", "collecting", "completed", "fallback"] = "idle"
    intent: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    sources: dict[str, FieldSource] = Field(default_factory=dict)
    pending_field: str | None = None
    clarification_count: int = 0
    total_rounds: int = 0
    asked_fields: list[str] = Field(default_factory=list)
    last_question: str | None = None

    @classmethod
    def from_value(cls, value: Any) -> "GrillContext":
        if isinstance(value, cls):
            return value.model_copy(deep=True)
        if isinstance(value, dict):
            return cls.model_validate(value)
        return cls()


class GrillResult(BaseModel):
    action: GrillAction
    message: str | None = None
    question: str | None = None
    target_field: str | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    context: GrillContext
    missing_fields: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _meal_profile() -> TaskProfile:
    return TaskProfile(
        task_type="meal_planner",
        version="1",
        fields=[
            FieldSpec(
                name="meal_type", description="餐次", priority="critical",
                aliases=["早餐", "午餐", "晚餐", "宵夜"],
                known_values={"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "late_night": "宵夜"},
                question="你想安排哪一餐？",
            ),
            FieldSpec(
                name="allergy_info", description="过敏原或需要避开的食物", priority="critical",
                aliases=["过敏", "忌口", "不吃", "避开"], known_values={"none": "没有过敏或忌口"},
                safety_critical=True, allow_free_text=True,
                question="你有需要避开的食物或过敏原吗？可以回答“没有”，也可以直接列出食物。",
            ),
            FieldSpec(
                name="health_goal", description="饮食目标", priority="preferred",
                aliases=["减脂", "减肥", "控制体重", "增肌", "均衡", "健康"],
                known_values={"weight_control": "控制体重", "muscle_gain": "增肌", "balanced": "均衡饮食"},
                default_value="balanced", has_default=True,
            ),
            FieldSpec(name="servings", description="人数", priority="preferred", aliases=["一人", "两人", "几人", "人份"], default_value=1, has_default=True),
            FieldSpec(name="cooking_time", description="可接受的烹饪时间", priority="preferred", aliases=["分钟", "时间", "快手"], default_value="30分钟内", has_default=True),
            FieldSpec(name="cuisine", description="菜系偏好", priority="preferred", aliases=["中餐", "西餐", "日式", "韩式", "川菜", "粤菜"], default_value="不限", has_default=True),
        ],
    )


def _calorie_profile() -> TaskProfile:
    return TaskProfile(
        task_type="calorie_query", version="1",
        fields=[
            FieldSpec(name="food", description="食物名称", priority="critical", aliases=["食物", "食品"], allow_free_text=True, question="你想查询哪种食物的热量？"),
            FieldSpec(name="amount", description="食物重量或份量", priority="preferred", aliases=["克", "g", "公斤", "份", "个", "块"], default_value="100g", has_default=True),
            FieldSpec(name="cooking_state", description="生重还是熟重", priority="preferred", aliases=["生重", "熟重", "生的", "熟的"], default_value="未说明，按知识库常用口径估算", has_default=True),
        ],
    )


PROFILES: dict[str, TaskProfile] = {"meal_planner": _meal_profile(), "calorie_query": _calorie_profile()}


def get_profile(intent: str | None) -> TaskProfile | None:
    return PROFILES.get(intent) if intent else None


_NONE_WORDS = ("没有", "无", "都可以", "都行", "不忌口", "不过敏", "没有忌口")


def _clean(value: str) -> str:
    value = re.sub(r"^(请问|请|帮我|查询|查一下|查|想知道|告诉我|看一下)\s*", "", value)
    return value.strip(" ，。！？?的")


def _is_unknown_answer(text: str) -> bool:
    normalized = text.strip().strip("，。！？? ")
    return normalized in {"不知道", "不清楚", "不确定", "没想好", "还不知道"}


def _known_value(field: FieldSpec, text: str) -> Any | None:
    lowered = text.lower()
    for value, label in field.known_values.items():
        if value.lower() in lowered or label.lower() in lowered:
            return value
    if field.name in {"allergy_info", "dietary_restrictions"} and any(word in text for word in _NONE_WORDS):
        return "none"
    return None


def _extract_food(text: str) -> str | None:
    match = re.search(r"(.+?)(?:的)?(?:热量|卡路里|多少卡|卡多少)", text)
    if not match:
        return None
    value = _clean(match.group(1))
    value = re.sub(r"(多少|有多少|大概|大约)\s*$", "", value).strip()
    return value if value and value not in {"多少", "热量"} else None


def _extract_amount(text: str) -> str | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(克|g|公斤|kg|个|份|块|片)", text, re.IGNORECASE)
    return f"{match.group(1)}{match.group(2)}" if match else None


def extract_for_field(field: FieldSpec, text: str) -> Any | None:
    known = _known_value(field, text)
    if known is not None:
        return known
    if field.name == "food":
        return _extract_food(text)
    if field.name == "amount":
        return _extract_amount(text)
    if field.name == "servings":
        match = re.search(r"(\d+)\s*(人|份)", text)
        return int(match.group(1)) if match else None
    if field.name == "cooking_time":
        match = re.search(r"(\d+)\s*分钟", text)
        return f"{match.group(1)}分钟内" if match else None
    return None


def extract_fields(profile: TaskProfile, text: str) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    for field in profile.fields:
        value = extract_for_field(field, text)
        if value is not None:
            extracted[field.name] = value
    return extracted


def field_label(field: FieldSpec, value: Any) -> str:
    return field.known_values.get(str(value), str(value))


class GrillEngine:
    """Ask only for information that blocks a useful answer."""

    def process(self, profile: TaskProfile, user_input: str, context: dict[str, Any] | GrillContext | None = None, *, current_intent: str | None = None) -> GrillResult:
        ctx = GrillContext.from_value(context)
        # completed 表示上一项任务已经结束；intent 变化表示用户开启了新任务。
        # collecting/fallback 只代表“还在收集”，不能因此把用户补充的信息丢掉。
        if ctx.status == "completed" or (ctx.intent and current_intent and ctx.intent != current_intent):
            ctx = GrillContext()
        elif ctx.status == "fallback":
            ctx.status = "collecting"
        if ctx.intent is None:
            ctx.intent = profile.task_type
        ctx.status = "collecting"
        ctx.total_rounds += 1

        pending_field = ctx.pending_field
        if pending_field:
            target = next((f for f in profile.fields if f.name == pending_field), None)
            if target:
                value = extract_for_field(target, user_input)
                if (
                    value is None
                    and user_input.strip()
                    and target.allow_free_text
                    and not _is_unknown_answer(user_input)
                ):
                    value = user_input.strip()
                if value is not None:
                    ctx.fields[target.name] = value
                    ctx.sources[target.name] = "user"
                    ctx.pending_field = None

        for name, value in extract_fields(profile, user_input).items():
            if name not in ctx.fields or pending_field == name:
                ctx.fields[name] = value
                ctx.sources[name] = "user"

        missing_critical = [field for field in profile.fields if field.priority == "critical" and not self._exists(ctx.fields.get(field.name))]
        if missing_critical:
            if ctx.total_rounds > profile.max_total_rounds:
                return self._fallback(profile, ctx, missing_critical)
            return self._clarify(profile, ctx, missing_critical[0])

        assumptions: list[str] = []
        for field in profile.fields:
            if field.name not in ctx.fields and field.has_default:
                ctx.fields[field.name] = field.default_value
                ctx.sources[field.name] = "default"
                assumptions.append(f"{field.description}按“{field_label(field, field.default_value)}”处理")
        ctx.pending_field = None
        ctx.status = "completed"
        if profile.confirmation_required:
            return GrillResult(action="pending_confirmation", message="信息已经足够，请确认后继续。", context=ctx, assumptions=assumptions)
        return GrillResult(action="execute", context=ctx, assumptions=assumptions)

    def _clarify(self, profile: TaskProfile, ctx: GrillContext, field: FieldSpec) -> GrillResult:
        if ctx.clarification_count >= profile.max_clarifications:
            return self._fallback(profile, ctx, [field])
        ctx.clarification_count += 1
        ctx.pending_field = field.name
        if field.name not in ctx.asked_fields:
            ctx.asked_fields.append(field.name)
        question = field.question or f"请补充你的{field.description}。"
        ctx.last_question = question
        candidates = [Candidate(label=label, value=value) for value, label in field.known_values.items()][: profile.candidate_count]
        return GrillResult(action="clarify", question=question, message=question, target_field=field.name, candidates=candidates, context=ctx, missing_fields=[field.name])

    @staticmethod
    def _fallback(profile: TaskProfile, ctx: GrillContext, missing_fields: list[FieldSpec]) -> GrillResult:
        missing = [item.description for item in missing_fields]
        ctx.status = "fallback"
        ctx.pending_field = missing_fields[0].name if missing_fields else None
        message = f"为了避免猜错，我还需要这些信息：{'、'.join(missing)}。请尽量一次性补充。"
        return GrillResult(
            action="fallback",
            message=message,
            target_field=ctx.pending_field,
            context=ctx,
            missing_fields=[item.name for item in missing_fields],
        )

    @staticmethod
    def _exists(value: Any) -> bool:
        return value is not None and (not isinstance(value, str) or bool(value.strip()))
