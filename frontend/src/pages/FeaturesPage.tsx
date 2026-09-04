/**
 * 特征清单（§17-19）：CORE 优先，AUXILIARY 折叠，TOF blocked 显示 null+reason。
 * 用户显式勾选 FeatureLocator；UI 只提交选择，不构建 Dataset（§19）。
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { client, type FeatureInfo } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";

function isCore(name: string): boolean {
  return name === "tof_us" || name === "amplitude_a_u";
}

function isPhysical(name: string): boolean {
  return name === "wave_speed_m_s";
}

export function FeatureRow({ f, selected, onToggle }: {
  f: FeatureInfo;
  selected?: boolean;
  onToggle?: (name: string, next: boolean) => void;
}) {
  const blocked = f.availability !== "AVAILABLE";
  return (
    <li data-testid={`feature-${f.feature_name}`} data-availability={f.availability}>
      {onToggle ? (
        <input
          type="checkbox"
          id={`chk-${f.feature_name}`}
          checked={selected ?? false}
          disabled={blocked}
          aria-label={`选择特征 ${f.feature_name}`}
          onChange={(e) => onToggle(f.feature_name, e.target.checked)}
        />
      ) : null}
      <label htmlFor={`chk-${f.feature_name}`}>
        <code>{f.feature_name}</code>
      </label>
      {" — "}
      {blocked ? (
        <strong data-testid={`availability-${f.feature_name}`}>
          {f.availability}
        </strong>
      ) : (
        <span>{f.availability}</span>
      )}
      {f.role ? ` · role: ${f.role}` : null}
      {f.gate_id ? ` · gate: ${f.gate_id}` : null}
      {f.missing_reason ? (
        <p>
          <small>
            原因：{f.missing_reason}（取值保持 null，不显示 0 — §16）
          </small>
        </p>
      ) : null}
    </li>
  );
}

export function FeaturesPage() {
  const { batteryId = "", experimentId = "" } = useParams();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const { data, isLoading, error } = useQuery({
    queryKey: ["features", batteryId, experimentId],
    queryFn: () => client.listFeatures(batteryId, experimentId),
  });

  if (isLoading) return <p role="status">加载特征清单…</p>;
  if (error) return <ErrorBanner error={error} />;
  const features = data?.data.features ?? [];

  const core = features.filter((f) => isCore(f.feature_name));
  const physical = features.filter((f) => isPhysical(f.feature_name));
  const auxiliary = features.filter((f) => !isCore(f.feature_name) && !isPhysical(f.feature_name));

  const toggle = (name: string, next: boolean) => {
    setSelected((prev) => {
      const copy = new Set(prev);
      if (next) copy.add(name);
      else copy.delete(name);
      return copy;
    });
  };

  return (
    <section aria-labelledby="features-title">
      <h2 id="features-title">特征 Features</h2>
      <p>
        <small>
          CORE 特征优先展示；辅助特征折叠。选择即 FeatureLocator，提交后才能进入数据集构建（§19）。
        </small>
      </p>

      <h3>CORE</h3>
      <ul data-testid="core-features">
        {core.map((f) => (
          <FeatureRow key={f.feature_name} f={f} selected={selected.has(f.feature_name)} onToggle={toggle} />
        ))}
      </ul>

      <h3>DERIVED（物理派生）</h3>
      <ul data-testid="physical-features">
        {physical.map((f) => (
          <FeatureRow key={f.feature_name} f={f} selected={selected.has(f.feature_name)} onToggle={toggle} />
        ))}
      </ul>

      <details data-testid="auxiliary-details">
        <summary>辅助特征 AUXILIARY（折叠，{auxiliary.length} 个）</summary>
        <ul data-testid="auxiliary-features">
          {auxiliary.map((f) => (
            <FeatureRow key={f.feature_name} f={f} selected={selected.has(f.feature_name)} onToggle={toggle} />
          ))}
        </ul>
      </details>

      <h3>当前选择（draft — 未确认）</h3>
      <p data-testid="selection-draft">
        {[...selected].length === 0 ? "（未选择任何特征）" : [...selected].join(", ")}
      </p>
      <p>
        <small>
          确认特征选择须走 UserActionRequired / API confirmation（§26）；确认前不得自动构建数据集。
        </small>
      </p>
    </section>
  );
}
