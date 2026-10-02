# Battery Research Workbench 使用指南

本文面向实验人员，介绍如何启动工作台、导入数据、检查科学前置条件、分析特征并生成数据集、模型评估与报告。界面以当前仓库版本为准；功能状态可能随版本变化。

## 1. 启动工作台

### Docker Compose（推荐）

在仓库根目录运行：

```bash
docker compose up --build -d
```

浏览器打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。检查服务：

```bash
docker compose ps
curl http://127.0.0.1:8000/api/v1/health
```

健康检查应返回 `{"status":"ok"}`。停止服务使用 `docker compose down`；这不会删除宿主机映射的数据目录。

默认端口为 `8000`，可通过环境变量 `BRW_PORT` 修改。默认只绑定本机回环地址。当前 API 没有认证机制，不要将服务直接暴露到不可信网络；远程访问应放在配置了认证和 TLS 的反向代理之后。

Windows 电脑可安装 Docker Desktop，启用 WSL 2 backend 和 Linux containers，然后把仓库放在 Windows 可访问的目录中，在项目根目录执行相同的 `docker compose` 命令。源码更新可通过 Git 同步后重新构建：

```bash
git pull
docker compose up --build -d
```

Compose 将 `data/raw`、`data/processed` 和 `data/artifacts` 映射到容器外部。换电脑或更新源码前，请备份需要保留的实验数据与产物；不要把原始数据当作源码更新覆盖。Docker Desktop 的 Linux 容器不等于原生 Windows 容器。

只读分析部署可设置 `BRW_RAW_READ_ONLY=true`；此时导入新原始数据不可用。其他环境变量和权限说明见根目录 [README](../README.md) 的 Docker deployment 一节。

### 本地开发模式

先在仓库根目录启动 API：

```bash
.venv/bin/uvicorn battery_workbench.api.serve:app --port 8000
```

再开一个终端启动前端：

```bash
cd frontend
npm install
npm run dev
```

打开 Vite 输出的本地地址（通常是 `http://localhost:5173`）。开发服务器会将 `/api/v1` 请求代理到本机 API。也可运行 `npm run build` 构建前端。

### 模型接入（Assistant 意图理解，可选）

Assistant 的 LLM 只做意图理解（把一句话映射为意图/目标/特征枚举），不做任何科学计算；不配 key 时自动用关键词规则，功能不受影响。支持任何 OpenAI 兼容接口（DeepSeek / OpenAI / 通义 / 自建网关）。

```bash
cp .env.example .env   # .env 含密钥，已被 git 忽略，切勿提交
```

然后用文本编辑器打开 `.env`，一次只启用一组（以 DeepSeek 为例）：

```bash
OPENAI_API_KEY=sk-你的key
OPENAI_BASE_URL=https://api.deepseek.com
BRW_LLM_MODEL=deepseek-chat
```

其它供应商模板见 `.env.example` 中的 B/C/D 组注释。改完 `.env` 后：

- Docker 部署：`docker compose up --build -d` 重建容器生效（compose 读取 `.env` 做变量插值）。
- 本地开发：重启 API 进程即可（backend 会兜底读取仓库根 `.env`，无需 `export`）。

## 2. 了解实验身份与文件组织

工作台用 **Battery → Experiment → DataAsset** 标识数据，不以文件名或 Cycle 作为数据身份。一个实验可以有多个电学 XLSX 和超声 TXT；导入时请确认电池与实验身份、文件类型和科学元数据。

当前支持的导入格式：

- 电学数据：`.xlsx`
- 超声数据：`.txt`

旧样例的典型文件位于：

```text
data/raw/batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx
data/raw/batteries/CELL_001/EXP_001/ultrasound/export - 2024.01.06 - 21.03.01.txt
```

生产导入应通过界面的“新建实验”向导完成，让系统登记 manifest、资产校验和文件 checksum。不要手动改写既有 raw 文件；如果同一实验有多个文件，都应分别作为资产登记。

## 3. 新建实验并导入数据

从实验库进入“新建实验”，按向导完成：

1. **实验信息**：填写 Battery ID 和实验名称；Experiment ID 可按界面规则自动生成。不要从文件名推断身份。
2. **数据资产**：分别上传电学 XLSX 和超声 TXT。检查文件角色、名称、大小和 checksum。
3. **格式检测**：确认系统检测出的格式/解析器。若结果有歧义，必须人工选择；不支持的格式不能继续。
4. **预览与验证**：分别阅读格式有效性、科学元数据完整性和流水线就绪状态。格式通过不代表科学参数已齐全。
5. **科学元数据**：尽可能提供采样率、时间锚点及实验所需的设备/几何信息。无法确认的值应留空或标记未知，不要猜测。
6. **提交**：复核身份、资产和限制后确认导入。提交登记数据资产；需要处理数据时，再明确点击“开始数据处理”。

如果采样率未知，导入可以继续，但依赖绝对时间/频率的分析（例如物理 TOF）会保持阻断，不能将未知值填成 0 或猜测值。

## 4. 按实验工作流分析

打开实验后，先在 **Overview（总览）** 查看当前状态、下一步建议、数据概况和限制。工作流导航会标注已完成、当前步骤和阻断步骤；阻断时按页面提供的恢复入口补齐前置条件。

建议按以下顺序操作：

### 4.1 Target：选择研究目标

在“特征分析”中选择目标，例如 Reference SOC。查看目标来源、覆盖率、范围和限制。当前 CELL_001 的 Reference SOC 是回顾性分段归一化参考标签，不是真实 SOC。Temperature 目标走数据驱动门：有温度通道且极差 ≥ 2°C 时放行，否则仍拒收并给出原因；SOH 只有两个独立状态，不能把逐帧重复值当成大量独立样本。

### 4.2 Alignment：检查同步

查看匹配、歧义、未匹配数量及同步误差。只有唯一匹配的 MeasurementEvent 才能安全进入分析；歧义记录不会静默挑选电学行。注意区分“已按暂定时间基准对齐”和“时间基准已验证”：`PROVISIONAL` 不代表同步已验证。

### 4.3 Waveform：检查波形与闸门

在“波形与闸门”查看超声 A-scan、缩放/平移和已配置的局部采样窗口。草稿闸门需要按界面动作确认后才成为已提交配置。闸门定义的是单帧波形内部的样本区间；由该帧提取的特征共享同一个电学 MeasurementEvent，不会因为选了不同闸门而自动获得不同电学时刻。

若页面要求 sampling rate 或时间基准，使用页面的参数/校准入口补齐并验证。TOF 前置条件未满足时应显示 blocked 状态和原因，不应把 0 当作有效 TOF。

### 4.4 Features 与 Relationships：提取和检查特征

浏览可用特征、单位、来源和覆盖率。先在 Exploratory 模式查看整体关系，再按需要检查 Overall、Charge、Discharge 等分组结果。Feature Ranking 是关联/排序证据，不等同因果关系，也不自动证明预测能力。

canonical `tof_us` 只有在当前配置确实满足采样率、闸门/校准与来源要求时才可用于分析。缺失、过期或不适用的特征会有状态说明；不要用历史结果替代当前参数定义。

### 4.5 Selection 与 Preview：确认 X、y 和样本

选择预测特征作为 X，并确认目标只对应一个 y。进入 Feature–Label Preview 后检查：

- 行数、纳入/排除数量及排除原因；
- 每列定义、单位和来源；
- 若干行的 provenance（原始 DataAsset、帧、电学记录、MeasurementEvent 和同步误差）；
- 当前特征/标签配置是否与预期一致。

ML-safe Review 会依据分组 split 处理训练集与 held-out 数据。held-out y 由后端遮蔽是防止泄漏的预期行为，不是缺陷。修改特征选择或目标后，应重新检查 Preview 和产物新鲜度。

### 4.6 Dataset 与 Split：构建数据集和分组划分

确认数据集的目标、特征、样本粒度和排除统计后，再创建 grouped split。此项目要求按 Battery 分组，禁止随机拆分帧/行来伪造独立泛化证据。可用分组不足时，模型步骤会阻断；不要通过放松分组规则绕过。

### 4.7 Models 与 Report：评估并报告

只有当前数据集存在合法 grouped split 后，才继续模型训练/比较。查看 Dummy baseline、评估范围、fold 信息和结果新鲜度。若模型没有超过 Dummy，应如实保留该结论。当前没有超参数调优功能，不能将固定基线对比描述为已完成调优。

在 Models 页面的建模入口可勾选参与本次运行的策略：默认仅勾选 Dummy 参考基线，其余策略（含 Elastic net、Huber 回归、MLP）按需勾选；至少保留 1 个策略才能启动。策略目录由后端注册表提供，新注册的固定基线会自动出现在勾选项中，无需前端改动。所有策略均为固定配置、无调参；其中 MLP 为 sklearn 单隐层（50 单元，lbfgs 求解器），确定性可复现。

生成报告前确认报告引用的是当前 dataset、split 和模型评估，而不是旧版本 artifact。报告中的数值应与其证据来源和数据限制一起解释。

### 4.8 跨电池 Cohort 与 LOBO

Models 页面另有“建立跨电池队列”和“Battery-level LOBO”入口。只有在至少准备好 2 块不同电池、且每块都有 manifest-backed SOC 数据集后，才有条件建立队列。还必须核对参考标签的公式/时间语义、特征定义版本和单位；系统不做单位换算。创建队列时需填写 harmonization policy 和 evidence references，服务端会再校验来源和 checksum。来源变化后旧队列会过期，应基于最新 source datasets 新建版本。

队列就绪后可运行固定基线 LOBO：每折留出一块电池，主要指标按电池等权汇总；pooled-row 数值只是诊断项。该流程不做超参数调优。当前仓库的真实样例只有 CELL_001 一块电池，因此该入口会显示阻断状态；登记了多块电池或通过合成测试，都不能代替第二块真实兼容电池的证据。

## 5. 状态、过期结果与常见问题

- **BLOCKED**：前置条件不满足；阅读页面给出的原因与 required action，并使用链接返回对应步骤。
- **WAITING_FOR_USER**：系统在等待明确的人类选择/确认；完成确认后再恢复流程。
- **PROVISIONAL**：使用暂定时间基准或有限证据；不应表述为已验证同步。
- **STALE**：上游配置/数据已变化，当前结果不能代表最新定义；回到对应步骤重新检查并重建下游结果。
- **UNKNOWN / NOT_AVAILABLE**：数据来源缺失或当前不可用；不是 0，也不应手动伪造。
- **HELD_OUT 值被遮蔽**：ML-safe 流程的防泄漏行为；训练数据不应读取 held-out 标签。
- **页面暂时无数据**：先确认 API 健康（`/api/v1/health`），再检查当前 Battery/Experiment 和资产状态；不要仅凭旧截图判断当前结果。

## 6. 当前科学边界

使用当前样例时请在分析与报告中保留以下限制：

- 样例只有 CELL_001 单电池、EXP_001 两个循环；不能据此声称跨电池泛化。
- 时间基准仍可能为 provisional，需在 Alignment 页面核实当前状态。
- Reference SOC 是回顾性参考标签，不等于独立测得的真实 SOC。
- 当前样例缺温度通道（温度目标需有通道且极差 ≥ 2°C 才放行）；SOH 独立状态数不足以支撑稳健的逐帧建模结论。
- Dummy baseline 未被模型超过时，应如实报告；固定基线比较不等于超参数调优。
- 特征相关、Ranking 和模型误差都受样本数量、分组结构、同步质量与标签定义限制。

在获得更多独立电池、循环/健康状态、经验证时间基准和必要传感器通道之前，结果应解释为当前实验内的有限探索或有限评估。

## 7. 数据保护与求助信息

- `data/raw/` 保存原始输入，不要编辑、覆盖或删除。
- 更新源码时先备份需要保留的数据目录，并确认 Compose bind mounts 指向正确目录。
- 页面出现错误时记录 Battery ID、Experiment ID、当前步骤、request ID（如有）和错误状态；不要只截取无上下文的报错文字。
- 开发/部署说明见 [README](../README.md)，文件格式与 manifest 规则见 [data contracts](data_contract/manifests.md)。
