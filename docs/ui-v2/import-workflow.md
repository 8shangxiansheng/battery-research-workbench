# 新建实验向导（Import Workflow）

6 步：实验信息 → 数据资产 → 格式检测 → 预览与验证 → 科学元数据 → 提交与启动。

1. **实验信息**：Battery ID 必填；Experiment ID 可留空（API 自动 EXP_%03d）；名称必填。
   身份不从文件名推断。
2. **数据资产**：Electrical(.xlsx) + Ultrasound(.txt) 分区上传（file picker；
   drag/drop 区域同源）。全部走 `POST /intake-sessions/{sid}/assets`，显示 role/filename/size/sha256。
3. **格式检测**：`POST /detect`（BRW-007 registry）。
   - DETECTED_UNIQUE → 继续
   - DETECTED_AMBIGUOUS → 歧义面板（必须人工选择，不静默）
   - UNSUPPORTED → 支持能力说明（electrical=.xlsx / ultrasound=.txt）+ 阻断
4. **预览与验证**：三维度分离显示 FORMAT_VALIDITY / SCIENTIFIC_METADATA_COMPLETENESS /
   PIPELINE_READINESS。`sampling_rate_hz = UNKNOWN` 显示 ⚠ 但不阻断 commit。
5. **科学元数据**：突出 sampling rate；其余（trigger/path length 等）折叠；
   "稍后提供"并注明影响（TOF 将暂不可用）。
6. **提交与启动**：提交前 summary → `确认并导入` → Raw registered / Checksums verified /
   READY_FOR_PIPELINE → 用户明确点击 `开始数据处理`（POST /runs INGEST_TO_MEASUREMENT_EVENTS）或 `稍后`。

会话 ID 在 URL（/new/:sessionId），刷新可恢复。
