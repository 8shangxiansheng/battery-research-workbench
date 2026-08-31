# BRW-007 Functional Specification

## Purpose

BRW-007 解决：

> 谁负责决定哪个 DataAsset 交给哪个 Parser？

答案：

```text
ExperimentImporter
+
DataAdapterRegistry
```

---

## Core abstraction

```text
DataAdapter
```

不是 Parser。

Adapter 负责：

```text
modality ownership
service delegation
result normalization
```

---

## Core orchestration

```text
Experiment
↓
DataAssets
↓
group by modality
↓
AdapterRegistry
↓
Adapter
↓
existing parser service
↓
ExperimentImportResult
```

---

## Future extensibility

以后增加：

```text
EISAdapter
ThermalAdapter
PressureAdapter
```

不修改 importer 主逻辑。
