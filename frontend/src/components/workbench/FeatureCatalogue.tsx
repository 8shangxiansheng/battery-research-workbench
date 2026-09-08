import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { client, type FeatureDefinitionEntry } from "../../api/client";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Checkbox } from "../ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../ui/dialog";
import { Input } from "../ui/input";
import { ErrorState, LoadingState } from "./shared";

/** BRW-013X V2 catalogue grouping — Core first, then MATLAB families. */
const CORE_CODES = ["amplitude_a_u", "tof_us", "wave_speed_m_s"];
const PHYSICAL_CODES = ["BOTTOM_AMP", "SWA", "TOF_XCORR", "ATTENUATION", "ATTEN_HF_ENERGY"];
const PHASE_CODES = ["BPS"];

function statusBadge(f: FeatureDefinitionEntry) {
  if (f.definition_status === "DEFINED_AND_VALIDATED") return <Badge variant="secondary">已验证 / Validated</Badge>;
  return <Badge variant="outline">待 MATLAB 对齐 / Parity pending</Badge>;
}

export function FeatureDetailDialog({ feature, onClose }: { feature: FeatureDefinitionEntry | null; onClose: () => void }) {
  return <Dialog open={!!feature} onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{feature?.display_name_en} / {feature?.display_name_zh}</DialogTitle>
        <DialogDescription>
          {feature?.code} · {feature?.family === "TD" ? "Time-domain / 时域" : "Frequency-domain / 频域"}
        </DialogDescription>
      </DialogHeader>
      {feature && <dl className="grid grid-cols-[120px_1fr] gap-x-4 gap-y-2 text-sm" data-testid="feature-detail">
        <dt className="muted">Formula / 公式</dt><dd><code className="text-xs">{feature.formula_text}</code></dd>
        <dt className="muted">Units / 单位</dt><dd>{feature.units}</dd>
        <dt className="muted">Scope / 作用范围</dt><dd>{feature.scope.join(" · ")}</dd>
        <dt className="muted">Validation / 验证</dt><dd>{statusBadge(feature)}<span className="ml-2 text-xs muted">{feature.parity_status}</span></dd>
        <dt className="muted">Version / 版本</dt><dd>{feature.formula_policy_version}</dd>
        <dt className="muted">Source / 来源</dt><dd><code className="text-xs">{feature.formula_source_id}</code></dd>
        {feature.existing_alias && <><dt className="muted">Alias / 别名</dt><dd className="text-xs muted">{feature.existing_alias}（语义一致的历史特征）</dd></>}
      </dl>}
    </DialogContent>
  </Dialog>;
}

export function FeatureCatalogue({ selected, onToggle, availableNames = [] }: {
  selected: string[];
  onToggle: (code: string) => void;
  availableNames?: string[];
}) {
  const catalogue = useQuery({ queryKey: ["feature-definitions"], queryFn: () => client.listFeatureDefinitions() });
  const [query, setQuery] = useState("");
  const [detail, setDetail] = useState<FeatureDefinitionEntry | null>(null);

  const entries = catalogue.data?.data.catalogue ?? [];
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter(f =>
      f.code.toLowerCase().includes(q) || f.display_name_en.toLowerCase().includes(q)
      || f.display_name_zh.includes(query.trim()));
  }, [entries, query]);

  if (catalogue.isLoading) return <LoadingState />;
  if (catalogue.error) return <ErrorState error={catalogue.error} retry={() => void catalogue.refetch()} />;

  const coreEntries = filtered.filter(f => CORE_CODES.includes(f.code));
  const physicalEntries = filtered.filter(f => PHYSICAL_CODES.includes(f.code));
  const phaseEntries = filtered.filter(f => PHASE_CODES.includes(f.code));
  const tdEntries = filtered.filter(f => f.family === "TD" && !CORE_CODES.includes(f.code));
  const fdEntries = filtered.filter(f => f.family === "FD");

  function renderGroup(label: string, items: FeatureDefinitionEntry[]) {
    if (!items.length) return null;
    const resolvedName = (f: FeatureDefinitionEntry) =>
      f.existing_alias && availableNames.includes(f.existing_alias) ? f.existing_alias : f.code;
    return <section className="mb-6" data-testid={`feature-group-${label.split(" /")[0]}`}>
      <h4 className="text-sm font-medium mb-2">{label} <span className="muted">({items.length})</span></h4>
      <div className="grid md:grid-cols-3 gap-3">
        {items.map(f => <div key={f.code} className="feature-card" data-testid={`catalogue-${f.code}`}>
          <div className="flex items-start gap-3">
            <Checkbox aria-label={`Select ${f.display_name_en}`} checked={selected.includes(resolvedName(f))}
              onCheckedChange={() => onToggle(resolvedName(f))} data-testid={`select-${f.code}`} />
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-medium truncate">{f.display_name_en} / {f.display_name_zh}</h3>
              <p className="text-xs muted mt-1 truncate">{f.code} · {f.units}</p>
            </div>
          </div>
          <div className="mt-3 flex gap-2 items-center flex-wrap">{statusBadge(f)}
            <Button variant="link" size="sm" className="px-0 h-auto" onClick={() => setDetail(f)}>详情 / Details</Button>
          </div>
        </div>)}
      </div>
    </section>;
  }

  return <div data-testid="feature-catalogue">
    <div className="flex gap-3 items-center mb-4">
      <label className="relative flex-1 max-w-sm">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 muted" aria-hidden />
        <Input aria-label="搜索特征 / Search features" placeholder="搜索特征 / Search features" className="!pl-9"
          value={query} onChange={e => setQuery(e.target.value)} />
      </label>
      <span className="text-xs muted">来源 / Source: <code>{catalogue.data?.data.formula_source_id}</code></span>
    </div>
    {renderGroup("核心特征 / Core", coreEntries)}
    {renderGroup("时域特征 / Time-Domain", tdEntries)}
    {renderGroup("频域特征 / Frequency-Domain", fdEntries)}
    {renderGroup("物理特征 / Physical", physicalEntries)}
    {renderGroup("相位特征 / Phase", phaseEntries)}
    {!coreEntries.length && !tdEntries.length && !fdEntries.length && !physicalEntries.length && !phaseEntries.length
      && <p className="muted text-sm" role="status">没有匹配 “{query}” 的特征。/ No features match “{query}”.</p>}
    <FeatureDetailDialog feature={detail} onClose={() => setDetail(null)} />
  </div>;
}
