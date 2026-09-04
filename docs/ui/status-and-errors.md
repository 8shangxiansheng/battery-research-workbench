# 状态与错误 UX

## 科学状态（来自 API，保持原语义）

| 状态 | UI 呈现 |
|---|---|
| TOF BLOCKED | 取值 null + 原因文字；**绝不显示 0 μs** |
| SOH NOT_READY_FOR_MODEL_EVALUATION | 状态文字，不当系统故障 |
| PROVISIONAL_TIMEBASE | sync validated_sync=false + PROVISIONAL 标签 |
| RETROSPECTIVE_SOC_REFERENCE | SOC 显示 protocol-anchored derived，不写 True SOC |
| LIMITED_CROSS_CYCLE_EVALUATION | 明示 2 cycles / within-battery 有限评估 |

## 错误映射（typed error → UX）

| API 错误码 | UI 面板 | HTTP |
|---|---|---|
| SCIENTIFIC_ACTION_REQUIRED | 行动面板（列出 required fields，用户输入后 submit+resume） | 409 |
| SCIENTIFIC_READINESS_BLOCKED | 就绪受阻面板（说明原因） | 409 |
| ARTIFACT_NOT_AVAILABLE | 可用性面板（可显示 prior evidence，保留证据标签） | 404 |
| VALIDATION_ERROR | 字段级反馈 | 400 |
| INTEGRITY_ERROR | 严重告警 | 409 |
| INTERNAL_ERROR | 友好错误 + request_id；**不显示 traceback** | 500 |

## Notifications 分类

Scientific Action Required / Limitation / Software Error / Success / Info 五类，样式与文案区分。

## 可访问性（§56）

- 键盘：闸门选择支持键盘提交（Enter）；全部控件可聚焦
- 表单均有 label；状态用 role="status"/"alert" 文字呈现
- 图表（SVG 波形）配文字说明与表格 fallback
