"""Shared conversation runtime for Web, CLI, and compatibility adapters."""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from core.memory import MemoryManager
from core.tool_registry import build_default_tool_registry
from core.workflow import create_workflow


@dataclass(frozen=True)
class ConversationResponse:
    answer: str
    type: str
    target_field: str | None = None
    options: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    response_time: float = 0.0
    retrieval_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "type": self.type,
            "target_field": self.target_field,
            "options": self.options,
            "assumptions": self.assumptions,
            "response_time": self.response_time,
            "retrieval_count": self.retrieval_count,
        }


class ConversationRuntime:
    """Own the one canonical way to invoke the agent workflow."""

    def __init__(self, workflow: Any | None = None, memory_mgr: Any | None = None) -> None:
        self.memory_mgr = memory_mgr or MemoryManager()
        self.tool_registry = build_default_tool_registry()
        self.workflow = workflow or create_workflow(
            memory_mgr=self.memory_mgr,
            tool_registry=self.tool_registry,
        )
        self._histories: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
        self._locks: defaultdict[str, threading.RLock] = defaultdict(threading.RLock)

    def ask(self, question: str, user_id: str | None = None) -> ConversationResponse:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question 不能为空")

        resolved_user_id = user_id or str(uuid.uuid4())
        normalized_question = question.strip()
        with self._locks[resolved_user_id]:
            return self._ask_locked(normalized_question, resolved_user_id)

    def _ask_locked(self, question: str, user_id: str) -> ConversationResponse:
        history = list(self._histories[user_id])
        user_message = {"role": "user", "content": question}
        if history:
            initial_state: dict[str, Any] = {"messages": [user_message], "user_id": user_id}
        else:
            initial_state = {
                "messages": [user_message],
                "user_id": user_id,
                "memory_context": [],
                "current_goal": "",
                "plan": [],
                "tool_outputs": {},
                "reflection": "",
                "iteration": 0,
                "followup": False,
                "grill_context": {},
                "grill_result": {},
            }

        started_at = time.perf_counter()
        final_state = self.workflow.invoke(
            initial_state,
            config={"configurable": {"thread_id": user_id}},
        )
        elapsed = time.perf_counter() - started_at

        assistant_messages = [
            message for message in final_state.get("messages", []) if message.get("role") == "assistant"
        ]
        answer = assistant_messages[-1]["content"] if assistant_messages else "暂时无法生成回答。"
        history.extend([user_message, {"role": "assistant", "content": answer}])
        self._histories[user_id] = history

        grill_result = final_state.get("grill_result", {}) or {}
        grill_action = grill_result.get("action")
        if grill_action not in {"clarify", "fallback", "pending_confirmation"}:
            self.memory_mgr.add_interaction(question, answer, user_id)

        response_type = {
            "clarify": "clarification",
            "fallback": "clarification",
            "pending_confirmation": "confirmation",
        }.get(grill_action, "answer")

        return ConversationResponse(
            answer=answer,
            type=response_type,
            target_field=grill_result.get("target_field"),
            options=grill_result.get("candidates", []),
            assumptions=grill_result.get("assumptions", []),
            response_time=round(elapsed, 2),
            retrieval_count=len(final_state.get("tool_outputs", {})),
        )
