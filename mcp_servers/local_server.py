import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio
import json
from mcp.server import Server, stdio_server
from mcp.types import TextContent, Tool
from core.tool_registry import ToolRegistry, build_default_tool_registry
# 创建服务器实例
server = Server("nutrition-local-server")
tool_registry: ToolRegistry = build_default_tool_registry()


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(name=spec.name, description=spec.description, inputSchema=spec.input_schema)
        for spec in tool_registry.specs
        if spec.name in {"calorie_query", "meal_planner"}
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "calorie_query":
        food = arguments.get("food", "")
        result = tool_registry.execute_result(
            name,
            f"{food} 热量",
            {"fields": {"food": food}},
            caller="mcp",
        )
    elif name == "meal_planner":
        calories = arguments.get("calories", "")
        meal_type = arguments.get("meal_type", "")
        result = tool_registry.execute_result(
            name,
            f"{calories}千卡 {meal_type} 组合",
            {"fields": {"calories": calories, "meal_type": meal_type}},
            caller="mcp",
        )
    else:
        result = tool_registry.execute_result(name, "", arguments, caller="mcp")
    return [TextContent(type="text", text=json.dumps(result.model_dump(mode="json"), ensure_ascii=False))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
