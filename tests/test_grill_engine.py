from core.grill_engine import GrillEngine, PROFILES


def test_meal_planner_asks_for_meal_type_first():
    result = GrillEngine().process(PROFILES["meal_planner"], "我想吃点东西")

    assert result.action == "clarify"
    assert result.target_field == "meal_type"
    assert result.question == "你想安排哪一餐？"
    assert [item.value for item in result.candidates] == ["breakfast", "lunch", "dinner"]


def test_meal_planner_collects_multiple_turns_until_ready():
    engine = GrillEngine()
    first = engine.process(PROFILES["meal_planner"], "我想吃点东西")
    second = engine.process(PROFILES["meal_planner"], "晚餐", first.context, current_intent="meal_planner")
    third = engine.process(PROFILES["meal_planner"], "没有忌口", second.context, current_intent="meal_planner")

    assert second.action == "clarify"
    assert second.target_field == "allergy_info"
    assert third.action == "execute"
    assert third.context.fields["meal_type"] == "dinner"
    assert third.context.fields["allergy_info"] == "none"
    assert third.context.fields["health_goal"] == "balanced"
    assert third.context.sources["health_goal"] == "default"


def test_safety_critical_free_text_is_accepted_when_explicitly_requested():
    engine = GrillEngine()
    first = engine.process(PROFILES["meal_planner"], "我想吃点东西")
    second = engine.process(PROFILES["meal_planner"], "晚餐", first.context, current_intent="meal_planner")
    third = engine.process(PROFILES["meal_planner"], "海鲜", second.context, current_intent="meal_planner")

    assert third.action == "execute"
    assert third.context.fields["allergy_info"] == "海鲜"


def test_unknown_safety_answer_does_not_silently_pass():
    engine = GrillEngine()
    first = engine.process(PROFILES["meal_planner"], "我想吃点东西")
    second = engine.process(PROFILES["meal_planner"], "晚餐", first.context, current_intent="meal_planner")
    third = engine.process(PROFILES["meal_planner"], "不知道", second.context, current_intent="meal_planner")

    assert third.action == "clarify"
    assert third.target_field == "allergy_info"
    assert "allergy_info" not in third.context.fields


def test_calorie_query_with_food_executes_and_defaults_amount():
    result = GrillEngine().process(PROFILES["calorie_query"], "鸡胸肉多少热量")

    assert result.action == "execute"
    assert result.context.fields["food"] == "鸡胸肉"
    assert result.context.fields["amount"] == "100g"


def test_calorie_query_without_food_clarifies():
    result = GrillEngine().process(PROFILES["calorie_query"], "多少热量")

    assert result.action == "clarify"
    assert result.target_field == "food"
    assert result.context.pending_field == "food"


def test_pending_intent_is_preserved_across_turns():
    engine = GrillEngine()
    first = engine.process(PROFILES["meal_planner"], "帮我安排一顿饭")
    second = engine.process(PROFILES["meal_planner"], "晚餐", first.context, current_intent="meal_planner")

    assert first.context.intent == "meal_planner"
    assert second.context.intent == "meal_planner"
    assert second.context.fields["meal_type"] == "dinner"
    assert second.action == "clarify"


def test_new_intent_does_not_reuse_old_context():
    engine = GrillEngine()
    first = engine.process(PROFILES["meal_planner"], "我想吃点东西")
    result = engine.process(
        PROFILES["calorie_query"],
        "鸡胸肉多少热量",
        first.context,
        current_intent="calorie_query",
    )

    assert result.action == "execute"
    assert result.context.intent == "calorie_query"
    assert result.context.fields == {"food": "鸡胸肉", "amount": "100g", "cooking_state": "未说明，按知识库常用口径估算"}


def test_max_total_rounds_returns_fallback():
    engine = GrillEngine()
    profile = PROFILES["meal_planner"].model_copy(update={"max_total_rounds": 2})
    first = engine.process(profile, "我想吃点东西")
    second = engine.process(profile, "还是不知道", first.context, current_intent="meal_planner")
    third = engine.process(profile, "仍然不知道", second.context, current_intent="meal_planner")

    assert second.action == "clarify"
    assert third.action == "fallback"
    assert third.context.status == "fallback"
    assert third.missing_fields == ["meal_type", "allergy_info"]


def test_fallback_context_can_resume_with_the_requested_value():
    engine = GrillEngine()
    profile = PROFILES["meal_planner"].model_copy(update={"max_clarifications": 0})
    fallback = engine.process(profile, "我想吃点东西")
    resumed = engine.process(profile, "晚餐", fallback.context, current_intent="meal_planner")

    assert fallback.action == "fallback"
    assert resumed.context.fields["meal_type"] == "dinner"
    assert resumed.target_field == "allergy_info"
