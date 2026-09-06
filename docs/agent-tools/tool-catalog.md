# Tool Catalog（36 tools, contract v1.0.0）

## Discovery / Inspection（read-only, NO_CONFIRMATION）
`list_experiments` `inspect_experiment` `inspect_data_quality` `inspect_synchronization`
`inspect_measurement_events` `inspect_run` `inspect_lineage` `inspect_intake_capabilities`

## Intake
`create_experiment`(确认) `load_demo`(幂等) `start_intake` `upload_experiment_asset`
`detect_asset_format` `validate_intake` `commit_intake`(确认+幂等) `cancel_intake`

## Parameters
`inspect_missing_parameters`(只读) `set_experiment_parameter`(USER_INPUT_REQUIRED + 确认；
no-guess 参数必须由用户提供 source)

## Waveform / Gates
`list_waveform_frames` `inspect_waveform_frame`(有界降采样预览) `list_gates`
`propose_gate`(只读 draft) `create_gate`(确认, 幂等 GATE::id)

## Features / Analysis
`list_available_features` `inspect_feature` `analyze_feature_relationships`(确认, BRW-021,
EXPLORATORY_FULL_DATA / TRAIN_ONLY_ML_SAFE) `propose_feature_selection`(只读 draft)
`confirm_feature_selection`(确认)

## Dataset / Evaluation
`prepare_soc_dataset`(确认, 幂等, leakage guard) `prepare_grouped_evaluation_split`(确认,
幂等, LEAVE_ONE_GROUP_OUT) `run_limited_soc_baselines`(确认, 固定基线, 无 tuning)
`inspect_model_comparison`(只读, 含 Dummy 基线对比 + 诚实结论)

## Reporting / Evidence
`generate_scientific_report`(确认, 幂等 REUSED, 聚合 only) `inspect_scientific_report`
`explain_result_evidence`(ClaimGuard: unsupported claim → BLOCKED) `inspect_evidence`
