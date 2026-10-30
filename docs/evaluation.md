# 评测体系使用说明

当前评测体系服务于小型平台的日常回归和提交门禁，目标是发现检索命中、追问决策和安全边界回退，而不是把模型分数包装成生产指标。

## 当前实现

评测数据统一由 `core.contracts.EvalCase` 描述，旧版 fixture 仍可以使用：

- `evaluation/rag_cases.json`：RAG 来源证据和查询改写用例；
- `evaluation/grill_cases.json`：Grill 追问、执行、拒答和上下文续接用例；
- `evaluation/fixtures/rag_corpus.json`：固定的 RAG 评测语料，不依赖个人本地知识库或 FAISS 索引。

`evaluation/dataset.py` 在加载阶段把 Grill 的旧 `name/task` 字段转换为 `case_id/expected_task`，再由 Pydantic 严格校验。当前共 82 条用例：18 条 RAG、64 条 Grill。

## 本地运行

使用仓库的 Python 3.12 环境运行确定性评测：

```text
.venv\Scripts\python.exe -m evaluation.runner --suite all --mode deterministic
```

提交前使用质量门槛：

```text
.venv\Scripts\python.exe -m evaluation.runner --suite all --mode deterministic --min-rag-recall 0.90 --min-grill-accuracy 0.90 --max-invalid-retrieval-rate 0.15 --min-safety-pass-rate 0.90
```

默认报告写入 `evaluation/reports/latest.json`。报告是运行产物，已加入 `.gitignore`，包括：

- 当前 commit SHA、运行时间和模式；
- 总用例、通过/失败数；
- RAG Recall@K、MRR、来源覆盖率、无效检索率；
- Grill action accuracy、追问字段准确率、过早回答率、过度追问率；
- 安全门禁准确率、必须包含内容覆盖率、禁止内容违规率和禁止动作违规率；
- 每条用例的检查项、实际来源/动作和失败原因。

## RAGAS 模式

RAGAS 只用于手动或定时的答案质量评测，不进入普通 push CI。因为 RAGAS 需要模型回答，系统不自动生成或上传回答；先准备一个本地 JSON 文件：

```json
{
  "rag-protein-source": {
    "answer": "鸡胸肉是常见的优质蛋白质来源。",
    "reference": "鸡胸肉是常见的优质蛋白质来源。"
  }
}
```

安装可选依赖后运行：

```text
.venv\Scripts\python.exe -m pip install -e ".[eval]"
.venv\Scripts\python.exe -m evaluation.runner --suite rag --mode ragas --answers-file path\to\answers.json
```

当前 RAGAS 适配器评估 Faithfulness、Context Precision、Context Recall 和 Answer Relevancy。接入实际模型时，应把回答文件作为一次评测快照保存，不要把 API Key、真实用户对话或个人健康档案提交到仓库。LangSmith 尚未接入代码，不能把它作为当前已完成能力对外描述。

## CI 门禁

`.github/workflows/ci.yml` 的 `test` job 在普通测试之后运行确定性评测：

- RAG Recall@K 至少 `0.90`；
- Grill action accuracy 至少 `0.90`；
- 无效检索率不高于 `0.15`。
- 安全用例通过率至少 `0.90`。

评测失败会使 CI 失败。由于该路径只使用固定语料和规则引擎，不依赖外部模型，提交结果稳定且不会产生额外 API 成本。

## 扩充规则

新增用例时优先补充真实缺陷的最小复现，并至少填写 `case_id`、`question`、`suite`、期望动作或期望来源。涉及安全边界时同时填写 `must_not_execute`、`must_include` 或 `must_not_include`。先让确定性评测通过，再把需要模型判断的答案质量放到 RAGAS 快照中；不直接把用例数量写成未经数据支持的“100 条”。
