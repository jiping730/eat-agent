"""Streaming primitives shared by the workflow runtime and HTTP layer."""

from __future__ import annotations

from threading import Event
from typing import Any, Callable

from core.contracts import StreamEvent, StreamEventName


class StreamCancelled(Exception):
    """Raised when a client stops a streaming conversation."""


StreamSink = Callable[[StreamEvent], None]


class StreamEmitter:
    """Create ordered, traceable events for one conversation turn."""

    def __init__(
        self,
        *,
        request_id: str,
        conversation_id: str,
        trace_id: str | None = None,
        sink: StreamSink | None = None,
        cancel_event: Event | None = None,
    ) -> None:
        self.request_id = request_id
        self.conversation_id = conversation_id
        self.trace_id = trace_id
        self.sink = sink
        self.cancel_event = cancel_event or Event()
        self.sequence = 0

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise StreamCancelled("stream cancelled by client")

    def emit(
        self,
        event: StreamEventName,
        data: dict[str, Any] | None = None,
        *,
        allow_cancelled: bool = False,
    ) -> StreamEvent:
        if not allow_cancelled:
            self.check_cancelled()
        item = StreamEvent(
            event=event,
            sequence=self.sequence,
            request_id=self.request_id,
            conversation_id=self.conversation_id,
            trace_id=self.trace_id,
            data=data or {},
        )
        self.sequence += 1
        if self.sink is not None:
            self.sink(item)
        return item

    def emit_sse(
        self,
        event: StreamEventName,
        data: dict[str, Any] | None = None,
        *,
        allow_cancelled: bool = False,
    ) -> str:
        return self.emit(event, data, allow_cancelled=allow_cancelled).to_sse()
