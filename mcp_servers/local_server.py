import sys
import os
# 计算项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# 打印调试信息
print(f"Project root: {project_root}")
print(f"sys.path[0]: {sys.path[0]}")
print(f"Contents of rag folder: {os.listdir(os.path.join(project_root, 'rag')) if os.path.exists(os.path.join(project_root, 'rag')) else 'rag folder not found'}")

import asyncio
import json
from mcp.server import Server, stdio_server
from mcp.types import TextContent, Tool
from rag.retriever import get_retriever_with_score   # 尝试导入
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
    retriever = get_retriever_with_score()

    if name == "calorie_query":
        food = arguments["food"]
        docs = retriever(f"{food} 热量")
        if docs:
            return [TextContent(type="text", text=docs[0].page_content)]
        else:
            return [TextContent(type="text", text=f"未找到 {food} 的热量信息。")]

    elif name == "meal_planner":
        calories = arguments["calories"]
        meal_type = arguments["meal_type"]
        docs = retriever(f"{calories}千卡 {meal_type} 组合")
        if docs:
            return [TextContent(type="text", text=docs[0].page_content)]
        else:
            return [TextContent(type="text", text=f"未找到 {calories}千卡的{meal_type}组合。")]

    else:
        raise ValueError(f"未知工具: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())