# OSI-001 — BEEP + cellpy Neware Compatibility Task Pack

把整个任务包放到：

```text
battery-research-workbench/
└── tasks/
    └── OSI-001/
```

然后让 Coding Agent：

1. 先读 `AGENTS.md`
2. 再读 `tasks/OSI-001/01_MASTER_PROMPT.md`
3. 第一轮只做环境与 API Inspect
4. 第二轮才创建隔离 uv 环境并运行 compatibility spike
5. 不修改 BRW-003/004 主实现，除非用户后续明确批准

---

## 目标

回答一个具体问题：

> 对当前 Neware 电池测试数据，cellpy 和 BEEP 到底能替 Battery Research Workbench 减少多少解析、分析和绘图开发量？

不是：

> 立刻把已有 Custom Parser 删除。

---

## 当前工作台 baseline

已经完成：

```text
BRW-003 Electrical XLSX Parser ✅
BRW-004 Electrical QA ✅
BRW-005 Ultrasound TXT Parser ✅
BRW-006 Ultrasound QA ✅
```

当前 Electrical Golden baseline：

```text
CELL_001 / EXP_001
records = 39996
cycles = 2
steps = 10
aux_temperature = 39996
aux_voltage = 39996
cycle_ids_raw = [1,2]
step_ids_raw = [1,2,3,4,5]
timestamp = 2024-01-06 09:52:31 → 20:58:54
```

原始 Neware workbook 包含：

```text
unit
test
cycle
step
record
auxVol
auxTemp
...
```

---

## 当前依赖兼容性注意

截至本任务包创建时：

```text
cellpy latest:
Python >= 3.13

BEEP 2026.2.7:
Python >= 3.11
```

因此 OSI-001 默认使用：

```text
Python 3.13
```

隔离实验环境。

不要在本轮直接迁移主 Workbench 的 Python 版本。
