import { useMutation } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { client, type FeatureRankingResponse } from "../../api/client";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from "../ui/table";
import { LoadingState, ErrorState } from "./shared";
import { numberText } from "../../lib/presentation";
import { TARGET_LABELS } from "./FeatureLabelTable";

function DirectionBadge({ entry }: { entry: FeatureRankingResponse["ranking"][number] }) {
  if (entry.direction_dependent) {
    return <Badge variant="outline" data-testid={`direction-dependent-${entry.feature_code}`}>
      <TriangleAlert size={11} className="mr-1" />方向不同 / Direction-dependent</Badge>;
  }
  return <Badge variant="secondary">方向一致 / Consistent</Badge>;
}

/** Feature × Target ranking. Exploratory uses all eligible rows;
 *  TRAIN-only restricts to one grouped-split fold's training rows. */
export function FeatureRankingTable({ batteryId, experimentId, targetId, features, mode }: {
  batteryId: string; experimentId: string; targetId: string; features: string[]; mode: "EXPLORATORY" | "TRAIN_ONLY_ML_SAFE";
}) {
  const rank = useMutation({
    mutationFn: () => client.postFeatureTargetRanking(batteryId, experimentId, {
      target_id: targetId, features, mode,
    }),
  });
  const isSoh = targetId === "soh_capacity_reference_percent";
  const isDirect = targetId === "voltage_v" || targetId === "current_a";
  return <div data-testid="feature-ranking">
    <div className="flex flex-wrap gap-3 items-center">
      <Button onClick={() => rank.mutate()} disabled={!features.length} data-testid="run-ranking-btn">
        Rank features / 特征排序</Button>
      <Badge variant={mode === "EXPLORATORY" ? "outline" : "secondary"} data-testid="ranking-mode-badge">
        {mode === "EXPLORATORY" ? "EXPLORATORY · 非 ML-safe" : "TRAIN-ONLY ML-SAFE"}
      </Badge>
      <span className="text-sm muted">Target (y) / 目标变量: <strong>{TARGET_LABELS[targetId] ?? targetId}</strong></span>
    </div>
    <p className="text-xs muted mt-2">Higher association does not imply causation or guaranteed predictive value. / 较高相关性不代表因果关系，也不保证模型预测能力。</p>
    {rank.isPending && <LoadingState />}
    {rank.error && <ErrorState error={rank.error} retry={() => rank.mutate()} />}
    {rank.data && (() => {
      const d = rank.data.data;
      if (isSoh && d.group_summary) {
        return <div className="mt-4" data-testid="soh-group-summary">
          <p className="text-sm flex gap-2 items-center"><TriangleAlert size={15} className="text-[#9b782e]" />
            仅 {new Set(d.group_summary.map(g => g.soh_percent)).size} 个独立 SOH 状态 — Limited，不做 frame 级相关性结论。</p>
          <Table className="mt-3">
            <TableHeader><TableRow><TableHead>Cycle / 循环</TableHead><TableHead>SOH</TableHead><TableHead>n frames</TableHead><TableHead>Feature mean</TableHead><TableHead>Median</TableHead><TableHead>Std</TableHead></TableRow></TableHeader>
            <TableBody>{d.group_summary.map(g => <TableRow key={g.cycle}>
              <TableCell>{g.cycle}</TableCell><TableCell className="tabular-nums">{numberText(g.soh_percent, 2)}</TableCell>
              <TableCell className="tabular-nums">{g.n_frames}</TableCell>
              <TableCell className="tabular-nums">{numberText(g.feature_mean, 1)}</TableCell>
              <TableCell className="tabular-nums">{numberText(g.feature_median, 1)}</TableCell>
              <TableCell className="tabular-nums">{numberText(g.feature_std, 1)}</TableCell>
            </TableRow>)}</TableBody>
          </Table>
        </div>;
      }
      return <Table className="mt-4">
        <TableHeader><TableRow>
          <TableHead>Feature / 特征</TableHead>
          <TableHead>Pearson / 皮尔逊</TableHead>
          <TableHead>Spearman / 斯皮尔曼</TableHead>
          {!isDirect && <><TableHead>Charge / 充电</TableHead><TableHead>Discharge / 放电</TableHead><TableHead>Direction / 方向</TableHead></>}
          <TableHead>n</TableHead><TableHead>Availability</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {d.ranking.map(r => <TableRow key={r.feature_code} data-testid={`rank-${r.feature_code}`}>
            <TableCell className="font-medium">{r.feature_code}</TableCell>
            <TableCell className="tabular-nums">{numberText(r.pearson_overall ?? r.pearson, 3)}</TableCell>
            <TableCell className="tabular-nums">{numberText(r.spearman_overall ?? r.spearman, 3)}</TableCell>
            {!isDirect && <><TableCell className="tabular-nums">{numberText(r.pearson_charge, 3)}</TableCell>
              <TableCell className="tabular-nums">{numberText(r.pearson_discharge, 3)}</TableCell>
              <TableCell><DirectionBadge entry={r} /></TableCell></>}
            <TableCell className="tabular-nums">{r.n_valid ?? "—"}</TableCell>
            <TableCell>{r.status === "VALID" ? <Badge variant="secondary">VALID</Badge> : <Badge variant="outline">{r.status}</Badge>}</TableCell>
          </TableRow>)}
        </TableBody>
      </Table>;
    })()}
  </div>;
}
