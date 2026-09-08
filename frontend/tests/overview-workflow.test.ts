import { describe, expect, it } from "vitest";
import type { StatusBlock, WorkspaceSummary } from "../src/api/client";
import { overviewNextStep } from "../src/lib/overview-workflow";

const ready = { synchronization: { validated_sync: true }, tof: { status: "AVAILABLE" } } as StatusBlock;
const workspace = {} as WorkspaceSummary;
describe("概览主路径", () => {
  it("缺失状态不视为就绪", () => expect(overviewNextStep(undefined, workspace).kind).toBe("unknown"));
  it("同步阻断优先于下游产物", () => expect(overviewNextStep({ ...ready, synchronization: { validated_sync: false, timebase_status: "PROVISIONAL" } }, workspace).kind).toBe("resolve"));
  it("TOF 阻断要求前置参数", () => expect(overviewNextStep({ ...ready, tof: { value: null, status: "BLOCKED", reason: "sampling" } }, workspace).kind).toBe("resolve"));
  it("前置通过但未确认闸门时进入波形", () => expect(overviewNextStep(ready, workspace).route).toBe("waveform"));
  it("有闸门后进入特征分析", () => expect(overviewNextStep(ready, { ...workspace, gate_set_id: "g" }).route).toBe("analysis"));
  it("已有模型时进入结果复核而非自动重跑", () => expect(overviewNextStep(ready, workspace, true).route).toBe("models"));
});
