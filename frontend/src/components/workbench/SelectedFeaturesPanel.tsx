import { useQuery } from "@tanstack/react-query";
import { client } from "../../api/client";
import { Badge } from "../ui/badge";
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from "../ui/table";
import { LoadingState, ErrorState } from "./shared";

const FEATURE_LABELS_ZH: Record<string, string> = {
  amplitude_a_u: "幅值", tof_us: "飞行时间", wave_speed_m_s: "声速",
  waveform_mean_a_u: "均值", waveform_std_a_u: "标准差", waveform_max_a_u: "最大值",
  waveform_min_a_u: "最小值", waveform_p2p_a_u: "峰值差", waveform_rms_a_u: "均方根值",
  waveform_energy_sum_sq_a_u2: "信号平方和", envelope_peak_a_u: "包络峰值",
  xcorr_shift_samples: "相对波形位移",
  SWA: "表面波幅值", BOTTOM_AMP: "底波幅值", TOF_XCORR: "表面波-底波互相关TOF",
  ATTENUATION: "底波衰减", BPS: "底波相移",
};
export function featureLabelBilingual(code: string): string {
  const zh = FEATURE_LABELS_ZH[code];
  const en = code.replaceAll("_", " ");
  return zh ? `${en} / ${zh}` : en;
}

function variantInfo(code: string): { variant: string; eligible: boolean } {
  if (code.toLowerCase().includes("movmean")) return { variant: "SOURCE_MOVMEAN5", eligible: false };
  return { variant: "RAW", eligible: true };
}

/** Selected features with bilingual display + scope/gate/variant/ML eligibility.
 *  Reads the dataset manifest through the API (getArtifact DS::) — no frontend
 *  recomputation. */
export function SelectedFeaturesPanel({ datasetId }: { datasetId: string | null | undefined }) {
  const ds = useQuery({
    queryKey: ["artifact", datasetId],
    queryFn: () => client.getArtifact(datasetId!),
    enabled: !!datasetId,
  });
  if (!datasetId) return null;
  if (ds.isLoading) return <LoadingState />;
  if (ds.error) return <ErrorState error={ds.error} retry={() => void ds.refetch()} />;
  const fields = (ds.data?.data.fields ?? {}) as Record<string, unknown>;
  const selected = (fields.selected_features as string[] | undefined) ?? [];
  if (!selected.length) return null;
  return <section className="panel mt-6 !p-5" data-testid="selected-features">
    <h2>Selected features / 所选特征</h2>
    <p className="muted text-sm mt-1">由后端数据集清单报告（bilingual）。内部 ID 不作为主要显示。</p>
    <Table>
      <TableHeader><TableRow>
        <TableHead>Feature / 特征</TableHead><TableHead>Scope / 范围</TableHead>
        <TableHead>Gate / 闸门</TableHead><TableHead>Variant / 变体</TableHead>
        <TableHead>ML eligibility / 建模资格</TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {selected.map(code => {
          const { variant, eligible } = variantInfo(code);
          const isPhysical = ["SWA", "BOTTOM_AMP", "TOF_XCORR", "ATTENUATION", "BPS"].includes(code);
          return <TableRow key={code} data-testid={`selected-feature-${code}`}>
            <TableCell className="font-medium">{featureLabelBilingual(code)}</TableCell>
            <TableCell>{isPhysical ? "Gate-local / 闸门局部" : "Full waveform / 全波形"}</TableCell>
            <TableCell>{isPhysical ? (code === "SWA" ? "SWA_SURFACE_GATE" : code === "BOTTOM_AMP" ? "BOTTOM_AMPLITUDE_GATE" : code) : "—"}</TableCell>
            <TableCell>{variant}</TableCell>
            <TableCell>{eligible
              ? <Badge variant="secondary">Eligible / 可用</Badge>
              : <Badge variant="outline">Exploratory only / 仅用于探索</Badge>}</TableCell>
          </TableRow>;
        })}
      </TableBody>
    </Table>
  </section>;
}
