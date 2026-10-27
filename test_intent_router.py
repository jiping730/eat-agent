from core.intent_router import classify_request
from core.grill_engine import GrillEngine, get_profile


def test_goal_only_routes_to_advice_without_meal_slots():
    intent = classify_request("我想减肥")

    assert intent.domain == "nutrition"
    assert intent.operation == "advice"
    assert intent.task is None
    assert intent.goal == "weight_control"


def test_explicit_meal_plan_routes_to_meal_planner():
    intent = classify_request("帮我安排减脂晚餐")

    assert intent.domain == "nutrition"
    assert intent.operation == "plan"
    assert intent.task == "meal_planner"
    assert intent.slots["meal_type"] == "dinner"


def test_calorie_lookup_and_calculation_are_different_operations():
    lookup = classify_request("鸡胸肉多少热量")
    calculation = classify_request("计算我今天摄入多少热量")

    assert (lookup.task, lookup.operation) == ("calorie_query", "lookup")
    assert (calculation.task, calculation.operation) == ("calorie_query", "calculate")


def test_generic_goal_is_advice():
    intent = classify_request("我想提高英语")

    assert intent.domain == "general"
    assert intent.operation == "advice"
    assert intent.goal == "improve_language"


def test_pending_grill_field_continues_previous_plan():
    intent = classify_request(
        "没有忌口",
        {
            "intent": "meal_planner",
            "operation": "plan",
            "domain": "nutrition",
            "pending_field": "allergy_info",
        },
    )

    assert intent.continuation is True
    assert (intent.task, intent.operation) == ("meal_planner", "plan")


def test_explicit_plan_can_switch_from_advice():
    intent = classify_request(
        "那帮我安排晚餐",
        {
            "intent": "nutrition",
            "operation": "advice",
            "domain": "nutrition",
            "pending_field": None,
        },
    )

    assert (intent.task, intent.operation) == ("meal_planner", "plan")


def test_operation_policy_keeps_advice_out_of_grill():
    profile = get_profile("meal_planner")
    result = GrillEngine().process(profile, "我想减肥", operation="advice", current_intent="meal_planner")

    assert result.action == "advise"
    assert result.target_field is None
    assert result.operation == "advice"


def test_operation_policy_still_clarifies_explicit_plan():
    profile = get_profile("meal_planner")
    result = GrillEngine().process(profile, "帮我安排减脂晚餐", operation="plan", current_intent="meal_planner")

    assert result.action == "clarify"
    assert result.target_field == "allergy_info"
