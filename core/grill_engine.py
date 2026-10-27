"""Deterministic, configurable clarification engine for the nutrition platform.

Grill is deliberately independent from LangGraph and model providers.  It
turns a task profile plus one user message into a versioned decision that the
workflow can safely persist, display, and gate tool execution on.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


FieldPriority = Literal["critical", "preferred"]
FieldType = Literal["enum", "number", "date", "text", "boolean"]
FieldSource = Literal["user", "inferred", "preference", "default", "refused"]
GrillAction = Literal[
    "execute",
    "advise",
    "clarify",
    "offer_candidates",
    "pending_confirmation",
    "fallback",
    "reject",
    "switch",
    "multi_task",
]
GrillStatus = Literal[
    "idle",
    "collecting",
    "completed",
    "fallback",
    "awaiting_confirmation",
    "rejected",
]


class Candidate(BaseModel):
    label: str
    value: Any
    description: str = ""


class FieldState(BaseModel):
    """Explain how a value entered the context."""

    source: FieldSource
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = ""


class ValidationIssue(BaseModel):
    code: Literal["invalid_value", "unknown_answer", "conflict", "dependency", "low_confidence"]
    field: str
    message: str


class DependencyRule(BaseModel):
    """Require fields when all values in ``when`` match the context."""

    when: dict[str, Any] = Field(default_factory=dict)
    require: list[str] = Field(default_factory=list)
    message: str | None = None


class ConflictRule(BaseModel):
    """Describe mutually exclusive phrases for one field."""

    field: str
    exclusive_values: list[Any] = Field(default_factory=list)
    conflict_patterns: list[str] = Field(default_factory=list)
    message: str = "这项信息存在冲突，请确认后再继续。"


class FieldSpec(BaseModel):
    name: str
    description: str
    field_type: FieldType = "text"
    priority: FieldPriority = "preferred"
    aliases: list[str] = Field(default_factory=list)
    known_values: dict[str, str] = Field(default_factory=dict)
    default_value: Any = None
    has_default: bool = False
    safety_critical: bool = False
    allow_free_text: bool = False
    question: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    max_length: int | None = None
    confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    refusal_allowed: bool = False


class OperationSpec(BaseModel):
    """Operation-specific Grill policy for one task profile."""

    requires_grill: bool = True
    required_fields: list[str] = Field(default_factory=list)


class TaskProfile(BaseModel):
    task_type: str
    version: str = "1.0"
    fields: list[FieldSpec]
    max_clarifications: int = Field(default=3, ge=0)
    max_total_rounds: int = Field(default=5, ge=1)
    candidate_count: int = Field(default=3, ge=0)
    confirmation_required: bool = False
    confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    refusal_policy: Literal["fallback", "reject", "default"] = "fallback"
    dependencies: list[DependencyRule] = Field(default_factory=list)
    conflicts: list[ConflictRule] = Field(default_factory=list)
    operations: dict[str, OperationSpec] = Field(default_factory=dict)

    def field(self, name: str | None) -> FieldSpec | None:
        if not name:
            return None
        return next((item for item in self.fields if item.name == name), None)


class GrillContext(BaseModel):
    status: GrillStatus = "idle"
    intent: str | None = None
    profile_version: str | None = None
    previous_intent: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    sources: dict[str, FieldSource] = Field(default_factory=dict)
    field_states: dict[str, FieldState] = Field(default_factory=dict)
    pending_field: str | None = None
    clarification_count: int = 0
    total_rounds: int = 0
    asked_fields: list[str] = Field(default_factory=list)
    last_question: str | None = None
    validation_errors: list[ValidationIssue] = Field(default_factory=list)
    conflict_fields: list[str] = Field(default_factory=list)
    refused_fields: list[str] = Field(default_factory=list)
    task_queue: list[str] = Field(default_factory=list)
    active_task: str | None = None
    domain: str | None = None
    operation: str | None = None
    goal: str | None = None
    intent_payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_value(cls, value: Any) -> "GrillContext":
        if isinstance(value, cls):
            return value.model_copy(deep=True)
        if isinstance(value, dict):
            return cls.model_validate(value)
        return cls()


class GrillResult(BaseModel):
    """Stable Grill v1 decision envelope."""

    schema_version: str = "1.0"
    action: GrillAction
    task: str | None = None
    operation: str | None = None
    profile_version: str | None = None
    message: str | None = None
    question: str | None = None
    target_field: str | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    context: GrillContext
    missing_fields: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)
    task_queue: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class _Extraction(BaseModel):
    value: Any = None
    confidence: float = 0.0
    evidence: str = ""
    unknown: bool = False
    refused: bool = False
    issue: ValidationIssue | None = None


PROFILE_DIR = Path(__file__).resolve().parent.parent / "config" / "grill_profiles"


def load_profiles(directory: str | Path = PROFILE_DIR) -> dict[str, TaskProfile]:
    """Load and validate all JSON profiles, selecting the highest version."""

    profile_dir = Path(directory)
    profiles: dict[str, TaskProfile] = {}
    if not profile_dir.exists():
        return profiles
    for path in sorted(profile_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        profile = TaskProfile.model_validate(payload)
        previous = profiles.get(profile.task_type)
        if previous is None or profile.version >= previous.version:
            profiles[profile.task_type] = profile
    return profiles


PROFILES: dict[str, TaskProfile] = load_profiles()


def get_profile(intent: str | None, version: str | None = None) -> TaskProfile | None:
    profile = PROFILES.get(intent) if intent else None
    # The current small platform ships one active version per task.  Keeping
    # the parameter makes the persisted version explicit and future-proof.
    if profile and version and profile.version != version:
        return profile
    return profile


_NONE_WORDS = ("没有", "无", "都可以", "都行", "不忌口", "不过敏", "没有忌口")
_UNKNOWN_WORDS = {"不知道", "不清楚", "不确定", "没想好", "还不知道", "不太清楚"}
_REFUSAL_WORDS = ("不想回答", "不方便回答", "拒绝回答", "不回答", "跳过这个", "不愿意说")
_CONFIRM_WORDS = ("确认", "确定", "可以", "好的", "好", "继续", "没问题")
_CANCEL_WORDS = ("取消", "不要", "算了", "不需要")


def _clean(value: str) -> str:
    value = re.sub(r"^(请问|请|帮我|查询|查一下|查|想知道|告诉我|看一下)\s*", "", value)
    return value.strip(" ，。！？?的")


def _is_unknown_answer(text: str) -> bool:
    normalized = text.strip().strip("，。！？? ")
    return normalized in _UNKNOWN_WORDS or any(word in normalized for word in _UNKNOWN_WORDS)


def _is_refusal(text: str) -> bool:
    normalized = text.strip().strip("，。！？? ")
    return any(word in normalized for word in _REFUSAL_WORDS)


def _is_confirmation(text: str) -> bool:
    normalized = text.strip().strip("，。！？? ")
    return normalized in _CONFIRM_WORDS


def _is_cancellation(text: str) -> bool:
    normalized = text.strip().strip("，。！？? ")
    return normalized in _CANCEL_WORDS


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


def _extract_date(text: str) -> str | None:
    match = re.search(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})日?", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def _extract_raw(field: FieldSpec, text: str) -> tuple[Any | None, float, str]:
    known = _known_value(field, text)
    if known is not None:
        return known, 0.99, text.strip()
    if field.name == "food":
        value = _extract_food(text)
        return value, 0.92 if value else 0.0, text.strip()
    if field.name == "amount":
        value = _extract_amount(text)
        return value, 0.97 if value else 0.0, text.strip()
    if field.field_type == "number":
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if match:
            raw = float(match.group(0))
            return (int(raw) if raw.is_integer() else raw), 0.96, match.group(0)
    if field.field_type == "date":
        value = _extract_date(text)
        return value, 0.96 if value else 0.0, text.strip()
    if field.field_type == "boolean":
        if any(word in text for word in ("否", "不需要", "不要", "没有")):
            return False, 0.95, text.strip()
        if any(word in text for word in ("是", "需要", "要", "有")):
            return True, 0.95, text.strip()
    if field.name == "servings":
        match = re.search(r"(\d+)\s*(人|份)", text)
        if match:
            return int(match.group(1)), 0.96, match.group(0)
    if field.name == "cooking_time":
        match = re.search(r"(\d+)\s*分钟", text)
        if match:
            return f"{match.group(1)}分钟内", 0.96, match.group(0)
    return None, 0.0, ""


def _validate_value(field: FieldSpec, value: Any) -> str | None:
    if value is None:
        return "不能为空"
    if field.field_type == "enum" and str(value) not in field.known_values:
        return f"必须是预设选项之一：{'、'.join(field.known_values.values())}"
    if field.field_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return "必须是有效数字"
        if field.min_value is not None and value < field.min_value:
            return f"不能小于 {field.min_value}"
        if field.max_value is not None and value > field.max_value:
            return f"不能大于 {field.max_value}"
    if field.field_type == "date":
        try:
            date.fromisoformat(str(value))
        except ValueError:
            return "必须是有效日期"
    if field.field_type == "boolean" and not isinstance(value, bool):
        return "必须回答是或否"
    if field.field_type == "text":
        if not isinstance(value, str) or not value.strip():
            return "必须是非空文本"
        if field.max_length is not None and len(value) > field.max_length:
            return f"长度不能超过 {field.max_length} 个字符"
    return None


def _extract_for_profile(
    profile: TaskProfile,
    field: FieldSpec,
    text: str,
    *,
    allow_free_text_fallback: bool = False,
    strict: bool = False,
) -> _Extraction:
    if _is_unknown_answer(text):
        return _Extraction(
            unknown=True,
            issue=ValidationIssue(code="unknown_answer", field=field.name, message=f"尚未确定{field.description}。"),
        )
    if _is_refusal(text):
        return _Extraction(refused=True)

    value, confidence, evidence = _extract_raw(field, text)
    if value is None and allow_free_text_fallback and field.allow_free_text and text.strip():
        value, confidence, evidence = text.strip(), 0.82, text.strip()
    if value is None:
        if strict and text.strip() and field.field_type in {"enum", "number", "date", "boolean"}:
            return _Extraction(
                issue=ValidationIssue(code="invalid_value", field=field.name, message=f"无法识别有效的{field.description}。")
            )
        return _Extraction()
    error = _validate_value(field, value)
    if error:
        return _Extraction(
            issue=ValidationIssue(code="invalid_value", field=field.name, message=f"{field.description}{error}。")
        )
    threshold = max(field.confidence_threshold, profile.confidence_threshold)
    if confidence < threshold:
        return _Extraction(
            issue=ValidationIssue(code="low_confidence", field=field.name, message=f"{field.description}识别置信度不足，请再明确一些。")
        )
    for rule in profile.conflicts:
        if rule.field != field.name:
            continue
        has_exclusive = any(str(value) == str(item) or str(item).lower() in text.lower() for item in rule.exclusive_values)
        normalized = text.strip().strip("，。！？? ")
        conflict_text = text.lower()
        for no_phrase in (
            "没有过敏或忌口",
            "没有过敏和忌口",
            "没有过敏",
            "没有忌口",
            "不忌口",
            "不过敏",
            "无过敏",
            "无忌口",
        ):
            conflict_text = conflict_text.replace(no_phrase, "")
        has_conflict = normalized not in _NONE_WORDS and any(pattern.lower() in conflict_text for pattern in rule.conflict_patterns)
        if has_exclusive and has_conflict:
            return _Extraction(issue=ValidationIssue(code="conflict", field=field.name, message=rule.message))
    return _Extraction(value=value, confidence=confidence, evidence=evidence)


def extract_for_field(field: FieldSpec, text: str) -> Any | None:
    """Backward-compatible single-field extraction helper."""

    value, _, _ = _extract_raw(field, text)
    if value is None and field.allow_free_text and text.strip() and not _is_unknown_answer(text):
        return text.strip()
    return value


def extract_fields(profile: TaskProfile, text: str) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    for field in profile.fields:
        extraction = _extract_for_profile(profile, field, text)
        if extraction.value is not None and extraction.issue is None:
            extracted[field.name] = extraction.value
    return extracted


def field_label(field: FieldSpec | None, value: Any) -> str:
    if field is None:
        return str(value)
    return field.known_values.get(str(value), str(value))


def detect_task_intents(text: str, profiles: dict[str, TaskProfile] | None = None) -> list[str]:
    """Detect the minimal supported multi-task shape without an LLM call."""

    available = profiles or PROFILES
    intents: list[str] = []
    if "meal_planner" in available and any(marker in text for marker in ("安排", "规划", "餐食", "吃什么", "菜单")):
        intents.append("meal_planner")
    if "calorie_query" in available and any(marker in text for marker in ("热量", "卡路里", "多少卡")):
        intents.append("calorie_query")
    return intents


class GrillEngine:
    """Ask only for information that blocks a useful and safe answer."""

    def process(
        self,
        profile: TaskProfile,
        user_input: str,
        context: dict[str, Any] | GrillContext | None = None,
        *,
        current_intent: str | None = None,
        operation: str | None = None,
    ) -> GrillResult:
        ctx = GrillContext.from_value(context)
        switched_from: str | None = None
        if ctx.status == "completed" or (ctx.intent and current_intent and ctx.intent != current_intent):
            switched_from = ctx.intent if ctx.intent != profile.task_type else None
            ctx = GrillContext(previous_intent=switched_from)
        elif ctx.status == "awaiting_confirmation":
            if _is_confirmation(user_input):
                ctx.status = "completed"
                ctx.profile_version = profile.version
                return self._execute_result(profile, ctx, reason="confirmed")
            if _is_cancellation(user_input):
                return self._reject(profile, ctx, "用户取消了本次任务。", reason="user_cancelled")
            return self._confirmation_result(profile, ctx)
        elif ctx.status in {"fallback", "rejected"}:
            ctx.status = "collecting"

        if ctx.intent is None:
            ctx.intent = profile.task_type
        ctx.profile_version = profile.version
        ctx.active_task = profile.task_type
        ctx.operation = operation or ctx.operation

        operation_spec = profile.operations.get(operation) if operation else None
        if operation_spec and not operation_spec.requires_grill:
            ctx.status = "completed"
            ctx.pending_field = None
            return self._result(profile, ctx, action="advise", reason="operation_does_not_require_grill")
        for field in profile.fields:
            if field.name in ctx.fields and field.name not in ctx.field_states:
                self._store_value(
                    ctx,
                    field,
                    ctx.fields[field.name],
                    ctx.sources.get(field.name, "inferred"),
                    0.9,
                    "persisted_context",
                )
        ctx.status = "collecting"
        ctx.total_rounds += 1
        ctx.validation_errors = []

        detected_tasks = detect_task_intents(user_input)
        if len(detected_tasks) > 1 and profile.task_type in detected_tasks and not ctx.task_queue:
            ctx.task_queue = detected_tasks

        pending_field = ctx.pending_field
        if pending_field:
            target = profile.field(pending_field)
            if target:
                target_result = _extract_for_profile(
                    profile,
                    target,
                    user_input,
                    allow_free_text_fallback=True,
                    strict=True,
                )
                outcome = self._apply_extraction(ctx, target, target_result, user_input)
                if outcome == "refused":
                    if target.refusal_allowed or profile.refusal_policy == "default":
                        ctx.refused_fields.append(target.name)
                        ctx.pending_field = None
                    else:
                        return self._reject(
                            profile,
                            ctx,
                            f"为了避免猜错，{target.description}不能在未确认的情况下跳过。",
                            reason="required_field_refused",
                            target_field=target.name,
                        )
                elif outcome in {"invalid", "unknown", "conflict"}:
                    if target_result.issue:
                        ctx.validation_errors.append(target_result.issue)
                    if outcome == "conflict":
                        ctx.conflict_fields.append(target.name)
                    if outcome != "unknown":
                        return self._clarify(
                            profile,
                            ctx,
                            target,
                            reason=target_result.issue.code if target_result.issue else "invalid_value",
                            issues=ctx.validation_errors,
                        )

        for field in profile.fields:
            if field.name == pending_field:
                continue
            extraction = _extract_for_profile(profile, field, user_input)
            if extraction.issue:
                if extraction.issue.code in {"invalid_value", "conflict"}:
                    ctx.validation_errors.append(extraction.issue)
                continue
            if extraction.value is not None and (field.name not in ctx.fields or pending_field == field.name):
                self._store_value(ctx, field, extraction.value, "user", extraction.confidence, extraction.evidence)

        required_fields = self._required_fields(profile, ctx, operation=operation)
        missing_required = [field for field in required_fields if not self._exists(ctx.fields.get(field.name))]
        if missing_required:
            if ctx.total_rounds > profile.max_total_rounds:
                return self._fallback(profile, ctx, missing_required, reason="max_total_rounds")
            clarification_reason = "required_field_missing"
            if ctx.validation_errors and ctx.validation_errors[-1].code in {
                "invalid_value",
                "conflict",
                "low_confidence",
            }:
                clarification_reason = ctx.validation_errors[-1].code
            return self._clarify(
                profile,
                ctx,
                missing_required[0],
                reason=clarification_reason,
                issues=ctx.validation_errors,
                switched_from=switched_from,
            )

        dependency_issues = self._dependency_issues(profile, ctx)
        if dependency_issues:
            ctx.validation_errors.extend(dependency_issues)
            field = profile.field(dependency_issues[0].field)
            if field:
                return self._clarify(profile, ctx, field, reason="dependency", issues=ctx.validation_errors)

        assumptions: list[str] = []
        for field in profile.fields:
            if field.name not in ctx.fields and field.has_default:
                error = _validate_value(field, field.default_value)
                if error:
                    ctx.validation_errors.append(
                        ValidationIssue(code="invalid_value", field=field.name, message=f"默认值无效：{error}。")
                    )
                    continue
                self._store_value(ctx, field, field.default_value, "default", 0.75, "profile.default_value")
                assumptions.append(f"{field.description}按“{field_label(field, field.default_value)}”处理")
        ctx.pending_field = None
        if profile.confirmation_required:
            ctx.status = "awaiting_confirmation"
            return self._confirmation_result(profile, ctx, assumptions=assumptions, reason="ready_for_confirmation")
        return self._execute_result(profile, ctx, assumptions=assumptions, reason="intent_switched" if switched_from else "ready")

    def _apply_extraction(self, ctx: GrillContext, field: FieldSpec, extraction: _Extraction, evidence: str) -> str:
        if extraction.refused:
            return "refused"
        if extraction.unknown:
            return "unknown"
        if extraction.issue:
            return "conflict" if extraction.issue.code == "conflict" else "invalid"
        if extraction.value is not None:
            self._store_value(ctx, field, extraction.value, "user", extraction.confidence, extraction.evidence or evidence)
            ctx.pending_field = None
            return "valid"
        return "unmatched"

    @staticmethod
    def _store_value(ctx: GrillContext, field: FieldSpec, value: Any, source: FieldSource, confidence: float, evidence: str) -> None:
        ctx.fields[field.name] = value
        ctx.sources[field.name] = source
        ctx.field_states[field.name] = FieldState(source=source, confidence=confidence, evidence=evidence)

    @staticmethod
    def _required_fields(
        profile: TaskProfile,
        ctx: GrillContext,
        *,
        operation: str | None = None,
    ) -> list[FieldSpec]:
        operation_spec = profile.operations.get(operation) if operation else None
        required_names = (
            list(operation_spec.required_fields)
            if operation_spec is not None and operation_spec.required_fields
            else [field.name for field in profile.fields if field.priority == "critical"]
        )
        for rule in profile.dependencies:
            if GrillEngine._matches_when(rule.when, ctx.fields):
                for name in rule.require:
                    if name not in required_names:
                        required_names.append(name)
        return [field for field in profile.fields if field.name in required_names]

    @staticmethod
    def _matches_when(when: dict[str, Any], fields: dict[str, Any]) -> bool:
        for name, expected in when.items():
            actual = fields.get(name)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True

    @staticmethod
    def _dependency_issues(profile: TaskProfile, ctx: GrillContext) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for rule in profile.dependencies:
            if not GrillEngine._matches_when(rule.when, ctx.fields):
                continue
            for name in rule.require:
                if not GrillEngine._exists(ctx.fields.get(name)):
                    field = profile.field(name)
                    issues.append(
                        ValidationIssue(
                            code="dependency",
                            field=name,
                            message=rule.message or f"{field.description if field else name}依赖其他已确认信息。",
                        )
                    )
        return issues

    def _clarify(
        self,
        profile: TaskProfile,
        ctx: GrillContext,
        field: FieldSpec,
        *,
        reason: str,
        issues: list[ValidationIssue] | None = None,
        switched_from: str | None = None,
    ) -> GrillResult:
        if ctx.clarification_count >= profile.max_clarifications:
            return self._fallback(profile, ctx, [field], reason="max_clarifications")
        ctx.clarification_count += 1
        ctx.pending_field = field.name
        if field.name not in ctx.asked_fields:
            ctx.asked_fields.append(field.name)
        question = field.question or f"请补充你的{field.description}。"
        if reason in {"invalid_value", "unknown_answer", "conflict", "dependency", "low_confidence"} and issues:
            question = f"{issues[-1].message} {question}"
        ctx.last_question = question
        candidates = [Candidate(label=label, value=value) for value, label in field.known_values.items()][
            : profile.candidate_count
        ]
        return self._result(
            profile,
            ctx,
            action="clarify",
            message=question,
            question=question,
            target_field=field.name,
            candidates=candidates,
            missing_fields=[field.name],
            confidence=0.98,
            reason="intent_switched" if switched_from else reason,
            issues=issues or [],
        )

    def _fallback(self, profile: TaskProfile, ctx: GrillContext, missing_fields: list[FieldSpec], *, reason: str) -> GrillResult:
        missing = [item.description for item in missing_fields]
        ctx.status = "fallback"
        ctx.pending_field = missing_fields[0].name if missing_fields else None
        message = f"为了避免猜错，我还需要这些信息：{'、'.join(missing)}。请尽量一次性补充。"
        return self._result(
            profile,
            ctx,
            action="fallback",
            message=message,
            target_field=ctx.pending_field,
            missing_fields=[item.name for item in missing_fields],
            confidence=0.99,
            reason=reason,
            issues=ctx.validation_errors,
        )

    def _reject(self, profile: TaskProfile, ctx: GrillContext, message: str, *, reason: str, target_field: str | None = None) -> GrillResult:
        ctx.status = "rejected"
        return self._result(
            profile,
            ctx,
            action="reject",
            message=message,
            target_field=target_field or ctx.pending_field,
            confidence=0.99,
            reason=reason,
            issues=ctx.validation_errors,
        )

    def _confirmation_result(
        self,
        profile: TaskProfile,
        ctx: GrillContext,
        *,
        assumptions: list[str] | None = None,
        reason: str = "confirmation_required",
    ) -> GrillResult:
        summary = "、".join(
            f"{field.description}={field_label(field, ctx.fields.get(field.name))}"
            for field in profile.fields
            if field.name in ctx.fields
        )
        message = f"信息已经足够（{summary}），请回复“确认”后继续。"
        return self._result(
            profile,
            ctx,
            action="pending_confirmation",
            message=message,
            question=message,
            assumptions=assumptions or [],
            confidence=self._context_confidence(profile, ctx),
            reason=reason,
        )

    def _execute_result(
        self,
        profile: TaskProfile,
        ctx: GrillContext,
        *,
        assumptions: list[str] | None = None,
        reason: str,
    ) -> GrillResult:
        ctx.status = "completed"
        return self._result(
            profile,
            ctx,
            action="execute",
            assumptions=assumptions or [],
            confidence=self._context_confidence(profile, ctx),
            reason=reason,
        )

    def _result(self, profile: TaskProfile, ctx: GrillContext, *, action: GrillAction, **kwargs: Any) -> GrillResult:
        return GrillResult(
            action=action,
            task=profile.task_type,
            operation=ctx.operation,
            profile_version=profile.version,
            context=ctx,
            task_queue=ctx.task_queue,
            **kwargs,
        )

    @staticmethod
    def _context_confidence(profile: TaskProfile, ctx: GrillContext) -> float:
        values: list[float] = []
        for field in GrillEngine._required_fields(profile, ctx, operation=ctx.operation):
            state = ctx.field_states.get(field.name)
            if state:
                values.append(state.confidence)
        return min(values, default=0.0)

    @staticmethod
    def _exists(value: Any) -> bool:
        return value is not None and (not isinstance(value, str) or bool(value.strip()))
