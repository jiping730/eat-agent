from pathlib import Path

import pytest

from core.intent_router import RequestIntent
from core.persistence import ConversationStore
from core.profile import ProfileService, UserProfileUpdate
from core.workflow import create_workflow


def test_profile_requires_consent_and_supports_update_export_delete(tmp_path: Path):
    store = ConversationStore(database_url=f"sqlite:///{tmp_path / 'profile.db'}")
    service = ProfileService(store)

    with pytest.raises(ValueError, match="授权"):
        service.update(
            "user-a",
            UserProfileUpdate(height_cm=170, health_goal="weight_control"),
        )

    saved = service.update(
        "user-a",
        UserProfileUpdate(
            height_cm=170,
            weight_kg=75,
            target_weight_kg=65,
            sex="prefer_not_to_say",
            activity_level="sedentary",
            health_goal="weight_control",
            allergies=["花生"],
            consent_granted=True,
        ),
    )
    assert saved["consent_granted"] is True
    assert saved["profile"]["allergies"] == ["花生"]
    assert service.workflow_context("user-a")["fields"] == {
        "health_goal": "weight_control",
        "allergy_info": "花生",
    }
    assert service.get("user-b")["consent_granted"] is False

    deleted = service.delete("user-a")
    assert deleted["consent_granted"] is False
    assert deleted["profile"]["height_cm"] is None
    assert deleted["profile"]["sex"] is None
    assert deleted["profile"]["allergies"] == []
    assert service.workflow_context("user-a") == {}
    store.engine.dispose()


class _Memory:
    def retrieve_relevant_memories(self, *_args, **_kwargs):
        return []

    def add_interaction(self, *_args, **_kwargs):
        return None

    def save_meta(self, *_args, **_kwargs):
        return None


def _workflow_state(user_profile):
    return {
        "messages": [{"role": "user", "content": "那帮我安排一顿餐食"}],
        "user_id": "profile-user",
        "memory_context": [],
        "user_profile": user_profile,
        "current_goal": "",
        "current_operation": "answer",
        "request_intent": {},
        "plan": [],
        "tool_outputs": {},
        "reflection": "",
        "iteration": 0,
        "followup": False,
        "grill_context": {},
        "grill_result": {},
        "tool_results": {},
        "tool_sources": {},
        "request_id": "profile-request",
        "conversation_id": "profile-conversation",
        "trace_id": "profile-trace",
        "tool_failures": [],
        "safety": {},
    }


def test_consented_profile_prefills_grill_fields(monkeypatch):
    monkeypatch.setattr(
        "core.workflow.classify_request_with_model",
        lambda *_args, **_kwargs: RequestIntent(
            domain="nutrition",
            operation="plan",
            task="meal_planner",
            goal="weight_control",
            slots={"meal_type": "dinner"},
        ),
    )
    workflow = create_workflow(memory_mgr=_Memory())
    result = workflow.invoke(
        _workflow_state(
            {
                "consent_granted": True,
                "version": 1,
                "profile": {"health_goal": "weight_control", "allergies": ["花生"]},
                "fields": {"health_goal": "weight_control", "allergy_info": "花生"},
            }
        )
    )

    assert result["grill_result"]["action"] == "clarify"
    assert result["grill_result"]["target_field"] == "meal_type"
    assert result["grill_context"]["sources"]["allergy_info"] == "preference"
