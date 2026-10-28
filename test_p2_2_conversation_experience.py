from pathlib import Path

import pytest

from core.grill_engine import FieldSpec, GrillContext, GrillEngine, OperationSpec, TaskProfile
from core.persistence import ConversationStore
from core.profile import ProfileService, UserProfileUpdate


def _store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(database_url=f"sqlite:///{tmp_path / 'p2-2.db'}")


def test_conversation_search_rename_and_archive_are_scoped(tmp_path: Path):
    store = _store(tmp_path)
    tenant_id = store.get_or_create_personal_tenant("user-1")
    first = store.create_conversation(
        conversation_id="conversation-1", user_id="user-1", tenant_id=tenant_id, title="减脂计划"
    )
    store.create_conversation(
        conversation_id="conversation-2", user_id="user-1", tenant_id=tenant_id, title="热量查询"
    )
    store.save_turn(
        conversation_id=first.id,
        user_id="user-1",
        tenant_id=tenant_id,
        request_id="request-1",
        user_message="我想要一个晚餐计划",
        assistant_message="请补充餐次",
        grill_context={},
        current_goal="meal_planner",
        response_type="clarification",
        target_field="meal_type",
    )

    assert [item.id for item in store.list_conversations("user-1", tenant_id, query_text="晚餐")] == [first.id]
    renamed = store.rename_conversation(first.id, "user-1", "我的晚餐计划", tenant_id)
    assert renamed.title == "我的晚餐计划"
    store.archive_conversation(first.id, "user-1", tenant_id)
    assert [item.id for item in store.list_conversations("user-1", tenant_id)] == ["conversation-2"]
    assert [item.id for item in store.list_conversations("user-1", tenant_id, include_archived=True)] == [
        first.id,
        "conversation-2",
    ]
    store.engine.dispose()


def test_profile_suggestions_require_consent_and_can_be_accepted(tmp_path: Path):
    store = _store(tmp_path)
    tenant_id = store.get_or_create_personal_tenant("user-1")
    profiles = ProfileService(store)
    suggestions = profiles.create_suggestions(
        "我乳糖不耐受，每天三餐，最近想减脂",
        user_id="user-1",
        conversation_id="conversation-1",
        tenant_id=tenant_id,
    )
    assert {item["field"] for item in suggestions} == {"allergies", "meals_per_day", "health_goal"}
    with pytest.raises(ValueError, match="授权"):
        profiles.accept_suggestion(suggestions[0]["id"], "user-1", tenant_id=tenant_id)

    profiles.set_consent("user-1", True, tenant_id=tenant_id)
    profiles.accept_suggestion(suggestions[0]["id"], "user-1", tenant_id=tenant_id)
    profile = profiles.get("user-1", tenant_id)
    assert "乳糖" in profile["profile"]["allergies"]
    assert store.list_profile_suggestions("user-1", tenant_id=tenant_id)[0]["status"] == "pending"
    store.engine.dispose()


def test_grill_progress_and_revision_controls_required_fields():
    profile = TaskProfile(
        task_type="p2_2_test",
        fields=[
            FieldSpec(name="goal", description="目标", priority="critical", allow_free_text=True),
            FieldSpec(name="note", description="补充说明", priority="preferred", allow_free_text=True),
        ],
        operations={"plan": OperationSpec(required_fields=["goal"])},
    )
    engine = GrillEngine()
    result = engine.process(profile, "减脂", operation="plan", current_intent=profile.task_type)
    context = result.context
    progress = engine.progress(profile, context)
    assert progress["completed_count"] == 1
    assert progress["required_count"] == 1
    revised = engine.revise(profile, context, field_name="goal", operation="plan")
    assert revised.target_field == "goal"
    with pytest.raises(ValueError, match="不能跳过"):
        engine.skip(profile, revised.context, field_name="goal", operation="plan")

    optional_context = GrillContext(
        intent=profile.task_type,
        operation="plan",
        fields={"goal": "减脂", "note": "少油"},
        pending_field="note",
        status="collecting",
    )
    skipped = engine.skip(profile, optional_context, field_name="note", operation="plan")
    assert "note" in skipped.context.skipped_fields


def test_experience_settings_are_scoped_and_partial_updates_preserve_values(tmp_path: Path):
    store = _store(tmp_path)
    tenant_id = store.get_or_create_personal_tenant("user-1")
    initial = store.get_experience_settings("user-1", tenant_id)
    assert initial["show_sources"] is True
    updated = store.update_experience_settings(
        "user-1",
        {"show_sources": False, "answer_style": "concise", "pinned_shortcuts": ["weight_control"]},
        tenant_id,
    )
    assert updated["show_sources"] is False
    assert updated["show_model_info"] is True
    assert updated["pinned_shortcuts"] == ["weight_control"]
    other_tenant = store.create_tenant(tenant_id="tenant-2", name="第二空间", slug="second", owner_id="user-1")["id"]
    assert store.get_experience_settings("user-1", other_tenant)["show_sources"] is True
    store.engine.dispose()
