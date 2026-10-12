import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { client } from "../../api/client";
import { useInvalidateWorkflow } from "../../hooks/useWorkflowContext";
import { ErrorState, LoadingState } from "./shared";

export function TemperatureChannelSelectionPanel({ batteryId, experimentId }: {
  batteryId: string;
  experimentId: string;
}) {
  const qc = useQueryClient();
  const invalidateWorkflow = useInvalidateWorkflow();
  const [channelId, setChannelId] = useState("");
  const overview = useQuery({
    queryKey: ["research-overview", batteryId, experimentId],
    queryFn: () => client.getResearchOverview(batteryId, experimentId),
    enabled: Boolean(batteryId && experimentId),
  });
  const channels = overview.data?.data.metadata.temperature.channel ?? [];
  useEffect(() => {
    setChannelId("");
  }, [batteryId, experimentId]);
  useEffect(() => {
    if (channels.length === 1 && channels[0]) setChannelId(channels[0]);
    else if (channelId && !channels.includes(channelId)) setChannelId("");
  }, [channels, channelId]);

  const rebuild = useMutation({
    mutationFn: () => client.startRun({
      profile: "INGEST_TO_MEASUREMENT_EVENTS",
      battery_id: batteryId,
      experiment_id: experimentId,
      measurement_events: { temperature_channel_id: channelId },
    }),
    onSuccess: () => {
      invalidateWorkflow(batteryId, experimentId);
      void qc.invalidateQueries({ queryKey: ["targets", batteryId, experimentId] });
      void qc.invalidateQueries({ queryKey: ["alignment-summary", batteryId, experimentId] });
    },
  });

  return <section className="panel mt-4 !p-5" data-testid="temperature-channel-selection">
    <h3 className="font-medium">Electrical 温度通道来源</h3>
    <p className="muted text-sm mt-1">为 MeasurementEvent 明确选择 auxTemp 通道；选择会进入运行计划与来源 manifest。</p>
    {overview.isLoading && <LoadingState />}
    {overview.error && <ErrorState error={overview.error} retry={() => void overview.refetch()} />}
    {overview.data && (channels.length === 0
      ? <p className="notice text-sm mt-3" data-testid="temperature-channel-unavailable">当前 processed auxTemp 没有可选的温度 channel ID；不会猜测或合并通道。</p>
      : <div className="mt-3 grid gap-3">
        <label className="text-sm" htmlFor="temperature-channel-id">用于事件关联的 channel ID</label>
        <select id="temperature-channel-id" className="input" value={channelId}
          onChange={(event) => setChannelId(event.target.value)} data-testid="temperature-channel-select">
          <option value="" disabled>请选择已登记的通道</option>
          {channels.map((channel) => <option key={channel} value={channel}>{channel}</option>)}
        </select>
        <p className="text-xs muted">观察到的通道：{channels.join("、")}。此选择仅决定采用哪个读数，不验证传感器位置、校准或温度目标的科学适用性。</p>
        <button type="button" className="button w-fit" disabled={!channelId || rebuild.isPending}
          onClick={() => rebuild.mutate()} data-testid="rebuild-temperature-channel">
          {rebuild.isPending ? "正在重建 MeasurementEvent…" : "应用通道并重建 MeasurementEvent"}
        </button>
        {rebuild.error && <p role="alert" className="notice text-sm">运行未启动：{(rebuild.error as Error).message}</p>}
        {rebuild.data && <p role="status" className="text-sm" data-testid="temperature-channel-run-started">
          重建运行已提交；同步、温度校准等其它科学门状态不会因此自动升级。<Link className="underline ml-1" to="/runs">前往 Runs 查看进度</Link>
        </p>}
      </div>)}
  </section>;
}
