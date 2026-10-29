# 测试目录

所有自动化测试集中在这里，文件名保留阶段前缀，便于从实施记录追溯到对应测试。

```bash
pytest -m "not e2e"  # 单元与集成测试
pytest -m e2e         # 浏览器验收，需先启动本地服务
```

测试依赖项目根目录运行；`pyproject.toml` 已将 `tests/` 配置为 pytest 的唯一测试目录。
