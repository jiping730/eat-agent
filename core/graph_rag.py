from neo4j import GraphDatabase
from config import settings


class GraphRAGEngine:
    def __init__(self):
        if not settings.use_graphrag:
            self.driver = None
            return
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password)
        )
        self._init_graph()

    def _init_graph(self):
        """初始化图结构：从文档中提取实体关系并导入"""
        # 此处可调用 NLP 工具从 documents 中抽取三元组
        # 示例：手动导入一些已知关系
        with self.driver.session() as session:
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (f:Food) REQUIRE f.name IS UNIQUE")
            # 插入示例数据
            session.run("MERGE (f:Food {name: '鸡胸肉'}) SET f.calorie = 165, f.category = '肉类'")
            session.run("MERGE (f:Food {name: '米饭'}) SET f.calorie = 116, f.category = '主食'")
            session.run(
                "MATCH (a:Food {name: '鸡胸肉'}), (b:Food {name: '米饭'}) MERGE (a)-[:搭配 {type: '午餐'}]->(b)")

    def search(self, query: str) -> str:
        """混合检索：先尝试图查询，失败则退回到向量检索"""
        if not self.driver:
            return ""

        # 关键词提取（简单示例）
        keywords = [word for word in query.split() if len(word) > 1]

        with self.driver.session() as session:
            # 1. 精确匹配实体
            for kw in keywords:
                result = session.run(
                    "MATCH (f:Food) WHERE f.name CONTAINS $kw RETURN f.name, f.calorie",
                    kw=kw
                ).single()
                if result:
                    return f"{result['f.name']} 每100克含 {result['f.calorie']} 千卡"

            # 2. 关系查询（如：鸡胸肉搭配什么？）
            if "搭配" in query:
                food = keywords[0] if keywords else ""
                result = session.run(
                    "MATCH (f:Food {name: $food})-[r:搭配]->(other) RETURN other.name, other.calorie",
                    food=food
                ).data()
                if result:
                    items = [f"{r['other.name']}({r['other.calorie']}千卡)" for r in result]
                    return f"{food} 可以搭配：{', '.join(items)}"

        return ""  # 未找到图结果，由主流程调用向量检索

    def close(self):
        if self.driver:
            self.driver.close()