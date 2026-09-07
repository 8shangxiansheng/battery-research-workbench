import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";
import type { FramePreviewResponse, GateEntry } from "../../api/client";
const Plot = createPlotlyComponent(Plotly);
export default function WaveformPlot({ preview, gates, draft, mode, reset, onSelect }: {
  preview: FramePreviewResponse; gates: GateEntry[]; draft: {start: number; end: number} | null;
  mode: "zoom" | "pan" | "select"; reset: number; onSelect: (start: number, end: number) => void;
}) {
  const regions = [...gates.filter(g=>g.start_sample!==undefined && g.end_sample!==undefined).map(g=>({start:g.start_sample!,end:g.end_sample!,draft:false})), ...(draft ? [{...draft,draft:true}] : [])];
  return <Plot data={[{x:preview.samples.map(s=>s.sample_index), y:preview.samples.map(s=>s.amplitude_a_u), type:"scatter", mode:"lines", line:{color:"#426976",width:1.35}, name:"Waveform", hovertemplate:"Sample %{x}<br>Amplitude %{y:.3f} a.u.<extra></extra>"}]}
    layout={{autosize:true,height:365,margin:{l:64,r:24,t:28,b:56},paper_bgcolor:"#fff",plot_bgcolor:"#fff",font:{family:"Inter, sans-serif",size:12,color:"#59666d"},showlegend:false,dragmode:mode,selectdirection:"h",uirevision:`${preview.frame_index}-${reset}`,
      xaxis:{title:{text:"Sample index"},gridcolor:"#edf0f0",zeroline:false,range:[0,preview.waveform_length-1]}, yaxis:{title:{text:"Amplitude (a.u.)"},gridcolor:"#edf0f0",zerolinecolor:"#dfe6e5"},
      shapes:regions.map(g=>({type:"rect",xref:"x",yref:"paper",x0:g.start,x1:g.end,y0:0,y1:1,fillcolor:g.draft ? "rgba(162,119,47,.13)" : "rgba(64,113,122,.09)",line:{color:g.draft ? "#9b782e" : "#64868b",width:1,dash:g.draft ? "dot" : "solid"}}))}}
    config={{responsive:true,displayModeBar:false,scrollZoom:true,displaylogo:false}}
    style={{width:"100%",height:365}} useResizeHandler
    onSelected={event=>{if(event?.range?.x){onSelect(Math.round(Math.min(...event.range.x)), Math.round(Math.max(...event.range.x)));}}}
  />;
}
