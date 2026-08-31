# Current Electrical Baseline

BRW-003 已验证：

```text
battery_id = CELL_001
experiment_id = EXP_001

records = 39996
cycles = 2
steps = 10
aux_temperature = 39996
aux_voltage = 39996

cycle_ids_raw = [1,2]
step_ids_raw = [1,2,3,4,5]

timestamp_min = 2024-01-06 09:52:31
timestamp_max = 2024-01-06 20:58:54

duplicate_timestamp_count = 12
```

Known facts:

- duplicate timestamps 确实来自原始 records；
- 多集中在 Step/Cycle 边界；
- QA 必须保留并报告；
- `SOC/DOD(%)` 仍保持 `soc_dod_percent`；
- `lgd_raw` 大量为空是源数据事实，不自动判 critical。
