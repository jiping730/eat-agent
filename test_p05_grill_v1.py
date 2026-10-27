from core.grill_engine import FieldSpec, GrillEngine, PROFILES, TaskProfile, detect_task_intents, load_profiles


def test_profiles_are_loaded_from_validated_configuration():
    assert set(PROFILES) >= {"meal_planner", "calorie_query"}
    assert PROFILES["meal_planner"].version == "1.0"
    assert {field.field_type for field in PROFILES["meal_planner"].fields} >= {"enum", "number", "text"}


def test_grill_result_has_versioned_decision_protocol():
    result = GrillEngine().process(PROFILES["meal_planner"], "我想吃点东西")
    payload = result.to_dict()

    assert payload["schema_version"] == "1.0"
    assert payload["task"] == "meal_planner"
    assert payload["profile_version"] == "1.0"
    assert payload["action"] == "clarify"
    assert payload["reason"] == "required_field_missing"
    assert payload["confidence"] > 0.9


def test_field_states_explain_user_and_default_values():
    engine = GrillEngine()
    first = engine.process(PROFILES["meal_planner"], "晚餐")
    result = engine.process(PROFILES["meal_planner"], "没有忌口", first.context, current_intent="meal_planner")

    assert result.action == "execute"
    assert result.context.field_states["meal_type"].source == "user"
    assert result.context.field_states["health_goal"].source == "default"
    assert result.context.field_states["health_goal"].confidence == 0.75


def test_invalid_enum_answer_is_explained_and_never_executed():
    profile = TaskProfile(
        task_type="enum_task",
        fields=[
            FieldSpec(
                name="choice",
                description="选项",
                field_type="enum",
                priority="critical",
                known_values={"a": "甲", "b": "乙"},
                question="请选择甲或乙。",
            )
        ],
    )
    engine = GrillEngine()
    first = engine.process(profile, "开始")
    result = engine.process(profile, "丙", first.context, current_intent="enum_task")

    assert result.action == "clarify"
    assert result.reason == "invalid_value"
    assert result.context.fields == {}
    assert result.issues[0].code == "invalid_value"


def test_number_date_and_boolean_types_are_normalized():
    engine = GrillEngine()
    number = TaskProfile(
        task_type="number_task",
        fields=[FieldSpec(name="count", description="数量", field_type="number", priority="critical", min_value=1)],
    )
    date_profile = TaskProfile(
        task_type="date_task",
        fields=[FieldSpec(name="day", description="日期", field_type="date", priority="critical")],
    )
    boolean = TaskProfile(
        task_type="boolean_task",
        fields=[FieldSpec(name="need", description="是否需要", field_type="boolean", priority="critical")],
    )

    assert engine.process(number, "3个").context.fields["count"] == 3
    assert engine.process(date_profile, "2026年10月27日").context.fields["day"] == "2026-10-27"
    assert engine.process(boolean, "是").context.fields["need"] is True


def test_low_confidence_free_text_stays_in_clarification():
    profile = TaskProfile(
        task_type="strict_text",
        confidence_threshold=0.95,
        fields=[FieldSpec(name="name", description="名称", field_type="text", priority="critical", allow_free_text=True)],
    )
    engine = GrillEngine()
    first = engine.process(profile, "开始")
    result = engine.process(profile, "一个不太明确的名字", first.context, current_intent="strict_text")

    assert result.action == "clarify"
    assert result.reason == "low_confidence"
    assert "name" not in result.context.fields


def test_conflicting_safety_answer_blocks_execution():
    context = {"intent": "meal_planner", "fields": {"meal_type": "dinner"}}
    result = GrillEngine().process(
        PROFILES["meal_planner"],
        "没有过敏，但海鲜过敏",
        context,
        current_intent="meal_planner",
    )

    assert result.action == "clarify"
    assert result.reason == "conflict"
    assert result.issues[0].code == "conflict"


def test_required_field_refusal_is_explicit_rejection():
    first = GrillEngine().process(PROFILES["meal_planner"], "我想吃点东西")
    result = GrillEngine().process(PROFILES["meal_planner"], "不想回答", first.context, current_intent="meal_planner")

    assert result.action == "reject"
    assert result.reason == "required_field_refused"
    assert result.context.status == "rejected"


def test_confirmation_is_a_real_gate_before_execution():
    profile = TaskProfile(
        task_type="confirmed_task",
        confirmation_required=True,
        fields=[
            FieldSpec(
                name="choice",
                description="选项",
                field_type="enum",
                priority="critical",
                known_values={"yes": "是"},
            )
        ],
    )
    engine = GrillEngine()
    pending = engine.process(profile, "是")
    executed = engine.process(profile, "确认", pending.context, current_intent="confirmed_task")

    assert pending.action == "pending_confirmation"
    assert pending.context.status == "awaiting_confirmation"
    assert executed.action == "execute"
    assert executed.reason == "confirmed"


def test_topic_switch_discards_old_task_fields():
    engine = GrillEngine()
    first = engine.process(PROFILES["meal_planner"], "晚餐")
    result = engine.process(
        PROFILES["calorie_query"],
        "鸡胸肉多少热量",
        first.context,
        current_intent="calorie_query",
    )

    assert result.action == "execute"
    assert result.context.intent == "calorie_query"
    assert result.context.previous_intent == "meal_planner"
    assert "meal_type" not in result.context.fields


def test_multi_task_input_keeps_an_explicit_sequential_queue():
    result = GrillEngine().process(PROFILES["meal_planner"], "帮我安排晚餐，同时查询鸡胸肉热量")

    assert result.context.task_queue == ["meal_planner", "calorie_query"]
    assert result.task_queue == ["meal_planner", "calorie_query"]
    assert result.action == "clarify"


def test_profile_loader_can_load_a_custom_profile(tmp_path):
    profile_file = tmp_path / "custom.json"
    profile_file.write_text(
        '{"task_type":"custom","version":"2.0","fields":[{"name":"x","description":"X","field_type":"text","priority":"critical"}]}',
        encoding="utf-8",
    )

    profiles = load_profiles(tmp_path)
    assert profiles["custom"].version == "2.0"


def test_task_intent_detection_only_returns_supported_tasks():
    assert detect_task_intents("安排晚餐，同时查鸡胸肉热量") == ["meal_planner", "calorie_query"]
