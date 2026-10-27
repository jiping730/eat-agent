# P1-1 实施记录：RAG 检索质量升级

## 阶段目标

在小型平台边界内，建立一条可重复构建、可回滚、带权限过滤和来源证据的本地 RAG 检索链路。开发环境继续使用本地文件和 FAISS，不引入 Qdrant、pgvector、异步任务队列或在线知识库后台。

## 实际实现

### 1. 文档入库

- 新增 `rag/ingestion.py`。
- 支持 `.txt` 文件读取、BOM/空白/换行清洗、段落拆分、长段落按大小和重叠切块。
- 以规范化内容去重，避免同一知识片段重复进入索引。
- 为每个片段写入 `source`、`title`、`document_id`、`content_hash`、`version`、`chunk_id` 和 `access_groups`。
- 提供命令行入口：

  ```bash
  python -m rag.ingestion --source data/documents --index data/vector_store --version v1
  ```

  需要控制访问组时可重复指定 `--access-group public --access-group nutrition`。

### 2. 版本发布和回滚

- 版本内容写入 `versions/<version>/manifest.json` 和 `versions/<version>/corpus.json`。
- 使用临时目录、文件 fsync 和原子重命名，避免发布过程中暴露半成品。
- `current.json` 是当前版本指针，发布只切换指针，不删除旧版本。
- `rollback_version(index_dir, version)` 通过校验完整版本后切回旧版本。

### 3. 混合召回和重排

- 查询先经过确定性改写：NFKC、大小写归一，以及常见营养词同义词归一。
- 纯 Python BM25 风格词法召回保证离线可用；存在 FAISS 索引时再加入向量召回。
- 两路结果按文档片段 ID 合并，保留 lexical、vector 或 hybrid 的来源方法。
- 默认重排器基于查询词覆盖率、短语命中和标题命中进行轻量排序，不需要模型 Key 或额外服务。
- 重排器单独暴露为 `rerank_documents()`，后续可替换 BGE/Cohere 而不影响 Tool Registry 和 API 契约。

### 4. 权限和证据

- 检索器支持 `access_groups`，在排序前过滤不允许访问的片段。
- `retrieve_with_contract()` 输出 `RetrievalResponse`，其中包含 `RetrievedDocument`、`SourceRef`、查询 ID 和结构化状态。
- 旧的 `retrieve_knowledge()` 文本接口继续保留，保证现有 Agent 和工具调用兼容。
- Tool Registry 结果增加来源文件、标题、文档 ID、版本、片段 ID和检索分数。

### 5. 黄金评测

- 新增 `evaluation/rag_cases.json`，用固定问题和期望来源描述黄金样例。
- 新增 `test_p1_rag_eval.py`，验证期望来源进入 Top-K，而不是只验证检索返回非空。
- 评测集当前覆盖蛋白质来源、卡路里同义词、减重同义词和过敏原安全问题。

## 验收记录

- P1-1 专项与公共契约测试：`11 passed`。
- RAG 清洗、去重、版本发布、回滚、词法召回、向量兼容、查询改写、权限过滤、重排元数据和来源证据均有测试。
- Python 3.12 容器环境执行测试，避免本机 Python SSL 动态库问题影响结果。
- `rag/ingestion.py`、`rag/retriever.py` 已执行 Black 格式化，并纳入 CI 的 Black、isort、Mypy 检查范围。

## 交付边界

本阶段完成的是小型平台可交付版本。默认重排器是可解释的本地规则，不等同于 BGE/Cohere 模型重排；FAISS 是可选增强，未把向量服务作为运行前置条件。生产规模扩大后，再按实际数据量选择 pgvector/Qdrant、模型重排、异步索引构建和管理后台。
