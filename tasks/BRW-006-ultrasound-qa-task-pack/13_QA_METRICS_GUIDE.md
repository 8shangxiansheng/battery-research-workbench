# BRW-006 QA Metrics Guide

RMS = `sqrt(mean(x^2))`：幅值尺度/异常帧 QA。

P2P = `max(x)-min(x)`：幅值跨度/突变 QA。

DC offset = `mean(x)`：基线偏移 QA；本阶段不做 DC removal。

Adjacent correlation = `corr(x_i, x_(i-1))`：形态突变 QA；不能直接解释成 SOC/SOH 物理变化。

Possible saturation：无 ADC rails 时只能报告 repeated extreme plateau，不能确认 clipping。

这些指标本阶段只用于 QA；后续 Feature Engine 才作为正式科研特征使用。
