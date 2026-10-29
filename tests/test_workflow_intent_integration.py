from core.tool_registry import build_default_tool_registry
from core.workflow import create_workflow


class StubMemory:
    def retrieve_relevant_memories(self, query, user_id=None):
        return []

    def save_meta(self, user_input, agent_output, score):
        return None


def _state(messages, grill_context=None):
    return {
        "messages": messages,
        "user_id": "intent-test-user",
        "memory_context": [],
        "current_goal": "",
        "current_operation": "answer",
        "request_intent": {},
        "plan": [],
        "tool_outputs": {},
        "reflection": "",
        "iteration": 0,
        "followup": False,
        "grill_context": grill_context or {},
        "grill_result": {},
        "tool_results": {},
        "tool_sources": {},
        "request_id": "intent-test-request",
        "conversation_id": "intent-test-conversation",
        "trace_id": "intent-test-trace",
        "tool_failures": [],
    }


def test_goal_only_advises_then_explicit_plan_enters_grill():
    workflow = create_workflow(memory_mgr=StubMemory(), tool_registry=build_default_tool_registry())

    first = workflow.invoke(_state([{"role": "user", "content": "我想减肥"}]))
    assert first["current_operation"] == "advice"
    assert first["grill_result"]["action"] == "advise"
    assert first["grill_result"].get("target_field") is None
    assert "哪一餐" not in first["messages"][-1]["content"]

    second = workflow.invoke(
        _state(
            [
                *first["messages"],
                {"role": "user", "content": "那帮我安排晚餐"},
            ],
            first["grill_context"],
        )
    )
    assert second["current_operation"] == "plan"
    assert second["current_goal"] == "meal_planner"
    assert second["grill_result"]["action"] == "clarify"
    assert second["grill_result"]["target_field"] == "allergy_info"

    third = workflow.invoke(
        _state(
            [
                *second["messages"],
                {"role": "user", "content": "没有忌口"},
            ],
            second["grill_context"],
        )
    )
    assert third["current_operation"] == "plan"
    assert third["grill_result"]["action"] == "execute"
    assert third["plan"] == []
    assert third["tool_outputs"].get("meal_planner")
