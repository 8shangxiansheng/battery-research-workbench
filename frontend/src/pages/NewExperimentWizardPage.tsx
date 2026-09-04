/**
 * BRW-025R §3-9 — New Experiment Wizard（6 步）。
 * Info → Assets → Detection → Preview/Validation → Metadata → Commit & Start。
 * 每步 Back/Continue/Cancel；server-backed intake_session_id；刷新可恢复（URL state）。
 * 上传全部走 BRW-024R intake；不做任何 raw 目录操作。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  client,
  type AdapterDetection,
  type ImportValidation,
  type IntakeSessionDetail,
} from "../api/client";
import { Badge, Card, Stepper, StatusText } from "../design/components";
import { ErrorBanner } from "../components/ErrorBanner";

const STEPS = ["实验信息", "数据资产", "格式检测", "预览与验证", "科学元数据", "提交与启动"];

function fmtSize(bytes: number): string {
  if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export function NewExperimentWizardPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { sessionId } = useParams(); // /new/:sessionId? — refresh recovery
  const [step, setStep] = useState(0);
  const [batteryId, setBatteryId] = useState("");
  const [experimentId, setExperimentId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [session, setSession] = useState<IntakeSessionDetail | null>(null);
  const [detections, setDetections] = useState<AdapterDetection[]>([]);
  const [validation, setValidation] = useState<ImportValidation | null>(null);
  const [stepError, setStepError] = useState<unknown>(null);
  const [committed, setCommitted] = useState<Record<string, unknown> | null>(null);
  const [uploaded, setUploaded] = useState<{ role: string; filename: string; size: number; sha256: string }[]>([]);

  const sessionQuery = useQuery({
    queryKey: ["intake-session", sessionId],
    queryFn: () => client.getIntakeSession(sessionId!),
    enabled: Boolean(sessionId) && !session,
  });

  useEffect(() => {
    if (sessionQuery.data?.data) setSession(sessionQuery.data.data);
  }, [sessionQuery.data]);

  const createSession = useMutation({
    mutationFn: async () => {
      const created = await client.createExperiment({
        battery_id: batteryId,
        experiment_id: experimentId || undefined,
        name,
        notes: description,
      });
      const s = await client.createIntakeSession(created.data.battery_id, created.data.experiment_id);
      return { experiment: created.data, session: s.data };
    },
    onSuccess: ({ session: s }) => {
      setSession(s);
      setStep(1);
      void qc.invalidateQueries({ queryKey: ["library"] });
      navigate(`/new/${s.session_id}`, { replace: true });
    },
    onError: (e) => setStepError(e),
  });

  const upload = useMutation({
    mutationFn: async ({ role, file }: { role: "ELECTRICAL" | "ULTRASOUND"; file: File }) => {
      if (!session) throw new Error("no session");
      return client.uploadIntakeAsset(session.session_id, role, file);
    },
    onSuccess: (r) => {
      setStepError(null);
      setUploaded((prev) => [
        ...prev.filter((x) => x.filename !== r.data.original_filename),
        {
          role: r.data.role,
          filename: r.data.original_filename,
          size: r.data.size,
          sha256: r.data.sha256,
        },
      ]);
      void client.getIntakeSession(session!.session_id).then((resp) => setSession(resp.data));
    },
    onError: (e) => setStepError(e),
  });

  const detect = useMutation({
    mutationFn: () => client.detectIntakeSession(session!.session_id),
    onSuccess: (r) => {
      setStepError(null);
      setDetections(r.data.detections);
      setStep(2);
    },
    onError: (e) => setStepError(e),
  });

  const validate = useMutation({
    mutationFn: () => client.validateIntakeSession(session!.session_id),
    onSuccess: (r) => {
      setStepError(null);
      setValidation(r.data);
      setStep(4);
    },
    onError: (e) => setStepError(e),
  });

  const commit = useMutation({
    mutationFn: () => client.commitIntakeSession(session!.session_id),
    onSuccess: (r) => {
      setStepError(null);
      setCommitted(r.data);
      setStep(5);
      void qc.invalidateQueries({ queryKey: ["library"] });
    },
    onError: (e) => setStepError(e),
  });

  const startPipeline = useMutation({
    mutationFn: () =>
      client.startRun({
        profile: "INGEST_TO_MEASUREMENT_EVENTS",
        battery_id: session!.battery_id,
        experiment_id: session!.experiment_id,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["library"] });
      void qc.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/experiments/${session!.battery_id}/${session!.experiment_id}`);
    },
    onError: (e) => setStepError(e),
  });

  // ----- step 0: info -----
  if (step === 0) {
    return (
      <Card title="新建实验 — 1/6 实验信息" testId="wizard-step-info">
        <Stepper steps={STEPS} current={0} />
        <p>
          <label htmlFor="wiz-battery">
            Battery ID（必填）：
            <input
              id="wiz-battery"
              data-testid="wiz-battery"
              value={batteryId}
              onChange={(e) => setBatteryId(e.target.value)}
              placeholder="CELL_100"
            />
          </label>
        </p>
        <p>
          <label htmlFor="wiz-exp">
            Experiment ID（留空自动生成）：
            <input
              id="wiz-exp"
              data-testid="wiz-experiment-id"
              value={experimentId}
              onChange={(e) => setExperimentId(e.target.value)}
              placeholder="自动生成 EXP_001…"
            />
          </label>
        </p>
        <p>
          <label htmlFor="wiz-name">
            实验名称（必填）：
            <input
              id="wiz-name"
              data-testid="wiz-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：循环寿命测试 第1轮"
            />
          </label>
        </p>
        <p>
          <label htmlFor="wiz-desc">
            描述（可选）：
            <input id="wiz-desc" data-testid="wiz-description" value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
        </p>
        <p>
          <small>身份由你显式输入或系统按序生成；绝不从文件名推断（§4）。</small>
        </p>
        {stepError ? <ErrorBanner error={stepError} /> : null}
        <button
          type="button"
          className="primary"
          data-testid="wiz-continue-info"
          disabled={!batteryId || !name || createSession.isPending}
          onClick={() => {
            setStepError(null);
            createSession.mutate();
          }}
        >
          {createSession.isPending ? "创建中…" : "创建并继续 →"}
        </button>
      </Card>
    );
  }

  if (!session) return <StatusText>加载会话…</StatusText>;

  const hasElectrical = session.assets.some((a) => a.role === "ELECTRICAL");
  const hasUltrasound = session.assets.some((a) => a.role === "ULTRASOUND");
  const ambiguous = detections.some((d) => d.state === "DETECTED_AMBIGUOUS");
  const unsupported = detections.some((d) => d.state === "UNSUPPORTED");

  // ----- step 5: commit & start -----
  if (step === 5) {
    return (
      <Card title="新建实验 — 6/6 提交与启动" testId="wizard-step-commit">
        <Stepper steps={STEPS} current={5} />
        {committed ? (
          <>
            <h3>已提交导入 ✓</h3>
            <ul>
              <li>Raw assets registered（已登记原始资产）</li>
              <li>Checksums verified（校验和已验证）</li>
              <li>
                status: <strong>READY_FOR_PIPELINE</strong>
              </li>
            </ul>
            <p data-testid="commit-summary">
              <small>import manifest checksum: {String(committed.import_manifest_checksum)}</small>
            </p>
            <button
              type="button"
              className="primary"
              data-testid="start-pipeline"
              disabled={startPipeline.isPending}
              onClick={() => startPipeline.mutate()}
            >
              {startPipeline.isPending ? "启动中…" : "开始数据处理（INGEST_TO_MEASUREMENT_EVENTS）"}
            </button>{" "}
            <button type="button" data-testid="later" onClick={() => navigate("/")}>
              稍后
            </button>
            {stepError ? <ErrorBanner error={stepError} /> : null}
          </>
        ) : (
          <>
            <h3>提交前确认（§9）</h3>
            <ul data-testid="pre-commit-summary">
              <li>Experiment: {session.experiment_composite_id}</li>
              {session.assets.map((a) => (
                <li key={a.intake_asset_id}>
                  {a.role}: {a.original_filename}（{fmtSize(a.size)}，sha256 {a.sha256.slice(0, 12)}…）
                </li>
              ))}
              {session.detections.map((d) => (
                <li key={`d-${d.intake_asset_id}`}>
                  Adapter: {d.adapter_id} v{d.adapter_version}（{d.state}）
                </li>
              ))}
              <li>Validation: {validation?.overall_passed ? "通过" : "未通过"}</li>
              <li>
                未知元数据: sampling_rate_hz = UNKNOWN（保持未知，不猜测）
              </li>
            </ul>
            {stepError ? <ErrorBanner error={stepError} /> : null}
            <button
              type="button"
              className="primary"
              data-testid="confirm-commit"
              disabled={commit.isPending}
              onClick={() => commit.mutate()}
            >
              {commit.isPending ? "导入中…" : "确认并导入"}
            </button>
          </>
        )}
      </Card>
    );
  }

  return (
    <Card title={`新建实验 — ${STEPS[step]}`} testId={`wizard-step-${step}`}>
      <Stepper steps={STEPS} current={step} />

      {step === 1 && (
        <>
          <h3>上传数据资产（走 intake API，禁止手工 raw 目录 — §5）</h3>
          <table data-testid="upload-table">
            <thead>
              <tr>
                <th>分区</th>
                <th>选择文件</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Electrical Data（.xlsx）</td>
                <td>
                  <label>
                    <span className="sr-only">选择电气数据文件</span>
                    <input
                      type="file"
                      accept=".xlsx"
                      data-testid="upload-electrical"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) upload.mutate({ role: "ELECTRICAL", file: f });
                      }}
                    />
                  </label>
                </td>
              </tr>
              <tr>
                <td>Ultrasound Data（.txt）</td>
                <td>
                  <label>
                    <span className="sr-only">选择超声数据文件</span>
                    <input
                      type="file"
                      accept=".txt"
                      data-testid="upload-ultrasound"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) upload.mutate({ role: "ULTRASOUND", file: f });
                      }}
                    />
                  </label>
                </td>
              </tr>
            </tbody>
          </table>
          <h4>已上传（{uploaded.length}）</h4>
          <ul data-testid="uploaded-list">
            {uploaded.length === 0 ? <li>暂无</li> : null}
            {uploaded.map((u) => (
              <li key={u.filename}>
                <Badge tone="primary">{u.role}</Badge> {u.filename}（{fmtSize(u.size)}）sha256 {u.sha256.slice(0, 12)}…
              </li>
            ))}
          </ul>
          {upload.isPending ? <StatusText>上传中…</StatusText> : null}
          {stepError ? <ErrorBanner error={stepError} /> : null}
          <button type="button" onClick={() => setStep(0)}>
            ← Back
          </button>{" "}
          <button
            type="button"
            className="primary"
            data-testid="wiz-continue-assets"
            disabled={!hasElectrical || !hasUltrasound}
            onClick={() => setStep(2)}
          >
            Continue →
          </button>
        </>
      )}

      {step === 2 && (
        <>
          <h3>格式检测（BRW-007 Adapter Registry）</h3>
          {!detections.length ? (
            <button
              type="button"
              className="primary"
              data-testid="run-detect"
              disabled={detect.isPending}
              onClick={() => detect.mutate()}
            >
              {detect.isPending ? "检测中…" : "运行检测（POST /detect）"}
            </button>
          ) : (
            <table data-testid="detection-table">
              <thead>
                <tr>
                  <th>状态</th>
                  <th>Role</th>
                  <th>Adapter</th>
                  <th>版本</th>
                  <th>原因/签名</th>
                </tr>
              </thead>
              <tbody>
                {detections.map((d) => (
                  <tr key={d.intake_asset_id} data-testid={`detection-${d.state}`}>
                    <td>
                      <Badge
                        tone={
                          d.state === "DETECTED_UNIQUE"
                            ? "success"
                            : d.state === "DETECTED_AMBIGUOUS"
                              ? "warning"
                              : "blocked"
                        }
                      >
                        {d.state}
                      </Badge>
                    </td>
                    <td>{d.asset_role}</td>
                    <td className="mono">{d.adapter_id ?? "—"}</td>
                    <td>{d.adapter_version ?? "—"}</td>
                    <td>
                      <small>{d.detection_reason}</small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {ambiguous ? (
            <div role="alert" data-testid="ambiguous-panel" style={{ border: "1px solid var(--warning)", padding: 8, marginTop: 8 }}>
              <strong>检测到歧义（DETECTED_AMBIGUOUS）</strong>
              <p>
                <small>多个 adapter 匹配，必须由你选择正确 adapter（不能静默选择 — §6）。</small>
              </p>
            </div>
          ) : null}
          {unsupported ? (
            <div role="alert" data-testid="unsupported-panel" style={{ border: "1px solid var(--blocked)", padding: 8, marginTop: 8 }}>
              <strong>不支持的格式（UNSUPPORTED）</strong>
              <p>
                <small>
                  当前支持能力：electrical=.xlsx（BRW-003）、ultrasound=.txt（BRW-005）。
                  请更换文件或联系维护者新增 adapter。
                </small>
              </p>
            </div>
          ) : null}
          {stepError ? <ErrorBanner error={stepError} /> : null}
          <button type="button" onClick={() => setStep(1)}>
            ← Back
          </button>{" "}
          <button
            type="button"
            className="primary"
            data-testid="wiz-continue-detect"
            disabled={!detections.length || unsupported || ambiguous}
            onClick={() => validate.mutate()}
          >
            {validate.isPending ? "验证中…" : "Continue → 预览与验证"}
          </button>
        </>
      )}

      {step === 4 && validation && (
        <>
          <h3>预览与验证（§7）</h3>
          <table data-testid="validation-table">
            <thead>
              <tr>
                <th>维度</th>
                <th>结果</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {validation.checks.map((c) => (
                <tr key={c.dimension + c.detail} data-testid={`check-${c.dimension}`}>
                  <td>{c.dimension}</td>
                  <td>{c.passed ? "✓" : "✗"}</td>
                  <td>
                    <small>{c.detail}</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p data-testid="fs-unknown-line">
            <Badge tone="warning">⚠ sampling_rate_hz = UNKNOWN</Badge>{" "}
            <small>格式 ✓；未知元数据保持未知（§8）；仍允许 commit。</small>
          </p>
          <p>overall: {validation.overall_passed ? "✓ 通过" : "✗ 未通过"}</p>
          <button type="button" onClick={() => setStep(2)}>
            ← Back
          </button>{" "}
          <button
            type="button"
            className="primary"
            data-testid="wiz-continue-validation"
            disabled={!validation.overall_passed}
            onClick={() => setStep(5)}
          >
            Continue → 科学元数据
          </button>
        </>
      )}

      {step === 4 && !validation && <StatusText>加载验证结果…</StatusText>}
    </Card>
  );
}

export function wizardApiErrorKind(err: unknown): string | null {
  return err instanceof ApiError ? err.code : null;
}
