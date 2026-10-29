from core.conversation_runtime import ConversationRuntime
from core.tool_registry import build_default_tool_registry


class FakeMemory:
    def __init__(self):
        self.saved = []

    def add_interaction(self, user_input, agent_output, user_id):
        self.saved.append((user_input, agent_output, user_id))


class FakeWorkflow:
    def __init__(self, action="execute"):
        self.action = action
        self.calls = []

    def invoke(self, state, config):
        self.calls.append((state, config))
        return {
            "messages": [
                *state["messages"],
                {"role": "assistant", "content": "统一工作流回答"},
            ],
            "grill_result": {
                "action": self.action,
                "target_field": "meal_type" if self.action == "clarify" else None,
                "candidates": [],
                "assumptions": [],
            },
            "tool_outputs": {"meal_planner": "ok"} if self.action == "execute" else {},
        }


def test_default_tool_registry_has_one_canonical_tool_boundary():
    registry = build_default_tool_registry()

    assert set(registry.names) == {"retrieval_tool", "calorie_query", "meal_planner", "web_search"}
    assert registry.execute("meal_planner", "晚餐", {"fields": {"meal_type": "dinner"}}).startswith("餐食规划参数已确认")


def test_conversation_runtime_owns_workflow_invocation_and_response_contract():
    workflow = FakeWorkflow(action="execute")
    memory = FakeMemory()
    runtime = ConversationRuntime(workflow=workflow, memory_mgr=memory)

    response = runtime.ask("晚餐", user_id="user-1")

    assert response.answer == "统一工作流回答"
    assert response.type == "answer"
    assert response.retrieval_count == 1
    assert workflow.calls[0][1] == {"configurable": {"thread_id": "user-1"}}
    assert memory.saved == [("晚餐", "统一工作流回答", "user-1")]


def test_clarification_is_not_saved_as_final_memory():
    workflow = FakeWorkflow(action="clarify")
    memory = FakeMemory()
    runtime = ConversationRuntime(workflow=workflow, memory_mgr=memory)

    response = runtime.ask("我想吃点东西", user_id="user-2")

    assert response.type == "clarification"
    assert response.target_field == "meal_type"
    assert memory.saved == []


def test_legacy_executor_can_be_migrated_without_creating_a_second_agent():
    from agent.agent_executor import WorkflowAgentExecutor

    runtime = ConversationRuntime(workflow=FakeWorkflow(), memory_mgr=FakeMemory())
    executor = WorkflowAgentExecutor(runtime=runtime)

    result = executor.invoke({"input": "晚餐"}, {"configurable": {"thread_id": "legacy-user"}})

    assert result["output"] == "统一工作流回答"
    assert result["metadata"]["type"] == "answer"
