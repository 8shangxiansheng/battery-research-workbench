/**
 * 波形与闸门（§9-12）。
 * - 只经 API preview 取帧（降采样），不 bulk 波形（§9/§73）。
 * - fs 未验证 → x 轴只能是 Sample Index（§10）。
 * - 用户拖选 draft gate → POST /gates 提交；UI 不算 feature（§11）。
 * - draft 与 committed 明显区分（§51）。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, client, type FramePreviewResponse } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";

interface DraftGate {
  start: number;
  end: number;
}

function GateOverlay({
  preview,
  committed,
  draft,
  onSelect,
}: {
  preview: FramePreviewResponse;
  committed: { gate_id: string; start_sample?: number; end_sample?: number }[];
  draft: DraftGate | null;
  onSelect: (start: number, end: number) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const dragStart = useRef<number | null>(null);
  const [ghost, setGhost] = useState<DraftGate | null>(null);

  const length = preview.waveform_length;
  const amplitudes = preview.samples.map((s) => s.amplitude_a_u);
  const yMin = Math.min(...amplitudes);
  const yMax = Math.max(...amplitudes);
  const yPad = (yMax - yMin) * 0.1 || 1;
  const plotY = (v: number) => 100 - ((v - (yMin - yPad)) / (yMax + yPad - (yMin - yPad))) * 100;

  const toSample = (clientX: number): number => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) {
      // jsdom/headless 无布局时退化为按像素等比例映射，保证拖选可用
      return Math.round(clientX % length);
    }
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return Math.round(ratio * length);
  };

  const points = preview.samples
    .map((s) => `${(s.sample_index / length) * 800},${plotY(s.amplitude_a_u)}`)
    .join(" ");

  return (
    <div>
      <svg
        ref={svgRef}
        data-testid="waveform-svg"
        role="img"
        aria-label={`波形帧 ${preview.frame_index}，x 轴 Sample Index（采样点）`}
        viewBox="0 0 800 100"
        width="100%"
        height="220"
        style={{ border: "1px solid #ccc", touchAction: "none", cursor: "crosshair" }}
        tabIndex={0}
        onKeyDown={(e) => {
          // §56/T60: 键盘可用的闸门控制
          if (e.key === "Enter" && ghost) {
            onSelect(ghost.start, ghost.end);
            setGhost(null);
          }
        }}
        onMouseDown={(e) => {
          dragStart.current = toSample(e.clientX);
          setGhost(null);
        }}
        onMouseMove={(e) => {
          if (dragStart.current !== null) {
            const cur = toSample(e.clientX);
            setGhost({
              start: Math.min(dragStart.current, cur),
              end: Math.max(dragStart.current, cur),
            });
          }
        }}
        onMouseUp={(e) => {
          if (dragStart.current !== null) {
            const cur = toSample(e.clientX);
            const start = Math.min(dragStart.current, cur);
            const end = Math.max(dragStart.current, cur);
            dragStart.current = null;
            if (end > start) onSelect(start, end);
            setGhost(null);
          }
        }}
      >
        {/* committed gates: 蓝色 */}
        {committed.map((g) =>
          g.start_sample !== undefined && g.end_sample !== undefined ? (
            <rect
              key={g.gate_id}
              x={(g.start_sample / length) * 800}
              width={((g.end_sample - g.start_sample) / length) * 800}
              y={0}
              height={100}
              fill="rgba(30,80,160,0.12)"
              stroke="rgba(30,80,160,0.6)"
              data-testid={`committed-gate-${g.gate_id}`}
            />
          ) : null,
        )}
        {/* draft: 橙色，明显区别于 committed（§51） */}
        {(draft ?? ghost) && (
          <rect
            x={((draft ?? ghost)!.start / length) * 800}
            width={(((draft ?? ghost)!.end - (draft ?? ghost)!.start) / length) * 800}
            y={0}
            height={100}
            fill="rgba(220,130,20,0.18)"
            stroke="rgba(220,130,20,0.8)"
            data-testid="draft-gate"
          />
        )}
        <polyline points={points} fill="none" stroke="#333" strokeWidth="0.8" />
      </svg>
      <p>
        <small>x 轴: Sample Index（采样点）— 采样频率未验证，不显示 μs 时间轴（§10）</small>
      </p>
    </div>
  );
}

export function WaveformPage() {
  const { batteryId = "", experimentId = "" } = useParams();
  const [frameIndex, setFrameIndex] = useState(0);
  const [draft, setDraft] = useState<DraftGate | null>(null);
  const [gateName, setGateName] = useState("");
  const [commitMessage, setCommitMessage] = useState<string | null>(null);
  const [commitError, setCommitError] = useState<unknown>(null);
  const queryClient = useQueryClient();

  const frames = useQuery({
    queryKey: ["waveform-frames", batteryId, experimentId],
    queryFn: () => client.listWaveformFrames(batteryId, experimentId),
  });
  const gates = useQuery({
    queryKey: ["gates", batteryId, experimentId],
    queryFn: () => client.listGates(batteryId, experimentId),
  });
  const preview = useQuery({
    queryKey: ["waveform-frame", batteryId, experimentId, frameIndex],
    queryFn: () => client.getWaveformFrame(batteryId, experimentId, frameIndex, 500),
    enabled: frames.isSuccess,
  });

  const commitGate = useMutation({
    mutationFn: (d: DraftGate) =>
      client.createGate({
        battery_id: batteryId,
        experiment_id: experimentId,
        gate_name: gateName || `Gate-${d.start}-${d.end}`,
        start_sample: d.start,
        end_sample: d.end,
        waveform_length: preview.data?.data.waveform_length ?? 1250,
      }),
    onSuccess: (result) => {
      setCommitMessage(
        `${result.data.reuse_status === "REUSED" ? "复用已有闸门" : "已提交闸门"}: ${result.data.gate_id}`,
      );
      setDraft(null);
      setGateName("");
      void queryClient.invalidateQueries({ queryKey: ["gates"] });
    },
    onError: (err) => setCommitError(err),
  });

  const maxFrame = useMemo(() => (frames.data?.data.frame_count ?? 1) - 1, [frames.data]);

  if (frames.isLoading) return <p role="status">加载波形帧列表…</p>;
  if (frames.error) {
    // §45: ARTIFACT_NOT_AVAILABLE 明确展示
    return <ErrorBanner error={frames.error} />;
  }
  const committedGates = gates.data?.data.gates ?? [];

  return (
    <section aria-labelledby="waveform-title">
      <h2 id="waveform-title">波形与闸门 Waveform &amp; Gates</h2>

      <div style={{ margin: "0.5rem 0" }}>
        <label htmlFor="frame-select">帧选择 frame：</label>
        <input
          id="frame-select"
          data-testid="frame-input"
          type="number"
          min={0}
          max={maxFrame}
          value={frameIndex}
          onChange={(e) => setFrameIndex(Math.min(maxFrame, Math.max(0, Number(e.target.value))))}
        />
        <span>
          {" "}
          / {maxFrame}（共 {frames.data?.data.frame_count} 帧）
        </span>
      </div>

      {preview.isLoading ? (
        <p role="status">加载帧预览…</p>
      ) : preview.error ? (
        <ErrorBanner error={preview.error} />
      ) : preview.data?.data ? (
        <GateOverlay
          preview={preview.data.data}
          committed={committedGates}
          draft={draft}
          onSelect={(start, end) => setDraft({ start, end })}
        />
      ) : null}

      <h3>草稿闸门（draft — 未提交）</h3>
      {draft ? (
        <div data-testid="draft-panel" style={{ border: "1px dashed #d82", padding: "0.5rem" }}>
          <p>
            start_sample: <code>{draft.start}</code> · end_sample: <code>{draft.end}</code>
          </p>
          <label htmlFor="gate-name">闸门显示名（Gate A / Gate B …）：</label>
          <input
            id="gate-name"
            value={gateName}
            onChange={(e) => setGateName(e.target.value)}
            placeholder="Gate A"
          />
          <p>
            <small>科学身份将由 API 返回的 gate_id 绑定（§12）。</small>
          </p>
          <button
            type="button"
            data-testid="commit-gate"
            onClick={() => commitGate.mutate(draft)}
            disabled={commitGate.isPending}
          >
            {commitGate.isPending ? "提交中…" : "提交闸门（走 API）"}
          </button>
        </div>
      ) : (
        <p>在波形上拖选一个区间以创建 draft gate。</p>
      )}

      {commitMessage && (
        <p role="status" data-testid="commit-success">
          {commitMessage}
        </p>
      )}
      {commitError instanceof ApiError && (
        <div role="alert" data-testid="commit-error">
          <ErrorBanner error={commitError} />
        </div>
      )}
      {!commitError && commitGate.isError ? <ErrorBanner error={commitGate.error} /> : null}

      <h3>已提交闸门（committed）</h3>
      {committedGates.length === 0 ? (
        <p data-testid="no-gates">暂无已提交闸门。</p>
      ) : (
        <table data-testid="gates-table">
          <caption>科学身份 = gate_id（显示名仅为人类可读）</caption>
          <thead>
            <tr>
              <th>gate_id</th>
              <th>gate_set</th>
              <th>start</th>
              <th>end</th>
            </tr>
          </thead>
          <tbody>
            {committedGates.map((g) => (
              <tr key={g.gate_id}>
                <td>
                  <code>{g.gate_id}</code>
                </td>
                <td>{g.gate_set_id}</td>
                <td>{g.start_sample ?? "—"}</td>
                <td>{g.end_sample ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
