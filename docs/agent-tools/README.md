# Agent Scientific Tool Layer (BRW-026)

Agent 只能经 `AgentToolRegistry → ToolGateway → WorkbenchService / IntakeEngine → 科学核心` 调用
确定性科学代码。工具层自身**不计算**任何科学量（SOC/TOF/相关系数/metrics）。

## 快速开始

```python
from battery_workbench.api.app import create_app
from battery_workbench.agent_tools.gateway import ToolGateway
from battery_workbench.agent_tools.models import AgentScientificContext

service = create_app(raw_root=..., processed_root=...).state.workbench_service
gateway = ToolGateway(service=service)
ctx = AgentScientificContext(battery_id="CELL_001", experiment_id="EXP_001")
result = gateway.execute("list_experiments", ctx, {})
```

## 文件

| 文件 | 内容 |
|---|---|
| `agent_tool_manifest.json` | 36 个工具的完整 metadata 清单 |
| `tool-schema-v1.json` | tool contract v1.0.0 schema |
| `tool-catalog.md` | 按类别的工具目录 |
| `confirmation-policy.md` | 三级确认策略 |
| `scientific-safety.md` | 科学安全边界 |
