# OSI-001 Experiment Specification

## Research question

对于当前 Neware 多-sheet XLSX：

```text
unit/test/cycle/step/record/auxVol/auxTemp
```

使用 cellpy / BEEP 是否可以减少：

```text
解析
cycle/step analysis
capacity summary
plotting
feature engineering
ML pipeline
```

的自研量？

---

## Control

现有 BRW-003/004 作为 control/reference。

不要拿第三方输出反向定义正确答案。

---

## Experiment arms

### Arm A
BRW Custom Parser

### Arm B
cellpy

### Arm C
BEEP

---

## Success definition

不是“import 成功”。

必须产生：

```text
actual parsed/structured data
numeric comparison
capability comparison
integration recommendation
```
