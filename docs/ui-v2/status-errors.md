# 状态与错误（§24）

| API 错误 | UI |
|---|---|
| AMBIGUOUS_ADAPTER | adapter 选择面板（wizard-step-2 内 ambiguous-panel） |
| UNSUPPORTED_FILE_FORMAT | unsupported 面板 + 支持能力 |
| INTAKE_NOT_VALIDATED | 回到验证步骤 |
| DUPLICATE_ASSET | 重复处理面板 |
| UPLOAD_TOO_LARGE | 上传反馈（413） |
| SCIENTIFIC_ACTION_REQUIRED | 行动面板（required fields + submit + resume） |
| SCIENTIFIC_READINESS_BLOCKED | readiness 面板 |
| INTEGRITY_ERROR | 严重告警 |
| INTERNAL_ERROR | request_id；无 traceback |

科学状态保持：TOF blocked = null + reason（绝不 0）；PROVISIONAL ≠ 软件错误；
SOH NOT_READY 不当系统故障。
