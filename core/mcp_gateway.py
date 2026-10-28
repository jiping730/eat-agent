"""Small-platform MCP server registry and guarded tool gateway.

The application keeps MCP transport details behind this module.  The public
workflow continues to call ``ToolRegistry``; MCP tools are discovered from a
configured stdio server and registered into that same policy boundary.
"""

from __future__ import annotations

import atexit
import asyncio
import json
import logging
import sys
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from typing import Any, Callable, Mapping

from config import settings
from core.contracts import McpServerConfig, McpToolContract
from core.logging_config import configure_logging, log_event
from core.tool_registry import ToolRegistry, ToolResult


class McpGatewayError(RuntimeError):
    """Raised when an MCP server cannot be started or called safely."""


def _schema_accepts(schema: Mapping[str, Any], value: Any) -> bool:
    """Validate the small JSON Schema subset needed at the gateway boundary."""

    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, Mapping):
            return False
        for key in schema.get("required", []):
            if key not in value:
                return False
        return all(
            key not in value or _schema_accepts(property_schema, value[key])
            for key, property_schema in schema.get("properties", {}).items()
        )
    if expected == "array":
        return isinstance(value, list) and all(_schema_accepts(schema.get("items", {}), item) for item in value)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


class _McpServerConnection:
    """Own one MCP stdio session on a dedicated event-loop thread."""

    def __init__(self, config: McpServerConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: Any | None = None
        self._stop_event: asyncio.Event | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._closed = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name=f"mcp-{self.config.name}", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=self.config.startup_timeout_seconds):
            self.close()
            raise McpGatewayError(f"MCP Server 启动超时: {self.config.name}")
        if self._error is not None:
            error = self._error
            self.close()
            raise McpGatewayError(f"MCP Server 启动失败: {self.config.name}") from error

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as exc:  # pragma: no cover - defensive thread boundary
            self._error = exc
            self._ready.set()

    async def _serve(self) -> None:
        # Import lazily so the application can still run its documented offline
        # fallback when the optional MCP dependency is absent in a dev shell.
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        parameters = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env or None,
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                self._loop = asyncio.get_running_loop()
                self._session = session
                self._stop_event = asyncio.Event()
                self._ready.set()
                await self._stop_event.wait()

    def _submit(self, operation: str, *args: Any, timeout: float | None = None) -> Any:
        if self._loop is None or self._session is None:
            raise McpGatewayError(f"MCP Server 未连接: {self.config.name}")

        async def invoke() -> Any:
            if operation == "list_tools":
                return await self._session.list_tools()
            if operation == "call_tool":
                return await self._session.call_tool(*args)
            raise McpGatewayError(f"未知 MCP 操作: {operation}")

        future: Future[Any] = asyncio.run_coroutine_threadsafe(invoke(), self._loop)
        try:
            return future.result(timeout=timeout or settings.tool_default_timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise McpGatewayError(f"MCP Server 调用超时: {self.config.name}") from exc
        except Exception as exc:
            raise McpGatewayError(f"MCP Server 调用失败: {self.config.name}") from exc

    def list_tools(self) -> Any:
        return self._submit("list_tools", timeout=self.config.startup_timeout_seconds)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return self._submit("call_tool", name, arguments, timeout=settings.tool_default_timeout_seconds)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)


class McpServerRegistry:
    """Configuration-driven registry for the small platform's MCP Servers."""

    def __init__(
        self,
        configs: list[McpServerConfig],
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        names = [config.name for config in configs if config.enabled]
        if len(names) != len(set(names)):
            raise ValueError("MCP Server 名称不能重复")
        unsupported = [config.name for config in configs if config.transport != "stdio"]
        if unsupported:
            raise ValueError(f"当前仅支持 stdio MCP Server: {', '.join(unsupported)}")
        self.configs = [config for config in configs if config.enabled]
        self.logger = logger or configure_logging(settings.log_level)
        self._connections: dict[str, _McpServerConnection] = {}
        self._tools: dict[str, McpToolContract] = {}
        self._started = False
        self._lock = threading.RLock()

    @classmethod
    def from_settings(cls, *, logger: logging.Logger | None = None) -> "McpServerRegistry":
        configs: list[McpServerConfig] = []
        raw = settings.mcp_servers_json.strip()
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("MCP_SERVERS_JSON 不是合法 JSON") from exc
            items = payload if isinstance(payload, list) else [payload]
            configs = [McpServerConfig.model_validate(item) for item in items]
        elif settings.local_mcp_server == "stdio":
            configs = [
                McpServerConfig(
                    name=settings.mcp_local_server_name,
                    command=sys.executable,
                    args=["-m", "mcp_servers.local_server"],
                    startup_timeout_seconds=settings.mcp_startup_timeout_seconds,
                )
            ]
        return cls(configs, logger=logger)

    @property
    def tools(self) -> tuple[McpToolContract, ...]:
        return tuple(self._tools.values())

    def start(self) -> tuple[McpToolContract, ...]:
        with self._lock:
            if self._started:
                return self.tools
            for config in self.configs:
                connection = _McpServerConnection(config, self.logger)
                connection.start()
                self._connections[config.name] = connection
                response = connection.list_tools()
                for tool in getattr(response, "tools", []) or []:
                    name = str(getattr(tool, "name", "")).strip()
                    if not name:
                        continue
                    input_schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
                    output_schema = getattr(tool, "outputSchema", None) or getattr(tool, "output_schema", None) or {}
                    qualified_name = f"{config.name}.{name}"
                    if qualified_name in self._tools:
                        raise ValueError(f"MCP 工具名称重复: {qualified_name}")
                    self._tools[qualified_name] = McpToolContract(
                        server_name=config.name,
                        name=name,
                        version=config.version,
                        description=str(getattr(tool, "description", "") or ""),
                        input_schema=dict(input_schema),
                        output_schema=dict(output_schema),
                        allowed_callers=["workflow", "skill", "legacy"],
                    )
            self._started = True
            log_event(self.logger, 20, "mcp_registry_started", server_count=len(self._connections), tool_count=len(self._tools))
            return self.tools

    def call(self, contract: McpToolContract, arguments: dict[str, Any]) -> ToolResult:
        connection = self._connections.get(contract.server_name)
        if connection is None:
            return ToolResult(status="configuration_error", error_code="mcp_server_unavailable")
        try:
            response = connection.call_tool(contract.name, arguments)
        except McpGatewayError:
            return ToolResult(status="tool_execution_failed", error_code="mcp_tool_unavailable")
        return self._to_tool_result(contract, response)

    @staticmethod
    def _to_tool_result(contract: McpToolContract, response: Any) -> ToolResult:
        if getattr(response, "isError", False) or getattr(response, "is_error", False):
            return ToolResult(
                status="tool_execution_failed",
                error_code="mcp_tool_error",
                sources=[{"type": "mcp", "source": contract.server_name, "title": contract.name}],
            )
        text_parts: list[str] = []
        for item in getattr(response, "content", []) or []:
            text = getattr(item, "text", None)
            if text is not None:
                text_parts.append(str(text))
        text = "\n".join(text_parts)
        if text:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, Mapping) and "status" in payload:
                try:
                    result = ToolResult.model_validate(payload)
                    if contract.output_schema and not _schema_accepts(contract.output_schema, result.data):
                        return ToolResult(status="tool_execution_failed", error_code="mcp_invalid_output")
                    return result.model_copy(
                        update={
                            "sources": [
                                {"type": "mcp", "source": contract.server_name, "title": contract.name},
                                *result.sources,
                            ]
                        }
                    )
                except Exception:
                    return ToolResult(status="tool_execution_failed", error_code="mcp_invalid_output")
            data: Any = payload if payload is not None else text
        else:
            data = None
        result = ToolResult(
            status="success",
            data=data,
            sources=[{"type": "mcp", "source": contract.server_name, "title": contract.name}],
        )
        if contract.output_schema and not _schema_accepts(contract.output_schema, result.data):
            return ToolResult(status="tool_execution_failed", error_code="mcp_invalid_output")
        return result

    def close(self) -> None:
        with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
            self._started = False
        for connection in connections:
            connection.close()


class McpToolGateway:
    """Adapt discovered MCP tools into the canonical Tool Registry."""

    def __init__(
        self,
        server_registry: McpServerRegistry,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.server_registry = server_registry
        self.logger = logger or configure_logging(settings.log_level)
        self._registered = False
        atexit.register(self.close)

    def register_into(self, tool_registry: ToolRegistry) -> tuple[str, ...]:
        if self._registered:
            return tuple(contract.name for contract in self.server_registry.tools)
        contracts = self.server_registry.start()
        existing_names = set(tool_registry.names)
        registered: list[str] = []
        for contract in contracts:
            registry_name = contract.name if contract.name in existing_names else f"{contract.server_name}.{contract.name}"
            tool_registry.register(
                registry_name,
                self._handler(contract),
                description=contract.description,
                input_schema=contract.input_schema,
                output_schema=contract.output_schema or ToolResult.model_json_schema(),
                allowed_callers=contract.allowed_callers,
                replace=registry_name in existing_names,
            )
            registered.append(registry_name)
        self._registered = True
        return tuple(registered)

    def _handler(self, contract: McpToolContract) -> Callable[[str, Mapping[str, Any]], ToolResult]:
        def call(query: str, context: Mapping[str, Any]) -> ToolResult:
            fields = context.get("fields") if isinstance(context.get("fields"), Mapping) else {}
            supplied = context.get("mcp_arguments") if isinstance(context.get("mcp_arguments"), Mapping) else {}
            arguments = dict(supplied)
            properties = contract.input_schema.get("properties", {}) if isinstance(contract.input_schema, Mapping) else {}
            for key in properties:
                if key not in arguments and key in fields:
                    arguments[key] = fields[key]
            if "query" in properties and "query" not in arguments:
                arguments["query"] = query
            return self.server_registry.call(contract, arguments)

        return call

    def close(self) -> None:
        self.server_registry.close()

