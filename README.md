# Agent1 项目

基于智谱AI和LangChain的智能检索增强生成（RAG）Agent。

## 目录结构

- `config.py` - 配置管理
- `main.py` - 主程序入口
- `utils/` - 工具模块（性能统计、回调）
- `rag/` - 检索增强生成核心组件
- `agent/` - Agent逻辑（工具、提示、执行器）
- `data/documents/` - 存放知识文档（.txt）

## 快速开始

1. 安装依赖：`pip install -r requirements.txt`
2. 在 `.env` 中填写智谱API密钥
3. 将知识文档放入 `data/documents/`
4. 运行 `python main.py`
