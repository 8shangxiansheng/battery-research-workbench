import { useState } from "react";
import { useParams } from "react-router-dom";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Checkbox } from "../ui/checkbox";
import { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../ui/dialog";
import { useSamplingSubmission, type SubmissionState } from "../../lib/submission";

const UNIT_FACTORS: Record<string, number> = { Hz: 1, kHz: 1e3, MHz: 1e6 };

/** BRW-018R2 — shared sampling-rate submission dialog.
 *
 * WAITING_FOR_USER → 输入 fs → Saving → Saved（+ 可选 run resume）→
 * readiness refresh，全程 Saving/Saved/Failed 显式可见，无 silent no-op。
 * Partial success（保存成功但 resume 失败）→ Retry Resume；绝不重复写参数。
 */
export function ParameterDialog({ label = "Add sampling rate" }: { label?: string }) {
  const { batteryId = "", experimentId = "" } = useParams();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState<"Hz" | "kHz" | "MHz">("MHz");
  const [source, setSource] = useState("");
  const [verified, setVerified] = useState(false);
  const [state, setState] = useState<SubmissionState | null>(null);
  const { submit, retryResume } = useSamplingSubmission();
  const saving = state?.phase === "SAVING";
  const numeric = Number(value);
  const valid = value.trim() !== "" && Number.isFinite(numeric) && numeric > 0 && source.trim().length > 0;

  async function doSubmit() {
    if (!valid) return;
    await submit(
      { batteryId, experimentId, value: numeric, unit, source: source.trim(), verified },
      setState,
    );
  }
  async function doRetryResume() {
    if (!state?.submissionId) return;
    await retryResume(batteryId, experimentId, state.submissionId, setState);
  }
  return <Dialog open={open} onOpenChange={next => {setOpen(next); if(next) {setState(null);}}}>
    <DialogTrigger asChild><Button variant="outline" size="sm">{label}</Button></DialogTrigger>
    <DialogContent><DialogHeader><DialogTitle>Sampling frequency</DialogTitle><DialogDescription>Provide the instrument's waveform sampling frequency for {batteryId} / {experimentId}. Frame cadence is not sampling frequency.</DialogDescription></DialogHeader>
      {state && (state.phase === "SAVED" || state.phase === "PARTIAL") ? (
        <div className="space-y-3" data-testid="submission-result">
          <p role="status" data-testid="submission-saved" className="notice">✓ {state.message}</p>
          {state.phase === "PARTIAL" && (
            <div className="space-y-2" data-testid="submission-partial">
              <p className="text-sm text-[#9b782e]">部分成功：参数已持久化，未重复写入。运行恢复失败，可重试。</p>
              <Button variant="outline" size="sm" data-testid="retry-resume" disabled={saving} onClick={doRetryResume}>
                {saving ? "恢复中…" : "重试恢复 / Retry Resume"}
              </Button>
            </div>
          )}
          {state.parameterSetId && <p className="text-xs muted">ParameterSet: {state.parameterSetId}</p>}
        </div>
      ) : state?.phase === "FAILED" ? (
        <div className="space-y-3" data-testid="submission-failed">
          <p role="alert" className="text-sm text-red-700">✗ {state.message}</p>
          <Button variant="outline" size="sm" data-testid="submission-retry" disabled={saving} onClick={doSubmit}>重试 / Retry</Button>
        </div>
      ) : (<form id="sampling-form" onSubmit={e => {e.preventDefault(); void doSubmit();}} className="space-y-4">
        <div className="flex gap-2 items-end">
          <label className="field flex-1">Sampling frequency
            <Input autoFocus data-testid="fs-dialog-value" type="number" min="0" step="any" value={value} onChange={e=>setValue(e.target.value)} placeholder="Enter instrument value" required/>
          </label>
          <label className="field w-24">Unit
            <select data-testid="fs-dialog-unit" className="w-full" value={unit} onChange={e=>setUnit(e.target.value as "Hz"|"kHz"|"MHz")}>
              <option value="Hz">Hz</option>
              <option value="kHz">kHz</option>
              <option value="MHz">MHz</option>
            </select>
          </label>
        </div>
        <label className="field">Instrument record or source<Input value={source} onChange={e=>setSource(e.target.value)} placeholder="e.g. acquisition configuration / lab record" required/></label>
        <details><summary>Where can I find this?</summary><p className="muted text-sm mt-2">Check the acquisition software or instrument configuration. Do not infer this value from the filename, frame interval, or sample count.</p></details>
        <label className="flex gap-2 items-start text-sm">
          <Checkbox checked={verified} onCheckedChange={v => setVerified(!!v)} data-testid="fs-verified-checkbox"/>
          <span>我确认这是仪器记录值（verified）· 未勾选将保存为 UNVERIFIED，canonical TOF 保持待激活。</span>
        </label>
        <p className="muted text-xs">后端以 Hz 规范化存储（{unit} → {Number(value) * (UNIT_FACTORS[unit] ?? 1)} Hz）。绝不从节奏、采样点数或文件名猜测。</p>
        {saving && <p role="status" data-testid="submission-saving" className="text-sm muted">Saving…（保存中，请勿关闭）</p>}
        {state?.phase === "SAVING" && null}
      </form>)}
      <DialogFooter>
        <Button variant="outline" onClick={()=>setOpen(false)}>{state && (state.phase === "SAVED" || state.phase === "PARTIAL") ? "Done" : "Cancel"}</Button>
        {!(state && (state.phase === "SAVED" || state.phase === "PARTIAL")) && !state?.phase.startsWith("FAIL") && (
          <Button type="submit" form="sampling-form" disabled={!valid || saving} data-testid="fs-dialog-save">{saving ? "Saving…" : "Save parameter"}</Button>
        )}
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
