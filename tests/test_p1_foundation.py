import json

import pytest
from pydantic import ValidationError

from core.contracts import (
    EvalCase,
    McpToolContract,
    ModelRouteRequest,
    RetrievalResponse,
    SourceRef,
    StreamEvent,
)


def test_source_contract_is_serializable_and_rejects_unknown_fields():
    source = SourceRef(
        type="knowledge_base",
        source="nutrition-guide.md",
        document_id="doc-1",
        version="2026-10-27",
        chunk_id="doc-1:3",
        metadata={"section": "蛋白质"},
    )

    assert source.model_dump(mode="json")["chunk_id"] == "doc-1:3"
    with pytest.raises(ValidationError):
        SourceRef(type="knowledge_base", source="guide", unsupported=True)


def test_retrieval_response_keeps_empty_result_explicit():
    response = RetrievalResponse(status="no_results", trace_id="trace-1")

    assert response.documents == []
    assert response.sources == []
    assert response.error_code is None


def test_model_route_contract_applies_safe_limits():
    request = ModelRouteRequest(
        task="answer",
        preferred_model="glm-4-flash",
        fallback_models=["glm-4-air"],
        max_tokens=1024,
        timeout_seconds=15,
    )

    assert request.temperature == 0.2
    with pytest.raises(ValidationError):
        ModelRouteRequest(task="answer", max_tokens=100_000)


def test_stream_event_serializes_to_replayable_sse():
    event = StreamEvent(
        event="retrieval.completed",
        sequence=2,
        request_id="request-1",
        conversation_id="conversation-1",
        trace_id="trace-1",
        data={"source_count": 1},
    )

    wire = event.to_sse()
    payload = json.loads(wire.split("data: ", 1)[1].splitlines()[0])
    assert wire.startswith("event: retrieval.completed\n")
    assert "id: request-1:2\n" in wire
    assert payload["data"] == {"source_count": 1}


def test_mcp_and_eval_contracts_capture_versioned_p1_metadata():
    tool = McpToolContract(server_name="local", name="meal_planner", version="1.0")
    case = EvalCase(
        case_id="meal-plan-001",
        question="帮我安排晚餐",
        expected_task="meal_planner",
        required_fields=["meal_type"],
        must_not_execute=True,
    )

    assert tool.model_dump(mode="json")["version"] == "1.0"
    assert case.must_not_execute is True
