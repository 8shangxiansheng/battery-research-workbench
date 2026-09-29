# 科学工作流（UI 实现参考）

> 面向用户的当前操作步骤见[工作台使用指南](../USER_GUIDE.md)。本文件说明页面之间的科学数据关系；界面状态和路由可能随版本演进。

当前用户主导航为 Overview → Waveform → Analysis → Models → Report。Analysis 内按 Target → Alignment → Features → Relationships → Selection → Dataset 检查科学流程；Split、Models 和 Report 是否可进入由当前 dataset、分组划分及工件状态决定。

## 科学工作流约束

1. **Overview** 汇总实验身份、数据就绪情况、科学限制和推荐下一步；前端使用后端返回的数据，不自行计算科学状态。
2. **Waveform / Gates** 展示波形和局部样本闸门。拖选区域先形成草稿，需显式确认后才成为已提交配置。横轴在采样率未可靠验证时使用 sample index。
3. **Target / Alignment** 展示目标定义、来源、覆盖及 MeasurementEvent 同步结果。同步按 DataAsset 与绝对时间建立；保留 `sync_error_s` 和歧义状态，不用 Cycle 替代跨文件身份。
4. **Features / Relationships** 显示特征的定义、单位、来源和状态。相关性与 Ranking 来自 API；前端不重算科学量，也不将相关性解释为因果关系。
5. **Selection / Preview** 以所选特征构成 X，以唯一研究目标构成 y；预览应检查纳入/排除统计和行级 provenance。ML-safe 评估中 held-out 标签由后端遮蔽。
6. **Dataset / Split** 在确认数据定义后生成数据集和分组 split。禁止随机拆分相关联的帧/行来替代 Battery-level 分组；样本组数不足时应保持阻断。
7. **Models / Report** 只对当前有效 dataset 和 split 的结果作结论；旧产物须标为 stale，报告聚合既有证据，不应暗示自动完成了超参数调优。
8. **Advanced / Assistant / Runs** 用于查看参数、证据、血缘和运行状态。`BLOCKED`、`WAITING_FOR_USER`、`PROVISIONAL`、`UNKNOWN` 与 `STALE` 都是有意义的科研状态，不应被折叠成通用错误或 READY。
