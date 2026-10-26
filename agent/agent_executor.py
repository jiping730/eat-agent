"""Backward-compatible adapter for the old ReAct entry point.

The application no longer creates a second ReAct graph here. Existing callers
can keep using ``create_agent_executor().invoke({"input": ...})`` while the
request is delegated to the canonical ConversationRuntime and LangGraph
workflow.
"""

from __future__ import annotations

from typing import Any

from core.conversation_runtime import ConversationRuntime


class WorkflowAgentExecutor:
    """Expose the old ``invoke`` shape over the unified runtime."""

    def __init__(self, runtime: ConversationRuntime | None = None) -> None:
        self.runtime = runtime or ConversationRuntime()

    def invoke(self, payload: dict[str, Any], config: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
        question = payload.get("input") or payload.get("question")
        if not isinstance(question, str):
            raise ValueError("invoke payload 必须包含 input 或 question 字段")

        user_id = None
        if config:
            user_id = config.get("configurable", {}).get("thread_id")
        response = self.runtime.ask(question, user_id=user_id)
        return {
            "input": question,
            "output": response.answer,
            "metadata": response.to_dict(),
        }


def create_agent_executor(callbacks: Any | None = None) -> WorkflowAgentExecutor:
    """Keep the public factory while routing to the canonical workflow."""

    # ``callbacks`` remains accepted for source compatibility. Observability
    # is owned by ConversationRuntime and the workflow from this point on.
    del callbacks
    return WorkflowAgentExecutor()
