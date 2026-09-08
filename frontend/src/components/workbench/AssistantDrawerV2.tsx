import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useLocation, useParams } from "react-router-dom";
import { useAssistant } from "./AssistantContext";
import { ArrowUpRight, CircleAlert, Lock, MessageSquare, SendHorizonal } from "lucide-react";
import { client, type AssistantSession } from "../../api/client";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetTrigger } from "../ui/sheet";

const PAGE_LABELS: Record<string, string> = {
  overview: "总览 / Overview", waveform: "波形与闸门 / Waveform", analysis: "特征分析 / Analysis",
  models: "SOC 建模 / Models", report: "科学报告 / Report",
};
const PHASE_LABELS: Record<string, string> = {
  UNDERSTAND_GOAL: "理解目标 / Understand goal",
  SELECT_TARGET: "选择目标 / Select target",
  CHECK_TARGET_READINESS: "目标就绪 / Target readiness",
  CHECK_ALIGNMENT: "检查对齐 / Alignment",
  CHECK_GATE_READINESS: "闸门就绪 / Gate readiness",
  INSPECT_FEATURES: "浏览特征 / Features",
  ANALYZE_RELATIONSHIPS: "分析关系 / Relationships",
  CHOOSE_PATH: "选择路径 / Choose path",
  EXPLORATORY_RESULT: "探索结果 / Exploratory result",
  CHECK_GROUPED_SPLIT: "分组划分 / Grouped split",
  TRAIN_ONLY_FEATURE_SELECTION: "TRAIN-only 选择 / Train-only selection",
  CONFIRM_SELECTION: "确认选择 / Confirm selection",
  BUILD_DATASET: "构建数据集 / Build dataset",
  RUN_BASELINES: "运行基线 / Run baselines",
  INTERPRET: "解读 / Interpret",
  REPORT: "报告 / Report",
  WAITING_FOR_USER: "等待输入 / Waiting for you",
};

export function AssistantDrawer() {
  const { batteryId = "", experimentId = "" } = useParams();
  const { setOpen, open: drawerOpen } = useAssistant();
  const location = useLocation();
  const page = PAGE_LABELS[location.pathname.split("/").filter(Boolean).pop() ?? "overview"] ?? "高级 / Advanced";
  const session = useQuery({
    queryKey: ["assistant-session", batteryId, experimentId],
    queryFn: () => client.openAssistantSession(batteryId, experimentId),
    staleTime: Infinity,
  });
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<{ role: string; message: string; status?: string }[]>([]);
  const [current, setCurrent] = useState<AssistantSession | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (session.data?.data) {
      setCurrent(session.data.data);
      setTurns(session.data.data.conversation.slice(-8).map(c => ({ role: c.role, message: c.message })));
    }
  }, [session.data]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [turns.length]);

  const send = useMutation({
    mutationFn: (message: string) =>
      client.sendAssistantMessage(batteryId, experimentId, current!.session_id, message, location.pathname),
    onSuccess: r => {
      setCurrent(r.data.session);
      setTurns(prev => [...prev,
        { role: "user", message: draft },
        { role: "assistant", message: r.data.message, status: r.data.status }]);
      setDraft("");
    },
    onError: () => setTurns(prev => [...prev,
      { role: "assistant", message: "助手处理失败，请稍后重试。", status: "FAILED" }]),
  });
  function submit(text?: string) {
    const msg = (text ?? draft).trim();
    if (!msg || send.isPending || !current) return;
    setTurns(prev => [...prev, { role: "user", message: msg }]);
    send.mutate(msg);
  }

  const phase = current?.phase ?? "UNDERSTAND_GOAL";
  return <Sheet open={drawerOpen} onOpenChange={setOpen}>
    <SheetTrigger asChild>
      <Button variant="ghost" aria-label="Research Assistant"><MessageSquare /><span className="hidden sm:inline">Research Assistant</span></Button>
    </SheetTrigger>
    <SheetContent className="sm:max-w-[440px] w-full flex flex-col">
      <SheetHeader><SheetTitle>科研助手 / Research Assistant</SheetTitle>
        <SheetDescription>意图与流程编排；科学数值全部来自确定性后端工具。</SheetDescription></SheetHeader>
      <div className="flex-1 overflow-y-auto space-y-4 pb-4" data-testid="assistant-drawer">
        {/* current context */}
        <div className="panel !p-3" data-testid="assistant-context">
          <p className="eyebrow">当前上下文 / Context</p>
          <p className="text-sm font-medium mt-1">{batteryId} / {experimentId} <Badge variant="outline" className="ml-1">{page}</Badge></p>
          <p className="text-xs muted mt-1">Phase: {PHASE_LABELS[phase] ?? phase}</p>
          {current?.selected_target && <p className="text-xs muted">Target: {current.selected_target} · {current.target_readiness ?? "—"}</p>}
          {current?.selected_features?.length ? <p className="text-xs muted">Features: {current.selected_features.join(", ")}</p> : null}
        </div>
        {/* conversation */}
        <div className="space-y-2" data-testid="assistant-conversation" aria-live="polite">
          {turns.length === 0 && <p className="text-sm muted">试试： “帮我研究SOC” / “同步对齐怎么样？” / “训练SOH模型” / “随机80/20训练测试”。</p>}
          {turns.map((t, i) => <div key={i} className={t.role === "user" ? "text-sm text-right" : "text-sm"}>
            {t.role === "user"
              ? <span className="inline-block bg-[#e9f1ef] rounded-lg px-3 py-2 max-w-[90%] text-left">{t.message}</span>
              : <div className={`rounded-lg px-3 py-2 max-w-[95%] whitespace-pre-wrap ${t.status === "SCIENTIFIC_BLOCK" || t.status === "WAITING_FOR_USER" || t.status === "BLOCKED" ? "bg-[#f7f0e2]" : "bg-[#f0f3f2]"}`}
                  data-testid={t.status === "SCIENTIFIC_BLOCK" ? "assistant-block" : "assistant-answer"}>
                  {t.status === "SCIENTIFIC_BLOCK" && <CircleAlert size={13} className="inline mr-1 text-[#9b782e]" />}
                  {t.message}
                </div>}
          </div>)}
          {send.isPending && <p className="text-xs muted" role="status">助手思考中…</p>}
          <div ref={bottomRef} />
        </div>
        {/* pending / confirmation card */}
        {current?.pending_user_action && <div className="notice !py-3" data-testid="assistant-pending">
          <p className="text-sm font-medium">等待你的输入 / Waiting for your input</p>
          <pre className="text-xs mt-1 whitespace-pre-wrap">{JSON.stringify(current.pending_user_action, null, 1).slice(0, 300)}</pre>
        </div>}
        {/* next actions (1-3) */}
        {current?.next_actions?.length ? <div data-testid="assistant-next-actions">
          <p className="eyebrow mb-2">建议下一步 / Next actions</p>
          <div className="space-y-1.5">
            {current.next_actions.slice(0, 3).map(a => <Button key={a.action_id} variant="outline" size="sm"
              className="w-full justify-start h-auto whitespace-normal"
              onClick={() => submit(a.label_zh)}>{a.label_zh}<ArrowUpRight className="ml-auto" size={14} /></Button>)}
          </div>
        </div> : null}
      </div>
      {/* input */}
      <div className="border-t pt-3 flex gap-2 items-center">
        <Input aria-label="向科研助手提问" placeholder="问一个问题…" value={draft}
          onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === "Enter") submit(); }}
          data-testid="assistant-input" />
        <Button size="icon" aria-label="发送" disabled={!draft.trim() || send.isPending || !current}
          onClick={() => submit()} data-testid="assistant-send"><SendHorizonal size={16} /></Button>
      </div>
      <p className="text-[10px] muted mt-2 flex gap-1 items-center">
        <Lock size={11} />科学数值由确定性工具计算；助手不记录思维链，仅记录会话与证据引用。</p>
    </SheetContent>
  </Sheet>;
}
