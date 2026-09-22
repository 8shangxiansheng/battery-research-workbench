# BRW-RC1 Thesis Table Inventory

| 表 | 内容 | 数据工件 |
|---|---|---|
| Tab-1 | Raw 资产 SHA256（电气 XLSX / 超声 TXT，immutable） | RELEASE_MANIFEST.raw_checksums |
| Tab-2 | 最终 ParameterSet（PS::3b512b82…, fs 50 MHz, USER_SUPPLIED/VERIFIED） | parameter_set_manifest.json |
| Tab-3 | 最终 GateCalibrationRecord（GC-TOF::e401fecb…, FROZEN v20, gates+frames+diagnostics） | gate_calibrations/*.json |
| Tab-4 | Canonical TOF 汇总：3995 行、VALID 3995、samples 776–804、tof_us 15.52–16.08、edge/invalid 原因 | canonical_tof_manifest/audit |
| Tab-5 | 同步质量：matched 3999 / ambiguous 4（保留）/ unmatched 0；validated_sync=false | synchronization_manifest.json |
| Tab-6 | 特征目录（33 TD/FD + 物理 codes + tof_us；定义/验证/单位/版本/溯源） | /feature-definitions |
| Tab-7 | 特征–标签表规格：X=6 预测量（含 canonical tof_us）、y=Reference SOC、3995 行、排除分解 | dataset_manifest DS::83013a61 |
| Tab-8 | Grouped split 成员：LEAVE_ONE_GROUP_OUT / CYCLE / fold1·fold2 角色 | split_manifest + assignments |
| Tab-9 | 模型对比（fold1 有限评估）：Dummy 30.72 / Linear 35.73 / Ridge 35.73 / RF 45.92 / GB 46.65 %MAE；无模型胜 Dummy | model_comparison.json |
| Tab-10 | 限制清单（11 项 machine-readable）与 unsupported claims | scientific_report.json |
| Tab-11 | 复现结果：Run A 计数/ID 全等 canonical；Run B DATASET/SPLIT/MODELING REUSED | reproducibility_manifest |
