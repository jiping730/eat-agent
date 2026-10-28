"""Explicit personal profile management for the small platform.

The profile is deliberately separate from conversation state and episodic
memory.  It is only loaded into the workflow after explicit user consent.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.persistence import ConversationStore


Sex = Literal["female", "male", "other", "prefer_not_to_say"]
ActivityLevel = Literal["sedentary", "light", "moderate", "high"]
HealthGoal = Literal["weight_control", "muscle_gain", "balanced_diet", "maintain"]


class UserProfileData(BaseModel):
    """Validated long-term nutrition preferences owned by one user."""

    model_config = ConfigDict(extra="forbid")

    height_cm: float | None = Field(default=None, ge=80, le=250)
    weight_kg: float | None = Field(default=None, ge=20, le=500)
    target_weight_kg: float | None = Field(default=None, ge=20, le=500)
    age: int | None = Field(default=None, ge=13, le=120)
    sex: Sex | None = None
    activity_level: ActivityLevel | None = None
    health_goal: HealthGoal | None = None
    allergies: list[str] = Field(default_factory=list, max_length=20)
    dietary_preferences: list[str] = Field(default_factory=list, max_length=20)
    disliked_foods: list[str] = Field(default_factory=list, max_length=50)
    common_ingredients: list[str] = Field(default_factory=list, max_length=50)
    meals_per_day: int | None = Field(default=None, ge=1, le=8)
    daily_budget: float | None = Field(default=None, ge=0, le=100_000)


class UserProfileUpdate(UserProfileData):
    """PUT payload; omitted fields preserve the current profile."""

    consent_granted: bool | None = None


class ProfileConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    granted: bool


class ProfileSuggestion(BaseModel):
    """A safe, user-confirmable candidate for the long-term profile."""

    id: str
    field: str
    value: Any
    label: str
    confidence: float
    status: str = "pending"
    message: str = "是否保存到你的个人档案？"


class ProfileService:
    """Validate profile writes and expose consent-aware workflow context."""

    def __init__(self, store: ConversationStore) -> None:
        self.store = store

    def get(self, user_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        return self.store.export_user_profile(user_id, tenant_id)

    def update(
        self,
        user_id: str,
        payload: UserProfileUpdate,
        *,
        actor: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        current = self.store.export_user_profile(user_id, tenant_id)
        current_profile = UserProfileData.model_validate(current.get("profile") or {})
        changes = payload.model_dump(
            mode="json",
            exclude_unset=True,
            exclude={"consent_granted"},
        )
        merged = current_profile.model_dump(mode="json")
        merged.update(changes)
        consent_granted = (
            payload.consent_granted
            if payload.consent_granted is not None
            else bool(current.get("consent_granted"))
        )
        if changes and not consent_granted:
            raise ValueError("保存个人档案前需要先明确授权并同意使用这些信息")
        if not consent_granted:
            merged = UserProfileData().model_dump(mode="json")
        validated = UserProfileData.model_validate(merged)
        return self.store.save_user_profile(
            user_id=user_id,
            profile=validated.model_dump(mode="json"),
            consent_granted=bool(consent_granted),
            actor=actor or user_id,
            tenant_id=tenant_id,
        )

    def set_consent(
        self, user_id: str, granted: bool, *, actor: str | None = None, tenant_id: str | None = None
    ) -> dict[str, Any]:
        return self.store.set_user_profile_consent(
            user_id, granted, actor=actor or user_id, tenant_id=tenant_id
        )

    def delete(
        self, user_id: str, *, actor: str | None = None, tenant_id: str | None = None
    ) -> dict[str, Any]:
        return self.store.delete_user_profile(user_id, actor=actor or user_id, tenant_id=tenant_id)

    @staticmethod
    def suggest_from_text(text: str) -> list[dict[str, Any]]:
        """Extract only high-confidence, explicit profile candidates.

        This is intentionally deterministic.  P2-2 proposes values to the user;
        it never persists a value merely because the text contains a related
        nutrition word.
        """

        normalized = text.strip()
        if not normalized:
            return []
        suggestions: list[dict[str, Any]] = []
        allergen_labels = {
            "乳糖": "乳糖不耐受",
            "牛奶": "牛奶过敏或不耐受",
            "花生": "花生过敏",
            "坚果": "坚果过敏",
            "海鲜": "海鲜过敏或忌口",
            "鸡蛋": "鸡蛋过敏或忌口",
            "大豆": "大豆过敏或忌口",
            "麸质": "麸质不耐受或忌口",
        }
        for value, label in allergen_labels.items():
            if value in normalized and re.search(r"过敏|不耐受|不能吃|忌口|不吃", normalized):
                suggestions.append(
                    {
                        "field": "allergies",
                        "value": [value],
                        "label": label,
                        "confidence": 0.96,
                    }
                )
                break

        if any(marker in normalized for marker in ("减肥", "减脂", "控制体重")):
            suggestions.append(
                {
                    "field": "health_goal",
                    "value": "weight_control",
                    "label": "控制体重/减脂",
                    "confidence": 0.94,
                }
            )
        elif "增肌" in normalized:
            suggestions.append(
                {
                    "field": "health_goal",
                    "value": "muscle_gain",
                    "label": "增肌",
                    "confidence": 0.94,
                }
            )

        meals_match = re.search(r"(?:每天|每日|一天|一日)\s*(?:吃\s*)?([一二两三四五六七八]|\d{1,2})\s*[顿餐]", normalized)
        if meals_match:
            raw_meals = meals_match.group(1)
            meals_per_day = {
                "一": 1,
                "二": 2,
                "两": 2,
                "三": 3,
                "四": 4,
                "五": 5,
                "六": 6,
                "七": 7,
                "八": 8,
            }.get(raw_meals)
            if meals_per_day is None:
                meals_per_day = int(raw_meals)
            if 1 <= meals_per_day <= 8:
                suggestions.append(
                    {
                        "field": "meals_per_day",
                        "value": meals_per_day,
                        "label": f"每天 {meals_per_day} 餐",
                        "confidence": 0.97,
                    }
                )

        dietary_values = {
            "素食": "素食",
            "纯素": "纯素",
            "低碳": "低碳饮食",
            "清真": "清真饮食",
        }
        for value, label in dietary_values.items():
            if value in normalized:
                suggestions.append(
                    {
                        "field": "dietary_preferences",
                        "value": [value],
                        "label": label,
                        "confidence": 0.92,
                    }
                )
                break
        return suggestions

    def create_suggestions(
        self,
        text: str,
        *,
        user_id: str,
        conversation_id: str | None = None,
        source_message_id: int | None = None,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        current = self.store.export_user_profile(user_id, tenant_id)
        profile = dict(current.get("profile") or {})
        created: list[dict[str, Any]] = []
        for candidate in self.suggest_from_text(text):
            field = candidate["field"]
            value = candidate["value"]
            existing = profile.get(field)
            if isinstance(value, list):
                existing_values = set(existing or []) if isinstance(existing, list) else set()
                if set(value).issubset(existing_values):
                    continue
            elif existing == value:
                continue
            created.append(
                self.store.create_profile_suggestion(
                    user_id=user_id,
                    field_name=field,
                    value=value,
                    label=candidate["label"],
                    confidence=candidate["confidence"],
                    conversation_id=conversation_id,
                    source_message_id=source_message_id,
                    tenant_id=tenant_id,
                )
            )
        return created

    def list_suggestions(self, user_id: str, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_profile_suggestions(user_id, tenant_id=tenant_id)

    def accept_suggestion(
        self, suggestion_id: str, user_id: str, *, actor: str | None = None, tenant_id: str | None = None
    ) -> dict[str, Any]:
        suggestion = self.store.get_profile_suggestion(suggestion_id, user_id, tenant_id)
        if suggestion is None:
            raise KeyError("档案建议不存在")
        if suggestion["status"] != "pending":
            raise ValueError("档案建议已经处理")
        current = self.store.export_user_profile(user_id, tenant_id)
        if not current.get("consent_granted"):
            raise ValueError("请先开启个人档案授权，再保存这条建议")
        field = str(suggestion["field"])
        value = suggestion["value"]
        profile = dict(current.get("profile") or {})
        if field in {"allergies", "dietary_preferences", "disliked_foods", "common_ingredients"}:
            existing = profile.get(field) or []
            merged = list(dict.fromkeys([*existing, *(value if isinstance(value, list) else [value])]))
            value = merged
        payload = UserProfileUpdate.model_validate({field: value, "consent_granted": True})
        updated = self.update(user_id, payload, actor=actor or user_id, tenant_id=tenant_id)
        self.store.update_profile_suggestion_status(suggestion_id, user_id, "accepted", tenant_id)
        return updated

    def dismiss_suggestion(self, suggestion_id: str, user_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        return self.store.update_profile_suggestion_status(suggestion_id, user_id, "dismissed", tenant_id)

    def workflow_context(self, user_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        """Return only consented profile data and Grill-compatible fields."""

        current = self.get(user_id, tenant_id)
        if not current.get("consent_granted"):
            return {}
        profile = dict(current.get("profile") or {})
        grill_fields: dict[str, Any] = {}
        if profile.get("health_goal"):
            grill_fields["health_goal"] = profile["health_goal"]
        allergies = profile.get("allergies") or []
        grill_fields["allergy_info"] = ", ".join(str(item) for item in allergies) if allergies else "none"
        return {
            "version": current.get("version", 0),
            "profile": profile,
            "fields": grill_fields,
            "consent_granted": True,
        }
