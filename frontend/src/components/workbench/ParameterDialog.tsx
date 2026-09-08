import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { client } from "../../api/client";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../ui/dialog";

export function ParameterDialog({ label = "Add sampling rate" }: { label?: string }) {
  const { batteryId = "", experimentId = "" } = useParams();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [source, setSource] = useState("");
  const [saved, setSaved] = useState(false);
  const save = useMutation({ mutationFn: () => client.createParameters(batteryId, experimentId, {
    values: { "ultrasound.sampling_rate_hz": { value: Number(value), unit: "MHz" } }, source, verified: false,
  }), onSuccess: () => {
    setSaved(true);
    for (const key of ["parameters", "status", "workspace-summary", "data-quality", "synchronization", "features"]) {
      void qc.invalidateQueries({ queryKey: [key, batteryId, experimentId] });
    }
  } });
  const valid = value.trim() !== "" && Number.isFinite(Number(value)) && Number(value) > 0 && source.trim().length > 0;
  return <Dialog open={open} onOpenChange={next => {setOpen(next); if(next) {setSaved(false); save.reset();}}}>
    <DialogTrigger asChild><Button variant="outline" size="sm">{label}</Button></DialogTrigger>
    <DialogContent><DialogHeader><DialogTitle>Sampling frequency</DialogTitle><DialogDescription>Provide the instrument’s waveform sampling frequency for {batteryId} / {experimentId}. Frame cadence is not sampling frequency.</DialogDescription></DialogHeader>
      {saved ? <div role="status" className="notice">Parameter saved. Verification and downstream processing are still required. TOF remains unavailable until the API provides a verified result.</div> : <form id="sampling-form" onSubmit={e => {e.preventDefault(); if(valid) save.mutate();}} className="space-y-4">
        <label className="field">Sampling frequency (MHz)<Input autoFocus type="number" min="0" step="any" value={value} onChange={e=>setValue(e.target.value)} placeholder="Enter instrument value" required/></label>
        <label className="field">Instrument record or source<Input value={source} onChange={e=>setSource(e.target.value)} placeholder="e.g. acquisition configuration / lab record" required/></label>
        <details><summary>Where can I find this?</summary><p className="muted text-sm mt-2">Check the acquisition software or instrument configuration. Do not infer this value from the filename, frame interval, or sample count.</p></details>
        <p className="muted text-sm">Saving records your input and its source. It does not automatically mark the value as verified.</p>
        {save.isError && <p role="alert">Couldn’t save the parameter. Check the value and connection, then retry.</p>}
      </form>}
      <DialogFooter><Button variant="outline" onClick={()=>setOpen(false)}>{saved ? "Done" : "Cancel"}</Button>{!saved && <Button type="submit" form="sampling-form" disabled={!valid || save.isPending}>{save.isPending ? "Saving…" : "Save parameter"}</Button>}</DialogFooter>
    </DialogContent>
  </Dialog>;
}
