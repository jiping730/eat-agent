"""Explicit personal profile management for the small platform.

The profile is deliberately separate from conversation state and episodic
memory.  It is only loaded into the workflow after explicit user consent.
"""

from __future__ import annotations

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


class ProfileService:
    """Validate profile writes and expose consent-aware workflow context."""

    def __init__(self, store: ConversationStore) -> None:
        self.store = store

    def get(self, user_id: str) -> dict[str, Any]:
        return self.store.export_user_profile(user_id)

    def update(self, user_id: str, payload: UserProfileUpdate, *, actor: str | None = None) -> dict[str, Any]:
        current = self.store.export_user_profile(user_id)
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
        )

    def set_consent(self, user_id: str, granted: bool, *, actor: str | None = None) -> dict[str, Any]:
        return self.store.set_user_profile_consent(user_id, granted, actor=actor or user_id)

    def delete(self, user_id: str, *, actor: str | None = None) -> dict[str, Any]:
        return self.store.delete_user_profile(user_id, actor=actor or user_id)

    def workflow_context(self, user_id: str) -> dict[str, Any]:
        """Return only consented profile data and Grill-compatible fields."""

        current = self.get(user_id)
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
