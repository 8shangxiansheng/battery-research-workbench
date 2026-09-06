# Scientific Safety（锁死项）

## ClaimGuard（BRW-023 传播）
`explain_result_evidence(claim=...)` 对以下 claim 直接 BLOCK：
"true SOC" / "validated cross-battery" / "absolute TOF" / "production-ready"。

## No-Guess Parameters
`ultrasound.sampling_rate_hz` `ultrasound.trigger_sample_index` `experiment.timezone`
`experiment.ultrasound_path_length_m` `experiment.reference_capacity_ah` — 设置时必须携带
显式 `source`；从 "frame cadence/filename/sample count/demo config" 推断 → SECURITY_VIOLATION。

## 科学状态保真
TOF BLOCKED → null + 原因（永不 0）；SOH NOT_READY（无 SOH modeling 工具）；
sync PROVISIONAL；SOC retrospective。全部经 `scientific_context.warnings` 原样向上传递。

## 隔离
实验上下文显式绑定 battery/experiment；资源（session/gate/dataset/split/run）记录属主
composite_id；无跨实验继承；Demo 不在 sandbox 出现。

## 安全基线
拒绝：任意路径、URL、shell、eval/compile、SQL、pickle、自定义特征代码、超大 payload、
path/url/command/sql/code 关键字字段。

## WAITING_FOR_USER
原样向上传递；工具层无 resume 工具；无自动填值。

## Audit
JSONL 式 entries：tool_call_id / tool_name / inputs_digest / confirmation_status /
result_status / resource_ids / run_id / request_id / evidence_refs。
禁止：secrets、chain-of-thought、波形 payload。
