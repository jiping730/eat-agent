import re
from rag.retriever import get_retriever_with_score


class CalorieQuerySkill:
    name = "calorie_query"
    description = "查询食物的热量，输入食物名称，返回每100克的热量"

    @staticmethod
    def extract_food(text: str) -> str:
        # 简单提取食物名称（可替换为 NER 模型）
        match = re.search(r"([\u4e00-\u9fa5]{2,})", text)
        return match.group(1) if match else ""

    @staticmethod
    def execute(input_text: str) -> str:
        food = CalorieQuerySkill.extract_food(input_text)
        if not food:
            return "请告诉我你想查询哪种食物？"
        retriever = get_retriever_with_score()
        docs = retriever(f"{food} 热量")
        if docs:
            return docs[0].page_content
        else:
            return f"抱歉，知识库中未找到 {food} 的热量信息。"