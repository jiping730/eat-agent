"""Shared, durable conversation runtime for Web, CLI, and compatibility adapters."""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, replace
from queue import Queue
from typing import Any, Callable, Iterator

from config import settings
from core.logging_config import configure_logging, fingerprint, log_event
from core.memory import MemoryManager
from core.observability import (
    bind_observation_context,
    new_trace_id,
    record_conversation,
    record_fallback,
    record_grill_decision,
    record_grill_rounds,
    record_langfuse_trace,
    record_workflow,
    reset_observation_context,
    start_span,
)
from core.persistence import ConversationStore
from core.redis_support import RedisCoordinator
from core.streaming import StreamCancelled, StreamEmitter
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
    conversation_id: str | None = None
    request_id: str | None = None
    message_id: int | None = None
    grill: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "type": self.type,
            "target_field": self.target_field,
            "options": self.options,
            "assumptions": self.assumptions,
            "response_time": self.response_time,
            "retrieval_count": self.retrieval_count,
            "conversation_id": self.conversation_id,
            "request_id": self.request_id,
            "message_id": self.message_id,
            "grill": self.grill,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ConversationResponse":
        return cls(
            answer=str(payload.get("answer", "")),
            type=str(payload.get("type", "answer")),
            target_field=payload.get("target_field"),
            options=list(payload.get("options", [])),
            assumptions=list(payload.get("assumptions", [])),
            response_time=float(payload.get("response_time", 0)),
            retrieval_count=int(payload.get("retrieval_count", 0)),
            conversation_id=payload.get("conversation_id"),
            request_id=payload.get("request_id"),
            message_id=payload.get("message_id"),
            grill=dict(payload.get("grill", {})),
        )


class ConversationRuntime:
    """Own the canonical workflow invocation and durable conversation state."""

    def __init__(
        self,
        workflow: Any | None = None,
        memory_mgr: Any | None = None,
        store: ConversationStore | None = None,
    ) -> None:
        self.logger = configure_logging(settings.log_level)
        for warning in settings.startup_warnings():
            log_event(self.logger, 30, "configuration_warning", warning=warning)
        self.memory_mgr = memory_mgr or MemoryManager()
        self.tool_registry = build_default_tool_registry()
        self.store = store or ConversationStore()
        self.workflow = workflow or create_workflow(
            memory_mgr=self.memory_mgr,
            tool_registry=self.tool_registry,
        )
        self._locks: defaultdict[str, threading.RLock] = defaultdict(threading.RLock)
        self.coordinator = RedisCoordinator()

    def ask(
        self,
        question: str,
        user_id: str | None = None,
        conversation_id: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> ConversationResponse:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question 不能为空")

        resolved_user_id = user_id or str(uuid.uuid4())
        resolved_conversation_id = conversation_id or resolved_user_id
        resolved_request_id = request_id or str(uuid.uuid4())
        resolved_trace_id = trace_id or new_trace_id()
        normalized_question = question.strip()
        context_token = bind_observation_context(
            request_id=resolved_request_id,
            trace_id=resolved_trace_id,
            conversation_id=resolved_conversation_id,
            user_id_hash=fingerprint(resolved_user_id),
        )
        try:
            with self._locks[resolved_conversation_id]:
                with self.coordinator.conversation_lock(resolved_conversation_id):
                    existing_response = self.store.get_idempotent_response(
                        resolved_conversation_id,
                        resolved_user_id,
                        resolved_request_id,
                    )
                    if existing_response is not None:
                        return ConversationResponse.from_dict(existing_response)
                    return self._ask_locked(
                        normalized_question,
                        resolved_user_id,
                        resolved_conversation_id,
                        resolved_request_id,
                        resolved_trace_id,
                    )
        finally:
            reset_observation_context(context_token)

    def ask_stream(
        self,
        question: str,
        user_id: str | None = None,
        conversation_id: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> Iterator[str]:
        """Run one turn in a worker and yield replayable SSE frames.

        The workflow is synchronous internally, so a bounded HTTP stream needs
        a worker boundary to expose node and model events as they happen. The
        same conversation lock and idempotency checks as ``ask`` are retained.
        """

        if not isinstance(question, str) or not question.strip():
            raise ValueError("question 不能为空")

        resolved_user_id = user_id or str(uuid.uuid4())
        resolved_conversation_id = conversation_id or resolved_user_id
        resolved_request_id = request_id or str(uuid.uuid4())
        resolved_trace_id = trace_id or new_trace_id()
        event_queue: Queue[Any] = Queue()
        cancel_event = threading.Event()
        emitter = StreamEmitter(
            request_id=resolved_request_id,
            conversation_id=resolved_conversation_id,
            trace_id=resolved_trace_id,
            sink=event_queue.put,
            cancel_event=cancel_event,
        )
        stream_end = object()

        def run() -> None:
            context_token = bind_observation_context(
                request_id=resolved_request_id,
                trace_id=resolved_trace_id,
                conversation_id=resolved_conversation_id,
                user_id_hash=fingerprint(resolved_user_id),
            )
            try:
                emitter.emit(
                    "conversation.started",
                    {"question_length": len(question.strip()), "status": "started"},
                )
                with self._locks[resolved_conversation_id]:
                    with self.coordinator.conversation_lock(resolved_conversation_id):
                        existing_response = self.store.get_idempotent_response(
                            resolved_conversation_id,
                            resolved_user_id,
                            resolved_request_id,
                        )
                        if existing_response is not None:
                            response = ConversationResponse.from_dict(existing_response)
                        else:
                            response = self._ask_locked(
                                question.strip(),
                                resolved_user_id,
                                resolved_conversation_id,
                                resolved_request_id,
                                resolved_trace_id,
                                stream_emit=emitter.emit,
                                cancel_event=cancel_event,
                            )
                emitter.emit("answer.completed", response.to_dict())
                emitter.emit("conversation.completed", {"status": "completed", "type": response.type})
            except StreamCancelled:
                emitter.emit(
                    "error",
                    {"code": "cancelled", "message": "回答生成已停止。"},
                    allow_cancelled=True,
                )
            except Exception as exc:
                log_event(self.logger, 40, "conversation_stream_failed", error_type=type(exc).__name__)
                emitter.emit(
                    "error",
                    {"code": "stream_failed", "message": "回答生成失败，请稍后重试。"},
                    allow_cancelled=True,
                )
            finally:
                event_queue.put(stream_end)
                reset_observation_context(context_token)

        threading.Thread(target=run, name="conversation-stream", daemon=True).start()
        try:
            while True:
                item = event_queue.get()
                if item is stream_end:
                    break
                yield item.to_sse()
        finally:
            cancel_event.set()

    def regenerate(
        self,
        *,
        user_id: str,
        conversation_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> ConversationResponse:
        """Regenerate the latest assistant turn without duplicating its user message."""

        resolved_request_id = request_id or str(uuid.uuid4())
        resolved_trace_id = trace_id or new_trace_id()
        snapshot = self.store.load(conversation_id, user_id, include_metadata=True)
        latest = self.store.latest_user_message(conversation_id, user_id)
        latest_index = next(
            (index for index, message in enumerate(snapshot.messages) if message.get("id") == latest["id"]),
            None,
        )
        if latest_index is None:
            raise KeyError("没有可重新生成的用户消息")
        history = snapshot.messages[:latest_index]
        context_token = bind_observation_context(
            request_id=resolved_request_id,
            trace_id=resolved_trace_id,
            conversation_id=conversation_id,
            user_id_hash=fingerprint(user_id),
        )
        try:
            with self._locks[conversation_id]:
                with self.coordinator.conversation_lock(conversation_id):
                    existing_response = self.store.get_idempotent_response(
                        conversation_id,
                        user_id,
                        resolved_request_id,
                    )
                    if existing_response is not None:
                        return ConversationResponse.from_dict(existing_response)
                    return self._ask_locked(
                        str(latest["content"]),
                        user_id,
                        conversation_id,
                        resolved_request_id,
                        resolved_trace_id,
                        history_messages=history,
                        persist_user_message=False,
                        regenerate=True,
                    )
        finally:
            reset_observation_context(context_token)

    def _ask_locked(
        self,
        question: str,
        user_id: str,
        conversation_id: str,
        request_id: str,
        trace_id: str,
        *,
        stream_emit: Callable[..., Any] | None = None,
        cancel_event: threading.Event | None = None,
        history_messages: list[dict[str, Any]] | None = None,
        persist_user_message: bool = True,
        regenerate: bool = False,
    ) -> ConversationResponse:
        if cancel_event is not None and cancel_event.is_set():
            raise StreamCancelled("stream cancelled by client")
        snapshot = self.store.load(conversation_id, user_id)
        user_message = {"role": "user", "content": question}
        initial_state: dict[str, Any] = {
            "messages": [*(history_messages if history_messages is not None else snapshot.messages), user_message],
            "user_id": user_id,
            "memory_context": [],
            "current_goal": snapshot.current_goal or "",
            "current_operation": (snapshot.grill_context or {}).get("operation", "answer"),
            "request_intent": (snapshot.grill_context or {}).get("intent_payload", {}),
            "plan": [],
            "tool_outputs": {},
            "reflection": "",
            "iteration": 0,
            "followup": False,
            "grill_context": snapshot.grill_context,
            "grill_result": {},
            "tool_results": {},
            "tool_sources": {},
            "request_id": request_id,
            "conversation_id": conversation_id,
            "trace_id": trace_id,
        }
        if stream_emit is not None:
            initial_state["stream_emit"] = stream_emit
        if cancel_event is not None:
            initial_state["cancel_event"] = cancel_event
        if regenerate:
            initial_state["regenerate"] = True

        started_at = time.perf_counter()
        workflow_status = "success"
        try:
            with start_span(
                "conversation.ask",
                {
                    "conversation.id": conversation_id,
                    "request.id": request_id,
                    "user.id_hash": fingerprint(user_id),
                },
            ):
                final_state = self.workflow.invoke(
                    initial_state,
                    config={"configurable": {"thread_id": conversation_id}},
                )
            if cancel_event is not None and cancel_event.is_set():
                raise StreamCancelled("stream cancelled by client")
        except Exception:
            workflow_status = "error"
            record_workflow(initial_state.get("current_goal"), workflow_status, time.perf_counter() - started_at)
            raise
        record_workflow(final_state.get("current_goal"), workflow_status, time.perf_counter() - started_at)
        elapsed = time.perf_counter() - started_at

        assistant_messages = [
            message for message in final_state.get("messages", []) if message.get("role") == "assistant"
        ]
        answer = assistant_messages[-1]["content"] if assistant_messages else "暂时无法生成回答。"

        grill_result = final_state.get("grill_result", {}) or {}
        grill_action = str(grill_result.get("action") or "")
        intent = final_state.get("current_goal") or grill_result.get("task")
        record_grill_decision(
            grill_action or "unknown",
            grill_result.get("target_field"),
            intent=intent,
            reason=grill_result.get("reason"),
        )
        grill_context = final_state.get("grill_context", {}) or {}
        record_grill_rounds(intent, int(grill_context.get("total_rounds", 0) or 0))
        if grill_action == "fallback":
            record_fallback("grill_fallback")
        if grill_action not in {"clarify", "fallback", "pending_confirmation", "reject", "switch", "multi_task"}:
            self.memory_mgr.add_interaction(question, answer, user_id)

        response_type = {
            "advise": "advice",
            "clarify": "clarification",
            "fallback": "clarification",
            "pending_confirmation": "confirmation",
            "reject": "rejection",
            "switch": "clarification",
            "multi_task": "clarification",
        }.get(grill_action, "answer")
        target_field = grill_result.get("target_field")
        response = ConversationResponse(
            answer=answer,
            type=response_type,
            target_field=target_field,
            options=grill_result.get("candidates", []),
            assumptions=grill_result.get("assumptions", []),
            response_time=round(elapsed, 2),
            retrieval_count=len(final_state.get("tool_outputs", {})),
            conversation_id=conversation_id,
            request_id=request_id,
            grill=grill_result,
        )

        message_id = self.store.save_turn(
            conversation_id=conversation_id,
            user_id=user_id,
            request_id=request_id,
            user_message=question,
            assistant_message=answer,
            grill_context=grill_context,
            current_goal=final_state.get("current_goal"),
            response_type=response_type,
            target_field=target_field,
            response_payload=response.to_dict(),
            persist_user_message=persist_user_message,
        )
        response = replace(response, message_id=message_id)
        self.store.update_idempotent_response(
            conversation_id=conversation_id,
            request_id=request_id,
            response_payload=response.to_dict(),
        )

        record_conversation(response_type, grill_action or "none", elapsed)
        record_langfuse_trace(
            "conversation",
            metadata={
                "intent": intent or "unknown",
                "response_type": response_type,
                "grill_action": grill_action or "none",
                "duration_ms": round(elapsed * 1000, 2),
            },
        )

        return response
