# Confirmation Policy

| 级别 | 工具 |
|---|---|
| NO_CONFIRMATION | 全部 read-only 工具 |
| USER_CONFIRMATION | create_experiment / commit_intake / create_gate / analyze_feature_relationships / confirm_feature_selection / prepare_soc_dataset / prepare_grouped_evaluation_split / run_limited_soc_baselines / generate_scientific_report |
| USER_INPUT_REQUIRED | set_experiment_parameter（科学参数必须由用户提供 source，禁止推断） |

绑定规则：`confirmation_id = CNF::hex`；`inputs_digest = sha256(tool+inputs)`。
- payload 变化 → digest 不匹配 → CONFIRMATION_REQUIRED（旧确认失效）
- 过期（默认 30 分钟）→ 拒绝
- tool 不匹配 → 拒绝
- 成功执行后 confirmation 消费（一次性）
