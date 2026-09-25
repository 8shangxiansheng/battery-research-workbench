# 原始数据 → 特征表链路正确性审计（2026-09-24）

范围：CELL_001/EXP_001 canonical 链。方法：独立重算 + 逐段对账 + 阶段测试门禁，不依赖既有绿灯自证。

## 逐段核对结果

| 段 | 核对 | 结果 |
|---|---|---|
| 超声 TXT parser | 3999 非空行 = 3999 帧；六段结构（元数据3 + 波形1250 + 尾段16）抽查零违例；首/尾 elapsed 与契约 golden facts 一致；`source_line_index` 为 **1-based** 非空行号 | ✓ |
| 波形保真 | 随机 30 帧：原始行第 5 段独立解析 ↔ zarr `U001/waveform` 按 `(waveform_group, waveform_row_index)` 逐字节相等 | ✓ |
| 电学 XLSX | record sheet 39997 行 = 39996 records + 表头；时间戳单调；9 组重复时间戳（20 行）如实入表 | ✓ |
| 同步 | 3995 `MATCHED_UNIQUE` + 4 `MATCHED_AMBIGUOUS`（DUPLICATE_ELECTRICAL_TIMESTAMP：帧 691/1914/2094/3998）；`sync_error_s` 全帧持久化；0.030–0.0312 s 恰好等于超声帧相对 1 s 电学栅格的相位偏移，物理自洽 | ✓ |
| 资格闸 | 4 歧义帧 `analysis_eligible=False` 且带原因；下游特征表恰为 3999−4=3995 行；label 表 null 行与歧义事件集完全一致 | ✓ |
| 特征表 | 独立重算 rms/max/min/mean/p2p ↔ FS::60649fd 值 30 帧全匹配（<1e-9） | ✓ |
| 数据集 | DS::83013a 3995×63；manifest 携带 FS/LB 路径 + checksum + builder 版本 | ✓ |
| 测试门禁 | parser/qa/sync/measurement/import/manifest 关键词命中 258 项全绿 | ✓ |

审计过程中的第一次"不匹配"是审计脚本自身把 `source_line_index` 当 0-based 使用所致（帧整体错位一行），修正映射后全部一致——记录在案避免后人重踩。

## 发现并已修复（同轮 commit）

波形页顶栏"参考 SOC"恒为 "—"：参考 SOC 属标签工件（`event_labels.parquet`），
但 UI 读的是事件行上从未被填充的 `soc_reference_percent`。修复为在
`GET /measurement-events` 按 `measurement_event_id` 只读联查 label 表，
meta 标注 `soc_reference_label_source`；歧义/无标签事件保持 null，不猜测、
不与电学原始 `soc_dod_percent` 混用。前端 header 断言 + 后端联读测试同步落地；
浏览器实测帧 2001 显示 `参考 SOC 0.12%`（label=0.1231）。

## 结论

raw → parser → QA → sync → MeasurementEvent → feature/label/dataset 各段的
行身份、数值、不确定性记账与资格排除均正确；唯一缺陷为展示层取数来源，已修复。
