import json
from types import SimpleNamespace

import pytest

from core.contracts import McpServerConfig, McpToolContract
from core.mcp_gateway import McpServerRegistry, McpToolGateway
from core.tool_registry import ToolRegistry, ToolResult


class FakeMcpRegistry:
    def __init__(self, contracts: tuple[McpToolContract, ...]):
        self._contracts = contracts
        self.calls: list[tuple[str, dict]] = []

    @property
    def tools(self):
        return self._contracts

    def start(self):
        return self._contracts

    def call(self, contract, arguments):
        self.calls.append((contract.name, arguments))
        return ToolResult(status="success", data={"answer": arguments.get("query", arguments.get("value"))})

    def close(self):
        return None


def test_mcp_server_config_is_stdio_only_and_rejects_duplicate_names():
    config = McpServerConfig(name="nutrition", command="python")
    assert config.transport == "stdio"

    with pytest.raises(ValueError, match="不能重复"):
        McpServerRegistry([config, config])


def test_gateway_registers_namespaced_tools_and_reuses_registry_policy():
    contract = McpToolContract(
        server_name="remote",
        name="lookup",
        input_schema={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        allowed_callers=["workflow"],
    )
    fake = FakeMcpRegistry((contract,))
    gateway = McpToolGateway(fake)
    tools = ToolRegistry()

    assert gateway.register_into(tools) == ("remote.lookup",)
    result = tools.execute_result(
        "remote.lookup",
        "",
        {"mcp_arguments": {"value": "鸡蛋"}, "request_id": "r-1"},
        caller="workflow",
    )

    assert result.status == "success"
    assert result.data == {"answer": "鸡蛋"}
    assert fake.calls == [("lookup", {"value": "鸡蛋"})]
    gateway.close()


def test_gateway_replaces_legacy_local_name_for_workflow_compatibility():
    contract = McpToolContract(
        server_name="nutrition_local",
        name="calorie_query",
        input_schema={"type": "object", "properties": {"food": {"type": "string"}}, "required": ["food"]},
        allowed_callers=["workflow"],
    )
    fake = FakeMcpRegistry((contract,))
    gateway = McpToolGateway(fake)
    tools = ToolRegistry()
    tools.register(
        "calorie_query",
        lambda _query, _context: ToolResult(status="success", data="legacy"),
        input_schema={"type": "object"},
    )

    assert gateway.register_into(tools) == ("calorie_query",)
    result = tools.execute_result(
        "calorie_query",
        "鸡蛋",
        {"mcp_arguments": {"food": "鸡蛋"}},
        caller="workflow",
    )

    assert result.status == "success"
    assert fake.calls == [("calorie_query", {"food": "鸡蛋"})]
    gateway.close()


def test_mcp_response_adds_provenance_and_rejects_invalid_output():
    contract = McpToolContract(
        server_name="nutrition_local",
        name="structured",
        output_schema={"type": "object", "required": ["value"]},
    )
    response = SimpleNamespace(
        isError=False,
        content=[SimpleNamespace(text=json.dumps({"status": "success", "data": {"value": 1}, "sources": []}))],
    )
    result = McpServerRegistry._to_tool_result(contract, response)
    assert result.status == "success"
    assert result.sources[0]["type"] == "mcp"

    invalid_response = SimpleNamespace(
        isError=False,
        content=[SimpleNamespace(text=json.dumps({"status": "success", "data": {"wrong": 1}, "sources": []}))],
    )
    invalid = McpServerRegistry._to_tool_result(contract, invalid_response)
    assert invalid.status == "tool_execution_failed"
    assert invalid.error_code == "mcp_invalid_output"
