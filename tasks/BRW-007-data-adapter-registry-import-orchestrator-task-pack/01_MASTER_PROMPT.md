# BRW-007 Master Vibe Coding Prompt

你正在维护：

```text
battery-research-workbench
```

当前已完成：

```text
BRW-003 Electrical XLSX Parser ✅
BRW-004 Electrical QA ✅
BRW-005 Ultrasound TXT Parser ✅
BRW-006 Ultrasound QA ✅
```

现在执行：

> **BRW-007 — Data Adapter Registry & Experiment Import Orchestrator**

---

# 0. 开始前先阅读

必须依次阅读：

1. `AGENTS.md`
2. `README.md`
3. `docs/development-plan.md`
4. `docs/architecture/system-architecture.md`
5. `docs/data_contract/manifests.md`
6. `docs/data_contract/electrical_xlsx.md`
7. `docs/data_contract/ultrasound_txt.md`
8. 当前 domain：
   - `battery.py`
   - `experiment.py`
   - `asset.py`
9. 当前 registries：
   - `battery_registry.py`
   - `experiment_registry.py`
   - `asset_registry.py`
10. 当前：
   - `src/battery_workbench/io/electrical/`
   - `src/battery_workbench/io/ultrasound/`
   - `src/battery_workbench/io/experiment/`
11. BRW-003 public service API
12. BRW-005 public service API
13. 当前 tests
14. 当前 manifests

第一轮只 Inspect，不修改代码。

---

# 1. Task

实现：

```text
DataAdapter abstraction
+
DataAdapterRegistry
+
ExperimentImportPlan
+
Experiment Import Orchestrator
```

目标是让上层以后统一调用：

```python
plan_experiment_import(...)
import_experiment(...)
```

而不是分别手工调用：

```python
parse_electrical_experiment(...)
parse_ultrasound_experiment(...)
```

---

# 2. Architecture

最终形成：

```text
CLI / API / Notebook / Agent
           ↓
ExperimentImporter
           ↓
ExperimentImportPlan
           ↓
AdapterRegistry
      /          \
     ↓            ↓
Electrical     Ultrasound
Adapter        Adapter
     ↓            ↓
Existing BRW Parser Services
           ↓
ExperimentImportResult
```

---

# 3. Core principle

Adapter 不重新实现 Parser。

## ElectricalAdapter

只包装已有：

```text
BRW-003 electrical service
```

禁止：

- 重新 openpyxl
- 复制 column mapping
- 重新写 parquet
- 重写 cycle/step parsing

## UltrasoundAdapter

只包装已有：

```text
BRW-005 ultrasound service
```

禁止：

- 重新 split TXT
- 重新解析 waveform
- 重新实现 Zarr writer

---

# 4. Recommended repository structure

新增：

```text
src/battery_workbench/io/adapters/
├── __init__.py
├── base.py
├── registry.py
├── electrical.py
└── ultrasound.py
```

必要时新增：

```text
src/battery_workbench/io/experiment/schemas.py
```

重点修改：

```text
src/battery_workbench/io/experiment/importer.py
```

---

# 5. DataAdapter interface

推荐 Protocol 或 ABC。

接口至少：

```python
class DataAdapter(Protocol):
    modality: str

    def supports(self, asset: DataAsset) -> bool:
        ...

    def import_assets(
        self,
        *,
        battery: BatteryCell,
        experiment: Experiment,
        assets: list[DataAsset],
        raw_root: Path,
        processed_root: Path,
        overwrite: bool = False,
    ) -> ModalityImportResult:
        ...
```

粒度必须是：

```text
Experiment + modality + multiple assets
```

因为：

```text
1 Experiment
可以有多个 electrical XLSX
可以有多个 ultrasound TXT
```

---

# 6. Unified result models

定义：

```text
AssetImportResult
ModalityImportResult
ExperimentImportPlan
ExperimentImportResult
```

不要返回 loose dict。

优先：
- Pydantic
- 或现有 typed dataclass 体系

---

# 7. ExperimentImportResult

至少：

```text
battery_id
experiment_id

requested_modalities
imported_modalities
skipped_modalities
unsupported_modalities

source_asset_ids

modality_results

output_paths

warnings
errors

status
```

status：

```text
SUCCESS
PARTIAL
FAILED
```

---

# 8. ModalityImportResult

至少：

```text
modality
adapter_name
adapter_version

asset_ids
status

output_paths
warnings
errors
```

---

# 9. Adapter Registry

实现：

```python
DataAdapterRegistry
```

至少：

```python
register(adapter)
get(modality)
has(modality)
modalities()
```

要求：

1. duplicate modality registration → 明确异常
2. unknown modality → 明确异常
3. 异常包含 modality
4. 不使用巨型 `if/elif`

禁止最终架构：

```python
if modality == "electrical":
    ...
elif modality == "ultrasound":
    ...
```

---

# 10. Default registry

实现：

```python
build_default_adapter_registry()
```

默认注册：

```text
electrical
ultrasound
```

以后可无侵入增加：

```text
eis
thermal
strain
pressure
acoustic_emission
```

无需修改 importer 主编排逻辑。

---

# 11. ElectricalAdapter

```text
modality = "electrical"
```

supports：

```python
asset.modality == "electrical"
```

import_assets：

必须调用现有 BRW-003 public service。

返回统一：

```text
ModalityImportResult
```

---

# 12. UltrasoundAdapter

```text
modality = "ultrasound"
```

必须调用现有 BRW-005 public service。

不复制 TXT parser。

---

# 13. Experiment Importer

把：

```text
io/experiment/importer.py
```

从 placeholder 变为真正 orchestrator。

推荐高层 API：

```python
plan_experiment_import(
    experiment_id: str,
    *,
    raw_root: Path,
    processed_root: Path,
    registry: DataAdapterRegistry | None = None,
    modalities: set[str] | None = None,
) -> ExperimentImportPlan
```

和：

```python
import_experiment(
    experiment_id: str,
    *,
    raw_root: Path,
    processed_root: Path,
    registry: DataAdapterRegistry | None = None,
    modalities: set[str] | None = None,
    overwrite: bool = False,
    strict: bool = False,
) -> ExperimentImportResult
```

如果现有 registry API 更适合直接传 Experiment，
可做合理适配，但必须保留统一高层入口。

---

# 14. Orchestration logic

Importer 流程：

```text
resolve Experiment
↓
resolve Battery
↓
resolve DataAssets
↓
optional modality filtering
↓
group assets by modality
↓
resolve adapter
↓
adapter.import_assets(...)
↓
collect results
↓
ExperimentImportResult
```

Importer 不知道：

```text
XLSX column
TXT semicolon
waveform 1250 samples
```

这些属于下层 Parser。

---

# 15. Grouping

必须：

```text
group by asset.modality
```

例如：

```text
E001 electrical
E002 electrical
U001 ultrasound
U002 ultrasound
```

调用：

```text
ElectricalAdapter → [E001, E002]
UltrasoundAdapter → [U001, U002]
```

每 modality 一次。

---

# 16. Unknown modality policy

例如：

```text
EIS01 modality=eis
```

但没有 EISAdapter。

## strict=False

要求：

```text
known modality 正常 import
unknown modality 记录 UNSUPPORTED_MODALITY
overall = PARTIAL
```

禁止 silent ignore。

## strict=True

允许：

```text
raise / FAILED / fail-fast
```

但行为必须明确并有测试。

---

# 17. Failure isolation

例如：

```text
ElectricalAdapter SUCCESS
UltrasoundAdapter FAILED
```

默认：

```text
ExperimentImportResult.status = PARTIAL
```

并保留成功的 electrical result。

禁止：

> 一个 modality 失败后把已经成功的信息丢掉。

strict mode 可以 fail-fast。

---

# 18. Dry-run

强烈要求实现：

```text
dry-run / planning
```

推荐独立：

```python
plan_experiment_import(...)
```

dry-run 不写文件、不调用 parser。

只生成：

```text
Experiment
DataAssets
groups
resolved adapters
expected outputs
unsupported modalities
```

这为未来：

```text
Agent plan
→ human approval
→ execute
```

铺路。

---

# 19. ExperimentImportPlan

至少：

```text
battery_id
experiment_id

modalities
asset_groups

adapter_assignments

expected_output_paths

unsupported_modalities

warnings
```

---

# 20. Output existence / overwrite policy

当前已存在：

```text
data/processed/electrical/...
data/processed/ultrasound/...
```

不要静默重写。

## overwrite=False

优先：

```text
existing output
→ skip + report
```

或明确 `AlreadyImportedError`。

建议第一版：

```text
skip_existing
```

这样 real-data integration 更安全。

## overwrite=True

只有用户显式要求才重新生成。

如果下层 service 没有安全 overwrite 参数，
不要为了 BRW-007 大改 BRW-003/005。

---

# 21. Expected output paths

Plan 中应能预测：

```text
electrical:
data/processed/electrical/{battery_id}/{experiment_id}/

ultrasound:
data/processed/ultrasound/{battery_id}/{experiment_id}/
```

不要硬编码到 importer 多处分散。

建议 adapter 自己暴露：

```python
expected_output_paths(...)
```

或 registry/service helper。

---

# 22. Provenance

Importer result 必须保留：

```text
battery_id
experiment_id
asset_ids
modality
adapter_name
adapter_version
output_paths
```

Adapter provenance 不替代 parser provenance。

最终链：

```text
Battery
↓
Experiment
↓
DataAsset
↓
DataAdapter
↓
Parser
↓
Processed Artifact
```

---

# 23. Error model

不要只返回字符串。

推荐结构化：

```json
{
  "code": "UNSUPPORTED_MODALITY",
  "modality": "eis",
  "asset_ids": ["EIS01"],
  "message": "..."
}
```

错误类型至少考虑：

```text
UNSUPPORTED_MODALITY
ADAPTER_FAILURE
ALREADY_IMPORTED
INVALID_ASSET_GROUP
EXPERIMENT_NOT_FOUND
BATTERY_NOT_FOUND
```

---

# 24. Logging

使用现有 logging 风格。

记录：

```text
battery_id
experiment_id
modality
asset_ids
adapter_name
status
```

不要 dump DataFrame / waveform。

---

# 25. Tests FIRST

先测试再实现。

必须：

## T01 Adapter interface

FakeAdapter 可注册/调用。

## T02 Registry register/get

## T03 Duplicate registration

Expected fail。

## T04 Unknown modality lookup

Expected explicit error。

## T05 Default registry

包含：

```text
electrical
ultrasound
```

## T06 Group by modality

## T07 Multi-asset same modality

```text
E001
E002
```

只调用 ElectricalAdapter 一次，
assets count=2。

## T08 Multi-modality experiment

```text
electrical
ultrasound
```

两个 adapter 均被调用。

## T09 Unknown modality non-strict

Expected：

```text
PARTIAL
```

## T10 Unknown modality strict

Expected：

```text
FAILED / exception
```

按统一设计。

## T11 One adapter fails

另一个成功。

Expected：

```text
PARTIAL
```

## T12 All success

Expected：

```text
SUCCESS
```

## T13 Existing outputs

overwrite=False：

```text
skip/report
```

不能静默覆盖。

## T14 overwrite=True

验证明确执行路径。

## T15 Provenance

asset IDs、adapter、output path 正确。

## T16 Dry-run

不调用 parser。

## T17 Dry-run unsupported modality

明确出现在 plan 中。

## T18 Real CELL_001 integration

当前 manifests：

```text
E001 electrical
U001 ultrasound
```

Plan 应解析：

```text
E001 → ElectricalAdapter
U001 → UltrasoundAdapter
```

因为已有 processed outputs，
integration 默认：

```text
plan only
或 overwrite=False skip-existing
```

不要破坏 Golden outputs。

---

# 26. Parser regression guard

必须确认：

BRW-007 没改变：

```text
BRW-003 output semantics
BRW-005 output semantics
```

运行完整 pytest。

如测试数量变化，报告。

---

# 27. Current real dry-run expected result

至少类似：

```text
ExperimentImportPlan

battery_id: CELL_001
experiment_id: EXP_001

electrical:
  adapter: ElectricalAdapter
  assets: [E001]

ultrasound:
  adapter: UltrasoundAdapter
  assets: [U001]

unsupported_modalities: []
```

如果当前 manifest 已变化，
报告变化，不硬改 expected。

---

# 28. Recommended public boundary

以后：

```text
CLI
API
Notebook
Agent
```

只依赖：

```text
Experiment Import Service
```

不直接依赖：

```text
CustomExcelParser
CustomTxtParser
```

---

# 29. No production Agent yet

虽然 dry-run / plan 为 Agent 铺路，
但本轮不实现：

```text
LangGraph
Tool Registry
LLM
Human approval UI
```

只准备确定性 API。

---

# 30. Scope guard

禁止：

- 修改 electrical parser algorithm
- 修改 ultrasound parser algorithm
- 修改 electrical QA
- 修改 ultrasound QA
- synchronization
- cycle mapping
- time anchor
- drift
- feature extraction
- ML
- Agent
- UI
- BEEP
- cellpy

---

# 31. Quality gates

完成后：

```bash
pytest
ruff check <本次修改文件>
ruff format --check <本次修改文件>
mypy src
git diff --check
```

不要顺手修 unrelated lint debt。

---

# 32. Final handoff

最终必须报告：

## Status
PASS / PARTIAL / FAIL

## Files changed

## Adapter interface

## Adapter registry

注册：

```text
electrical
ultrasound
```

## Experiment Importer

说明：
- plan
- execute
- grouping
- strict/non-strict
- failure isolation
- overwrite policy

## Current CELL_001 dry-run

明确：

```text
E001 → ElectricalAdapter
U001 → UltrasoundAdapter
```

## Existing-output behavior

## Provenance

## Tests

pytest / coverage / ruff / format / mypy / git diff

## Regression confirmation

确认 BRW-003/005 行为没被改变。

## Known limitations

未实现：

- synchronization
- new modalities
- Agent
- UI

完成后停止，不进入 BRW-008。
