# Recommended Vibe Coding Sequence

不要一次让 Agent 写完所有东西。

## Prompt 1 — Inspect only
让 Agent：
- 读文档
- 检查当前两个真实 XLSX / manifest
- 输出 schema discovery
- 不改代码

人工确认后继续。

## Prompt 2 — Tests only
让 Agent：
- 写 synthetic workbook tests
- 写 golden/integration test scaffolding
- 不实现 parser 主逻辑

运行测试，应当有合理的 failing tests。

## Prompt 3 — Single asset parser
实现：
- `column_mapping.py`
- `schemas.py`
- `custom_excel.py`
- 单个 DataAsset parsing

只让相关 tests 通过。

## Prompt 4 — Experiment service
实现：
- 多 Electrical DataAsset
- provenance
- sort
- overlap diagnostics

## Prompt 5 — Parquet writer
实现标准输出和 manifest。

## Prompt 6 — Real-data validation
真正运行 CELL_001 数据，输出报告。

## Prompt 7 — Cleanup
只做：
- ruff
- type hints
- docs
- no unrelated refactor

这种方式比“一句话实现 BRW-003”更安全。
