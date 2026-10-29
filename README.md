# 轻松食 · Agentic RAG 智能营养助手

基于 **智谱AI + LangChain + LangGraph** 的智能检索增强生成（RAG）Agent，专注于食物热量查询与餐食搭配推荐。

## 核心特性

- **意图识别** — 自动判断用户意图（热量查询 / 餐食规划 / 追问 / 联网搜索 / 通用问答）
- **知识库检索** — 基于 FAISS 向量库的语义检索，支持相似度阈值过滤
- **联网搜索** — 集成 Tavily 搜索引擎，支持实时信息查询
- **多轮对话** — 短期记忆 + 长期记忆（FAISS 向量化），支持追问与上下文关联
- **GraphRAG** — 可选 Neo4j 图检索，支持食物搭配关系查询
- **MCP 协议** — 提供本地 MCP Server，支持外部工具调用
- **Web 界面** — FastAPI API + 移动端优先 React 界面，开箱即用

## 实施记录

已完成阶段的实际改动、对应 Git 提交、测试结果和已知边界，见：[项目实施记录](docs/implementation-record.md)。

后续开发的唯一主线和优先级清单见：[项目实施主线](docs/implementation-roadmap.md)。其中 `P0-5` 专指 Grill v1 产品化；历史记录中的 `P05` 企业级运行保障是另一套已完成的阶段编号。

## 项目结构

```
agent1/
├── main.py                  # CLI 入口（调用统一 ConversationRuntime）
├── config.py                # 全局配置（Pydantic Settings）
├── .env.example             # 本地配置模板（真实 .env 不入 Git）
├── requirements.txt         # 依赖清单
├── pyproject.toml           # 项目元数据、pytest 与工具配置
├── Dockerfile               # 应用镜像构建
├── docker-compose.yml       # 本地小型平台编排
├── alembic.ini              # 数据库迁移入口
│
├── agent/                   # Agent 核心
│   ├── agent_executor.py    # 旧入口兼容适配器，转发到统一 Workflow
│   ├── tools.py             # 工具定义（知识库检索、联网搜索）
│   └── prompt.py            # ReAct 提示模板
│
├── core/                    # 工作流与记忆
│   ├── conversation_runtime.py # Web、CLI、兼容入口共用的会话运行时
│   ├── tool_registry.py     # 统一工具注册与执行边界
│   ├── workflow.py          # LangGraph 状态图（意图识别→记忆检索→Grill→规划→执行→生成）
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
├── front/                   # FastAPI API 包
│   ├── app.py               # API、认证、会话和健康检查入口
│   └── schemas.py           # API 请求/响应模型
│
├── frontend/                # 新版 React 移动端优先前端（生产由 5000 托管，开发可用 5173）
│   ├── src/                 # 页面、组件、API service 和设计令牌
│   ├── docs/                # 设计系统和 UI 验收记录
│   └── README.md            # 前端启动与接口说明
│
├── config/grill_profiles/   # Grill 任务画像配置
├── migrations/              # Alembic 数据库迁移
├── scripts/                 # 启停、迁移、备份与 Docker 运维脚本
├── tests/                   # 全部自动化测试（单元、集成、浏览器）
├── evaluation/              # RAG / Grill 评测样例
├── docs/                    # 实施主线、阶段记录和专项说明（入口见 docs/README.md）
├── deploy/                  # 可选 Kubernetes/监控部署清单
└── data/                    # 本地运行数据（索引与知识文档）
    ├── documents/           # 知识文档（.txt）
    ├── vector_store/        # FAISS 索引
    └── memory/              # 记忆存储
```

## 工作流

```
Web / CLI / 兼容入口
          ↓
ConversationRuntime
          ↓
LangGraph Workflow
          ↓
意图识别 → 记忆检索 → Grill 信息完整性检查 → 行动规划
                                      ↓
                              Tool Registry
                          ┌──────────┼──────────┐
                     知识库检索   联网搜索   餐食/热量工具
                                      ↓
                              答案生成 → 反思存档
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
copy .env.example .env      # Windows
# cp .env.example .env      # Linux/macOS
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

**Web 模式（单端口）：**

```bash
cd frontend
npm ci
npm run build
cd ..
python front/app.py
# 访问 http://localhost:5000；FastAPI 同时提供 API 和 React 页面
```

**React 开发模式（可选）：**

```bash
cd frontend
npm ci
copy .env.example .env.local  # Windows
npm run dev
# 访问 http://localhost:5173；仅用于前端热更新开发
```

React 前端是项目唯一的 Web 界面；生产构建由 FastAPI 在 `5000` 端口托管，`front/` 仅提供 API 和静态文件托管。真实接口默认关闭 mock；只有将 `VITE_USE_MOCK_API=true` 写入 `frontend/.env.local` 时才使用本地预览数据。

**Docker 模式：**

```bash
docker compose up -d --build
# 访问 http://localhost:5000
```

### 6. 测试

```bash
pytest -m "not e2e"       # 默认测试集
pytest -m e2e              # 浏览器验收，需要已启动服务和 Playwright
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
