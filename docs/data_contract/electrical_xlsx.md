# Electrical XLSX Data Contract — v0.1

Source example: `小-1-1-264.xlsx`

## Workbook sheets

| Sheet | Rows | Columns | Role |
|---|---:|---:|---|
| `unit` | 7 | 9 | supporting table |
| `test` | 18 | 23 | supporting table |
| `cycle` | 3 | 39 | supporting table |
| `step` | 19 | 41 | supporting table |
| `record` | 39997 | 29 | primary time series |
| `log` | 3 | 5 | supporting table |
| `idle` | 1 | 8 | supporting table |
| `auxVol` | 39998 | 4 | supporting table |
| `auxTemp` | 39998 | 4 | supporting table |
| `curve` | 1 | 1 | supporting table |

这里的 Rows/Columns 是 Excel 的物理维度，不等同于 canonical 输出行数。当前样例中：

- `record` 为 1 行表头 + 39996 条数据；
- `cycle` 为 1 行表头 + 2 条数据；
- `step` 为 1 行表头 + 10 条有效 Step 数据，尾部另有 6 个全空格式化行，以及 2 个只有 `容量(Ah)` 的非表格残留行；
- `auxTemp` / `auxVol` 均为 2 行表头 + 39996 条数据，canonical 表头位于第 2 行。

## Confirmed primary table: `record`

Confirmed columns from the real file:

`数据序号, 循环号, 工步号, 工步开始结束标识, 工步类型, 时间, 总时间, 电流(A), 电压(V), 容量(Ah),
比容量(mAh/g), 充电容量(Ah), 充电比容量(mAh/g), 放电容量(Ah), 放电比容量(mAh/g),
能量(Wh), 比能量(mWh/g), 充电能量(Wh), 充电比能量(mWh/g), 放电能量(Wh),
放电比能量(mWh/g), 绝对时间, 功率(W), dQ/dV(mAh/V), dQm/dV(mAh/V.g),
接触电阻(mΩ), 模块启停开关, SOC/DOD(%), LgD`

## Supporting tables

- `cycle`: cycle-level capacity/energy/efficiency/temperature summary
- `step`: step-level charge/discharge/rest/DCIR summary
- `auxTemp`: T1 temperature time series
- `auxVol`: V1 auxiliary voltage time series
- `unit`, `test`, `log`, `idle`, `curve`: metadata/support

## Timestamp behavior

当前 `record`、`auxTemp` 和 `auxVol` 时间戳是 non-decreasing，而不是严格递增：

- 没有时间倒退；
- 存在 12 个重复时间戳，集中于 Cycle/Step 边界；
- parser 必须保留这些行并记录 duplicate diagnostics，不得静默去重。

## Golden facts for current sample

- Start: `2024-01-06 09:52:31`
- End: `2024-01-06 20:58:54`
- `record` data rows: 39996
- cycles: 2

## Parser rules

1. Never alter the workbook.
2. Preserve original Chinese column names in raw schema metadata.
3. Map to canonical English field names only in the standardized layer.
4. Time must be non-decreasing within each DataAsset; duplicate timestamps are allowed and must be reported.
5. Cycle/step values must be cross-checkable against `cycle`/`step`.
6. Missing/ambiguous fields remain explicit null/unknown.
7. Fully blank formatted rows and identity-free non-tabular footer rows may be excluded only with explicit parser warnings; partially populated tabular rows must fail validation.
