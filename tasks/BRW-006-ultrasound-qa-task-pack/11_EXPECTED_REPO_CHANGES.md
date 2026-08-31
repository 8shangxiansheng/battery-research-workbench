# Expected Repository Changes

主要新增：

```text
src/battery_workbench/ultrasound/qa/
├── __init__.py
├── schemas.py
├── structural.py
├── temporal.py
├── waveform.py
├── cross_frame.py
├── anomalies.py
├── figures.py
├── report.py
└── service.py

configs/ultrasound_qa.yaml

tests/unit/test_ultrasound_qa_*.py
tests/integration/test_current_ultrasound_qa.py
```

不应大改：`io/ultrasound/`（BRW-005 parser）、electrical、synchronization、analysis、ml、agent、apps。
