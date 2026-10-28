import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio
import json
import os

# stdout is reserved for MCP JSON-RPC frames; application logs must use stderr.
os.environ.setdefault("MCP_STDIO", "1")

from mcp.server import Server, stdio_server
from mcp.types import TextContent, Tool
from config import settings
from core.tool_registry import ToolRegistry, ToolResult, build_default_tool_registry
# 创建服务器实例
server = Server("nutrition-local-server")
tool_registry: ToolRegistry = build_default_tool_registry()


def allowed_tools() -> set[str]:
    return {item.strip() for item in settings.mcp_local_allowed_tools.split(",") if item.strip()}


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(name=spec.name, description=spec.description, inputSchema=spec.input_schema)
        for spec in tool_registry.specs
        if spec.name in allowed_tools() and "mcp" in spec.allowed_callers
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name not in allowed_tools():
        result = ToolResult(status="permission_denied", error_code="tool_not_allowed")
    else:
        result = tool_registry.execute_result(
            name,
            json.dumps(arguments, ensure_ascii=False),
            {"fields": arguments, "mcp_arguments": arguments},
            caller="mcp",
        )
    return [TextContent(type="text", text=json.dumps(result.model_dump(mode="json"), ensure_ascii=False))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
