import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { NavLink, Link, Route, Routes, useParams, useLocation, useNavigate, Navigate } from "react-router-dom";
import { Activity, ArrowUpRight, ChartNoAxesCombined, Check, ChevronsUpDown, FileText, FlaskConical, LayoutDashboard, Library, MessageSquare, Settings2, Waves } from "lucide-react";
import { client } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "../../components/ui/popover";
import { Command, CommandInput, CommandList, CommandEmpty, CommandItem } from "../../components/ui/command";
import { Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { SidebarProvider, Sidebar, SidebarHeader, SidebarContent, SidebarFooter, SidebarMenu, SidebarMenuItem, SidebarMenuButton, SidebarInset, SidebarTrigger, SidebarGroup } from "../../components/ui/sidebar";
import { OverviewPage } from "./OverviewPage";
import { WaveformWorkbench } from "./WaveformWorkbench";
import { AnalysisWorkbench } from "./AnalysisWorkbench";
import { ModelsWorkbench } from "./ModelsWorkbench";
import { ReportWorkbench } from "./ReportWorkbench";
import { AdvancedPage } from "./AdvancedPage";
import { ExperimentLibraryPage } from "../LibraryPage";
import { NewExperimentWizardPage } from "../NewExperimentWizardPage";
import { RunsPage } from "../RunsPage";

const navigation = [
  { path: "overview", label: "总览", icon: LayoutDashboard }, { path: "waveform", label: "波形与闸门", icon: Waves },
  { path: "analysis", label: "特征分析", icon: Activity }, { path: "models", label: "SOC 建模", icon: ChartNoAxesCombined }, { path: "report", label: "科学报告", icon: FileText },
];
export function ExperimentSwitcher() {
  const { batteryId, experimentId } = useParams(); const [open, setOpen] = useState(false); const navigate = useNavigate();
  const library = useQuery({ queryKey: ["library-switcher"], queryFn: () => client.listLibraryExperiments({limit: 200}) });
  const entries = library.data?.data.experiments ?? []; const current = entries.find(e=>e.battery_id===batteryId && e.experiment_id===experimentId);
  return <div className="flex items-center gap-3 min-w-0"><Popover open={open} onOpenChange={setOpen}><PopoverTrigger asChild>
    <Button role="combobox" aria-expanded={open} aria-label="切换实验" variant="ghost" className="max-w-[320px] text-left"><FlaskConical/><span className="truncate">{batteryId} / {experimentId}</span><ChevronsUpDown className="ml-2 opacity-60"/></Button>
  </PopoverTrigger><PopoverContent className="w-80 p-0" align="start"><Command><CommandInput placeholder="搜索实验…"/><CommandList><CommandEmpty>{library.isLoading ? "加载实验…" : library.isError ? "实验列表加载失败。" : "未找到实验。"}</CommandEmpty>
    {entries.map(e=><CommandItem key={e.experiment_composite_id} value={`${e.name} ${e.battery_id} ${e.experiment_id}`} onSelect={()=>{navigate(`/experiments/${e.battery_id}/${e.experiment_id}/overview`);setOpen(false);}}><FlaskConical/><div>{e.name}<p className="text-xs muted">{e.battery_id} / {e.experiment_id}</p></div>{e.experiment_id===experimentId && e.battery_id===batteryId && <Check className="ml-auto"/>}</CommandItem>)}
  </CommandList></Command><div className="border-t p-2"><Button variant="ghost" asChild className="w-full justify-start"><Link to="/">打开实验库<ArrowUpRight/></Link></Button></div></PopoverContent></Popover>{current?.is_demo && <Badge variant="outline">Demo</Badge>}</div>;
}
export function AssistantDrawer() {
  const { batteryId, experimentId } = useParams(); const location = useLocation(); const [question, setQuestion] = useState("");
  const page = navigation.find(n=>location.pathname.endsWith(n.path))?.label ?? "高级";
  return <Sheet><SheetTrigger asChild><Button className="assistant-trigger"><MessageSquare/>Research Assistant</Button></SheetTrigger>
    <SheetContent className="sm:max-w-[420px] w-full"><SheetHeader><SheetTitle>科研助手</SheetTitle><SheetDescription>来自当前工作区的上下文。</SheetDescription></SheetHeader>
      <div className="py-8 space-y-8"><div className="panel"><p className="eyebrow">当前上下文</p><p className="font-medium">{batteryId} / {experimentId}</p><p className="muted text-sm mt-1">{page}</p></div>
        <div><h3 className="mb-3">可以探索的问题</h3><div className="space-y-2">{["这个实验能分析什么？", "为什么 TOF 不可用？", "有没有模型跑赢 Dummy？"].map(q=><Button key={q} variant="outline" className="w-full justify-start whitespace-normal h-auto py-3 text-left" onClick={()=>setQuestion(q)}>{q}<ArrowUpRight className="ml-auto shrink-0"/></Button>)}</div></div>
        {question && <div role="status" className="notice">Selected question: {question} 尚未发送任何请求。</div>}
        <div className="border-t pt-6"><Badge variant="secondary">助手未连接</Badge><p className="text-sm muted mt-3">本版本未启用科学问答与工具执行。请在工作台中查看结果、限制与证据。</p></div>
      </div>
    </SheetContent>
  </Sheet>;
}
function ExperimentLayout() {
  const { batteryId = "", experimentId = "" } = useParams(); const base = `/experiments/${batteryId}/${experimentId}`;
  return <SidebarProvider><a href="#main-content" className="skip-link">跳转到正文</a><Sidebar>
    <SidebarHeader className="px-6 py-6"><Link to="/" className="flex gap-3 items-center font-semibold text-base"><span className="rounded-md bg-primary p-2 text-white"><Waves size={20}/></span>工作台</Link></SidebarHeader>
    <SidebarContent><SidebarGroup className="px-4 pt-8"><p className="eyebrow px-3 mb-4">实验</p><nav aria-label="主导航"><SidebarMenu>{navigation.map(n=><SidebarMenuItem key={n.path}><SidebarMenuButton asChild className="h-11 mb-1"><NavLink to={`${base}/${n.path}`} className={({isActive})=>isActive ? "!bg-sidebar-accent !text-sidebar-accent-foreground font-medium" : ""}><n.icon/><span>{n.label}</span></NavLink></SidebarMenuButton></SidebarMenuItem>)}</SidebarMenu></nav></SidebarGroup></SidebarContent>
    <SidebarFooter className="px-4 pb-6"><SidebarMenu><SidebarMenuItem><SidebarMenuButton asChild className="h-11"><NavLink to={`${base}/advanced/parameters`}><Settings2/><span>高级</span></NavLink></SidebarMenuButton></SidebarMenuItem><SidebarMenuItem><SidebarMenuButton asChild className="h-11"><Link to="/"><Library/><span>实验库</span></Link></SidebarMenuButton></SidebarMenuItem></SidebarMenu><p className="text-xs muted px-3 pt-5">电池科研工作台</p></SidebarFooter>
  </Sidebar><SidebarInset className="bg-[#fafbfa] min-w-0"><div className="app-topbar"><SidebarTrigger/><div className="h-5 border-l"/><ExperimentSwitcher/><span className="ml-auto text-xs muted hidden lg:block">科研工作台</span></div>
  <main id="main-content" className="app-content w-full" key={`main-${batteryId}/${experimentId}`}><Routes>
    <Route index element={<Navigate to="overview" replace/>}/><Route path="overview" element={<OverviewPage/>}/><Route path="waveform" element={<WaveformWorkbench/>}/><Route path="analysis" element={<AnalysisWorkbench/>}/><Route path="models" element={<ModelsWorkbench/>}/><Route path="report" element={<ReportWorkbench/>}/><Route path="advanced/:section" element={<AdvancedPage/>}/>
    <Route path="modeling" element={<Navigate to={`${base}/models`} replace/>}/><Route path="reports" element={<Navigate to={`${base}/report`} replace/>}/><Route path="features" element={<Navigate to={`${base}/analysis`} replace/>}/>
    {['data','dataset-split','evidence','workspace','runs'].map(p=><Route key={p} path={p} element={<Navigate to={`${base}/advanced/${p}`} replace/>}/>)}<Route path="*" element={<Navigate to={`${base}/overview`} replace/>}/>
  </Routes></main><AssistantDrawer key={`drawer-${batteryId}/${experimentId}`}/></SidebarInset></SidebarProvider>;
}
export function AppRoutes() { return <Routes><Route path="/" element={<div className="app-content"><ExperimentLibraryPage/></div>}/><Route path="/new" element={<div className="app-content"><NewExperimentWizardPage/></div>}/><Route path="/new/:sessionId" element={<div className="app-content"><NewExperimentWizardPage/></div>}/><Route path="/runs" element={<div className="app-content"><Button variant="outline" asChild><Link to="/">Back to library</Link></Button><RunsPage/></div>}/><Route path="/experiments/:batteryId/:experimentId/*" element={<ExperimentLayout/>}/><Route path="*" element={<Navigate to="/" replace/>}/></Routes>; }
