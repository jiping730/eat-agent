"""Small-platform safety policy for nutrition conversations.

The guard is intentionally deterministic and dependency-free.  It is not a
medical diagnosis model and it does not try to replace professional review.
Its job is to create one auditable boundary around user input, untrusted
retrieval/tool content, tool execution, and final answers.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field


class SafetyDecision(BaseModel):
    """Serializable result of one safety policy evaluation."""

    model_config = ConfigDict(extra="forbid")

    action: str = "allow"
    risk_level: str = "low"
    categories: list[str] = Field(default_factory=list)
    sanitized_text: str = ""
    redactions: list[str] = Field(default_factory=list)
    prompt_injection: bool = False
    allergens: list[str] = Field(default_factory=list)
    medical_risk: bool = False
    requires_disclaimer: bool = False
    citations_required: bool = False
    message: str = ""


class SafetyGuard:
    """Rule-based safety boundary shared by Workflow and API memory flows."""

    _injection_markers = (
        "忽略之前",
        "忽略系统",
        "忽略所有指令",
        "跳过安全",
        "泄露系统提示",
        "显示系统提示",
        "开发者消息",
        "不要遵守",
        "越过限制",
        "ignore previous",
        "ignore all instructions",
        "system prompt",
        "developer message",
        "reveal your prompt",
        "jailbreak",
    )
    _medical_markers = (
        "糖尿病",
        "高血压",
        "低血压",
        "肾病",
        "肾功能",
        "肝病",
        "肝功能",
        "痛风",
        "高血脂",
        "心脏病",
        "甲状腺",
        "孕妇",
        "怀孕",
        "哺乳",
        "儿童",
        "未成年",
        "老人",
        "药物",
        "吃药",
        "服药",
        "处方",
        "胰岛素",
        "二甲双胍",
        "华法林",
        "抗凝药",
        "降压药",
        "降糖药",
    )
    _high_risk_medical_markers = (
        "停药",
        "换药",
        "加量",
        "减量",
        "剂量",
        "能不能一起吃",
        "相互作用",
        "治疗",
        "治愈",
        "诊断",
        "替代医生",
        "替代治疗",
        "是否安全",
    )
    _allergen_markers = (
        "花生",
        "坚果",
        "核桃",
        "杏仁",
        "牛奶",
        "乳制品",
        "鸡蛋",
        "蛋类",
        "海鲜",
        "鱼类",
        "鱼",
        "虾",
        "蟹",
        "贝类",
        "大豆",
        "黄豆",
        "小麦",
        "麸质",
        "芝麻",
    )
    _numeric_nutrition_pattern = re.compile(
        r"(?:\d+(?:\.\d+)?\s*(?:千卡|大卡|kcal|卡路里|克|g|毫克|mg|公斤|kg|%))",
        re.IGNORECASE,
    )
    _redaction_patterns: tuple[tuple[str, re.Pattern[str], str], ...] = (
        ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "手机号"),
        (
            "email",
            re.compile(
                r"(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![A-Z0-9._%+-])",
                re.IGNORECASE,
            ),
            "邮箱",
        ),
        (
            "id_card",
            re.compile(r"(?<!\d)(?:\d{17}[\dXx]|\d{15})(?!\d)"),
            "身份证号",
        ),
        ("secret", re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_-]{16,}\b"), "密钥"),
        ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b", re.IGNORECASE), "访问令牌"),
        ("bank_card", re.compile(r"(?<!\d)\d{12,19}(?!\d)"), "银行卡号"),
    )

    _medical_disclaimer = (
        "⚠️ 医疗安全提示：这里只能提供一般性营养信息，不能替代医生诊断、处方或用药指导。"
        "如涉及疾病、孕哺期、儿童、药物剂量或相互作用，请先咨询医生或注册营养师。"
    )
    _allergy_disclaimer = (
        "⚠️ 过敏原强提醒：请以食品包装的完整配料表和交叉污染标识为准；严重过敏时不要仅凭本建议试吃，"
        "必要时咨询专业人士。"
    )
    _citation_disclaimer = "⚠️ 数据来源提示：回答中的具体营养数值暂未取得可核验来源，请以食品包装标签、官方数据库或专业人士提供的数据为准。"

    @classmethod
    def redact(cls, text: str) -> tuple[str, list[str]]:
        """Redact common secrets and direct identifiers before persistence."""

        sanitized = text or ""
        redactions: list[str] = []
        for code, pattern, label in cls._redaction_patterns:
            if pattern.search(sanitized):
                sanitized = pattern.sub(f"[已脱敏{label}]", sanitized)
                redactions.append(code)
        return sanitized, redactions

    @classmethod
    def _contains_any(cls, text: str, markers: Iterable[str]) -> bool:
        normalized = (text or "").lower()
        return any(marker.lower() in normalized for marker in markers)

    @classmethod
    def _allergens(cls, text: str) -> list[str]:
        return list(dict.fromkeys(marker for marker in cls._allergen_markers if marker in (text or "")))

    @classmethod
    def inspect_user_input(cls, text: str) -> SafetyDecision:
        sanitized, redactions = cls.redact(text or "")
        injection = cls._contains_any(text, cls._injection_markers)
        medical = cls._contains_any(text, cls._medical_markers)
        high_risk_medical = medical and cls._contains_any(text, cls._high_risk_medical_markers)
        allergens = cls._allergens(text)
        categories: list[str] = []
        if injection:
            categories.append("prompt_injection")
        if redactions:
            categories.append("sensitive_data")
        if allergens:
            categories.append("allergen")
        if medical:
            categories.append("medical_context")

        if high_risk_medical:
            return cls._decision(
                action="escalate",
                risk_level="high",
                categories=categories,
                sanitized_text=sanitized,
                redactions=redactions,
                prompt_injection=injection,
                allergens=allergens,
                medical_risk=True,
                requires_disclaimer=True,
                message=cls._medical_disclaimer,
            )
        if injection:
            # Injection is treated as untrusted text.  It is not a reason to
            # reject a normal question, but it must never authorize a tool.
            return cls._decision(
                action="warn",
                risk_level="medium",
                categories=categories,
                sanitized_text=sanitized,
                redactions=redactions,
                prompt_injection=True,
                allergens=allergens,
                medical_risk=medical,
                requires_disclaimer=medical,
                message="检测到疑似指令注入内容，已将其作为普通文本处理，不会据此执行隐藏指令。",
            )
        return cls._decision(
            action="sanitize" if redactions else ("warn" if allergens or medical else "allow"),
            risk_level="medium" if allergens or medical else "low",
            categories=categories,
            sanitized_text=sanitized,
            redactions=redactions,
            allergens=allergens,
            medical_risk=medical,
            requires_disclaimer=medical,
            message=cls._allergy_disclaimer if allergens else (cls._medical_disclaimer if medical else ""),
        )

    @classmethod
    def inspect_untrusted_content(cls, content: str) -> SafetyDecision:
        """Detect instruction-like text in retrieved or MCP content."""

        sanitized, redactions = cls.redact(content or "")
        injection = cls._contains_any(content, cls._injection_markers)
        if injection:
            # Keep evidence as data but isolate instruction-looking lines from
            # the answer prompt.  The caller still records the detection.
            lines = []
            for line in sanitized.splitlines():
                if cls._contains_any(line, cls._injection_markers):
                    lines.append("[已隔离不可信指令片段]")
                else:
                    lines.append(line)
            sanitized = "\n".join(lines)
        return cls._decision(
            action="warn" if injection else ("sanitize" if redactions else "allow"),
            risk_level="medium" if injection else "low",
            categories=["prompt_injection"] if injection else (["sensitive_data"] if redactions else []),
            sanitized_text=sanitized,
            redactions=redactions,
            prompt_injection=injection,
            message="检索或工具内容包含指令样式文本，已按不可信数据隔离。" if injection else "",
        )

    @classmethod
    def check_tool_call(
        cls, user_text: str, tool_name: str, context: Mapping[str, Any] | None = None
    ) -> SafetyDecision:
        """Run the pre-tool gate.  A tool never receives a high-risk request."""

        decision = cls.inspect_user_input(user_text)
        if decision.prompt_injection:
            return decision.model_copy(
                update={
                    "action": "block",
                    "risk_level": "high",
                    "message": f"已阻止由不可信指令触发的工具调用（{tool_name}）。",
                }
            )
        if decision.action == "escalate":
            return decision.model_copy(update={"action": "block"})
        return decision

    @classmethod
    def validate_output(
        cls,
        answer: str,
        *,
        input_decision: Mapping[str, Any] | SafetyDecision | None = None,
        request_intent: Mapping[str, Any] | None = None,
        grill_context: Mapping[str, Any] | None = None,
        sources: Iterable[Mapping[str, Any]] | None = None,
    ) -> SafetyDecision:
        """Sanitize and validate final text before it reaches the user."""

        sanitized, redactions = cls.redact(answer or "")
        source_list = list(sources or [])
        intent = dict(request_intent or {})
        context = dict(grill_context or {})
        input_payload = (
            input_decision.model_dump(mode="json")
            if isinstance(input_decision, SafetyDecision)
            else dict(input_decision or {})
        )
        allergens = list(input_payload.get("allergens") or [])
        fields = context.get("fields") or {}
        allergy_value = str(fields.get("allergy_info") or fields.get("dietary_restrictions") or "")
        if allergy_value and allergy_value.lower() not in {"none", "无", "没有", "无忌口"}:
            allergens = list(dict.fromkeys([*allergens, *cls._allergens(allergy_value)]))

        categories: list[str] = []
        if redactions:
            categories.append("sensitive_data")
        medical = bool(input_payload.get("medical_risk")) or cls._contains_any(
            answer, cls._medical_markers + cls._high_risk_medical_markers
        )
        if medical:
            categories.append("medical_context")
        domain = str(intent.get("domain") or "")
        task = str(intent.get("task") or "")
        nutrition_context = domain == "nutrition" or task in {"calorie_query", "meal_planner"}
        numeric_nutrition = nutrition_context and bool(cls._numeric_nutrition_pattern.search(sanitized))
        if numeric_nutrition:
            categories.append("nutrition_fact")

        conflicting_allergens = [item for item in allergens if item and item in sanitized]
        if conflicting_allergens:
            categories.append("allergen_conflict")
            sanitized = (
                "我检测到回答内容涉及你标记的过敏原（"
                + "、".join(conflicting_allergens)
                + "），因此没有直接推荐该内容。请改用明确不含相关过敏原的方案，并核对配料表。\n"
                + cls._allergy_disclaimer
            )
            return cls._decision(
                action="block",
                risk_level="high",
                categories=categories,
                sanitized_text=sanitized,
                redactions=redactions,
                allergens=allergens,
                medical_risk=medical,
                requires_disclaimer=True,
                message=cls._allergy_disclaimer,
            )

        if medical and cls._medical_disclaimer not in sanitized:
            sanitized = f"{sanitized}\n\n{cls._medical_disclaimer}".strip()
        if numeric_nutrition:
            if source_list:
                if "来源：" not in sanitized and "参考来源：" not in sanitized:
                    references = "、".join(
                        str(item.get("title") or item.get("source") or item.get("uri") or "知识库")
                        for item in source_list[:3]
                    )
                    sanitized = f"{sanitized}\n\n参考来源：{references}".strip()
            elif cls._citation_disclaimer not in sanitized:
                sanitized = f"{sanitized}\n\n{cls._citation_disclaimer}".strip()

        action = "citation_required" if numeric_nutrition and not source_list else ("warn" if categories else "allow")
        return cls._decision(
            action=action,
            risk_level="medium" if categories else "low",
            categories=categories,
            sanitized_text=sanitized,
            redactions=redactions,
            allergens=allergens,
            medical_risk=medical,
            requires_disclaimer=medical,
            citations_required=numeric_nutrition,
            message=cls._citation_disclaimer if numeric_nutrition and not source_list else "",
        )

    @staticmethod
    def _decision(**kwargs: Any) -> SafetyDecision:
        return SafetyDecision(**kwargs)


def safety_summary(decision: SafetyDecision | Mapping[str, Any]) -> dict[str, Any]:
    """Return the small public subset safe to expose in API responses/logs."""

    payload = decision.model_dump(mode="json") if isinstance(decision, SafetyDecision) else dict(decision)
    return {
        "action": payload.get("action", "allow"),
        "risk_level": payload.get("risk_level", "low"),
        "categories": list(payload.get("categories") or []),
        "redactions": list(payload.get("redactions") or []),
        "prompt_injection": bool(payload.get("prompt_injection", False)),
        "allergens": list(payload.get("allergens") or []),
        "requires_disclaimer": bool(payload.get("requires_disclaimer", False)),
        "citations_required": bool(payload.get("citations_required", False)),
        "message": payload.get("message", ""),
    }
