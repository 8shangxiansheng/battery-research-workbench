# Human Review Checklist

Coding Agent 完成后，人工至少检查：

1. 打开 `parser_manifest.json`
   - 文件数是否与你实际放入一致？
   - Cycle IDs 是否符合真实实验？
   - start/end time 是否合理？

2. 用 pandas：
   ```python
   import pandas as pd
   df = pd.read_parquet(...)
   print(df.head())
   print(df.tail())
   print(df["cycle_index_raw"].value_counts())
   ```

3. 随机挑 5 行：
   - 原 XLSX
   - records.parquet
   手工比 V / I / timestamp / cycle / step。

4. 检查 `electrical_asset_id`
   多 XLSX 时是否真的能区分来源。

5. 检查原始文件 SHA256 未变化。

6. 查看 tests：
   确认 Agent 没有通过降低断言来“让测试绿”。

7. 确认代码没有开始写：
   - ultrasound
   - synchronization
   - ML
   - agent
