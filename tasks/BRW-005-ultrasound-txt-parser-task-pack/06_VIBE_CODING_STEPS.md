# BRW-005 Vibe Coding Sequence

## Round 1 — Inspect only

检查：

- ultrasound manifests
- TXT count
- 每个 TXT 结构
- frame counts
- elapsed ranges
- waveform sample count
- unknown fields
- file_start_time availability

不改代码。

---

## Round 2 — Tests RED

先写：

- line parser tests
- invalid format tests
- multi-file tests
- Zarr round-trip
- golden/integration scaffolding

让测试合理失败。

---

## Round 3 — Single TXT parser

只实现：

```text
custom_txt.py
schemas.py
validation.py
```

先让单文件 tests GREEN。

---

## Round 4 — Zarr + Parquet

实现：

```text
storage/zarr_store.py
frames.parquet
```

加入 round-trip tests。

---

## Round 5 — Multi-asset service

实现：

```text
service.py
manifest.py
```

支持一个 Experiment 多 TXT。

---

## Round 6 — Current real dataset

真正解析当前 Ultrasound TXT。

生成：

```text
frames.parquet
waveforms.zarr
parser_manifest.json
```

做 golden + SHA256。

---

## Round 7 — Cleanup

```text
pytest
ruff
format
mypy
git diff
docs
```

不做 BRW-006。
