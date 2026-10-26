import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio
import json
from mcp.server import Server, stdio_server
from mcp.types import TextContent, Tool
from core.tool_registry import retrieve_knowledge
# 创建服务器实例
server = Server("nutrition-local-server")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(
            name="calorie_query",
            description="查询食物的热量，输入食物名称，返回每100克的热量",
            inputSchema={
                "type": "object",
                "properties": {
                    "food": {"type": "string", "description": "食物名称，如鸡胸肉"}
                },
                "required": ["food"]
            }
        ),
        Tool(
            name="meal_planner",
            description="根据热量目标推荐餐食组合",
            inputSchema={
                "type": "object",
                "properties": {
                    "calories": {"type": "integer", "description": "目标热量，如500"},
                    "meal_type": {"type": "string", "enum": ["早餐", "午餐", "晚餐"]}
                },
                "required": ["calories", "meal_type"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "calorie_query":
        food = arguments["food"]
        return [TextContent(type="text", text=retrieve_knowledge(f"{food} 热量"))]

    elif name == "meal_planner":
        calories = arguments["calories"]
        meal_type = arguments["meal_type"]
        return [TextContent(type="text", text=retrieve_knowledge(f"{calories}千卡 {meal_type} 组合"))]

    else:
        raise ValueError(f"未知工具: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
