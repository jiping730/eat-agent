# 轻松食 · Agentic RAG 智能营养助手

基于 **智谱AI + LangChain + LangGraph** 的智能检索增强生成（RAG）Agent，专注于食物热量查询与餐食搭配推荐。

## 核心特性

- **意图识别** — 自动判断用户意图（热量查询 / 餐食规划 / 追问 / 联网搜索 / 通用问答）
- **知识库检索** — 基于 FAISS 向量库的语义检索，支持相似度阈值过滤
- **联网搜索** — 集成 Tavily 搜索引擎，支持实时信息查询
- **多轮对话** — 短期记忆 + 长期记忆（FAISS 向量化），支持追问与上下文关联
- **GraphRAG** — 可选 Neo4j 图检索，支持食物搭配关系查询
- **MCP 协议** — 提供本地 MCP Server，支持外部工具调用
- **Web 界面** — Flask 前端，开箱即用的聊天式交互

## 项目结构

```
agent1/
├── main.py                  # CLI 入口
├── config.py                # 全局配置（Pydantic Settings）
├── .env                     # 环境变量（API Key 等）
├── requirements.txt         # 依赖清单
├── pyproject.toml           # 项目元数据 & 构建配置
│
├── agent/                   # Agent 核心
│   ├── agent_executor.py    # ReAct Agent 执行器
│   ├── tools.py             # 工具定义（知识库检索、联网搜索）
│   └── prompt.py            # ReAct 提示模板
│
├── core/                    # 工作流与记忆
│   ├── workflow.py          # LangGraph 状态图（意图识别→记忆检索→规划→执行→生成→反思）
│   ├── memory.py            # 短期/长期记忆管理器
│   ├── graph_rag.py         # GraphRAG 引擎（Neo4j）
│   └── skills/              # 技能模块
│       ├── calorie_query/   # 热量查询技能
│       └── meal_planner/    # 餐食规划技能
│
├── rag/                     # 检索增强生成
│   ├── embeddings.py        # 智谱 Embedding 封装
│   ├── vector_store.py      # FAISS 向量库构建与加载
│   └── retriever.py         # 带相似度阈值的检索器
│
├── utils/                   # 工具函数
│   ├── llm.py               # 智谱 LLM 封装
│   ├── callbacks.py         # LangChain 性能回调
│   └── performance.py       # 性能统计装饰器
│
├── mcp_servers/             # MCP 服务器
│   ├── local_server.py      # 本地 MCP Server（热量查询 + 餐食规划）
│   └── firecrawl_client.py  # Firecrawl 爬虫客户端
│
├── front/                   # Web 前端
│   ├── app.py               # Flask 应用
│   ├── templates/index.html # 聊天页面
│   └── static/              # JS / CSS
│
└── data/                    # 数据目录
    ├── documents/           # 知识文档（.txt）
    ├── vector_store/        # FAISS 索引
    └── memory/              # 记忆存储
```

## 工作流

```
用户输入 → 意图识别 → 记忆检索 → 行动规划 → 工具执行 → 答案生成 → 反思存档
              │                          │
              ├─ calorie_query            ├─ 知识库检索
              ├─ meal_planner             └─ 联网搜索
              ├─ followup（追问）
              ├─ web_search
              └─ general
```

## 快速开始

### 1. 环境要求

- Python >= 3.12
- 智谱AI API Key（[获取地址](https://open.bigmodel.cn/)）

### 2. 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

### 3. 配置环境变量

在 `.env` 文件中填写：

```env
ZHIPUAI_API_KEY=your_api_key_here
TAVILY_API_KEY=your_tavily_key     # 可选，用于联网搜索
NEO4J_URI=bolt://localhost:7687    # 可选，用于 GraphRAG
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

### 4. 准备知识文档

将 `.txt` 格式的知识文档放入 `data/documents/` 目录，首次运行时自动构建向量索引。

### 5. 启动

**CLI 模式：**

```bash
python main.py
```

**Web 模式：**

```bash
python front/app.py
# 访问 http://localhost:5000
```

## 配置说明

主要配置项在 `config.py` 中，通过 Pydantic Settings 管理：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `llm_model` | `glm-4-flash` | 智谱 LLM 模型 |
| `embedding_model` | `embedding-2` | 智谱 Embedding 模型 |
| `short_term_size` | `10` | 短期记忆保留轮数 |
| `long_term_top_k` | `5` | 长期记忆检索数量 |
| `use_graphrag` | `False` | 是否启用 GraphRAG |
| `enable_mcp` | `True` | 是否启用 MCP |

## 可选服务

- **联网搜索** — 需配置 `TAVILY_API_KEY`，用于实时信息查询
- **GraphRAG** — 需运行 Neo4j 并配置连接信息，用于食物搭配关系图查询
- **MCP Server** — 运行 `python mcp_servers/local_server.py` 启动本地 MCP 服务

## License

MIT
