"""User-facing conversation experience contracts for the small platform."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExperienceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    show_model_info: bool = True
    show_sources: bool = True
    show_safety_details: bool = True
    answer_style: Literal["concise", "standard", "detailed"] = "standard"
    pinned_shortcuts: list[str] = Field(default_factory=list, max_length=12)


class ConversationActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["skip", "revise", "restart"]
    field: str | None = Field(default=None, max_length=64)


SHORTCUTS: tuple[dict[str, str], ...] = (
    {
        "id": "weight_control",
        "label": "减脂建议",
        "prompt": "我想获得减脂方面的通用建议",
    },
    {
        "id": "muscle_gain",
        "label": "增肌建议",
        "prompt": "我想获得增肌方面的通用建议",
    },
    {
        "id": "balanced_diet",
        "label": "均衡饮食",
        "prompt": "我想改善饮食均衡，请给我一些通用建议",
    },
    {
        "id": "calorie_query",
        "label": "查询热量",
        "prompt": "我想查询一种食物的热量",
    },
    {
        "id": "meal_planner",
        "label": "制定餐食",
        "prompt": "请帮我制定餐食计划",
    },
)


def list_shortcuts(pinned: list[str] | None = None) -> list[dict[str, str | bool]]:
    pinned_ids = set(pinned or [])
    return [{**item, "pinned": item["id"] in pinned_ids} for item in SHORTCUTS]
