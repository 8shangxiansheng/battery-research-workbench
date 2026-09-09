"""BRW-026 AgentToolRegistry — validated catalog of semantic scientific tools."""

from __future__ import annotations

from typing import Any

from battery_workbench.agent_tools.models import (
    TOOL_CONTRACT_VERSION,
    ConfirmationPolicy,
    ToolCategory,
    ToolSpec,
)


class DuplicateToolError(ValueError):
    pass


class UnknownToolError(KeyError):
    pass


class AgentToolRegistry:
    """Owns the name → ToolSpec mapping; contract-versioned."""

    def __init__(self, contract_version: str = TOOL_CONTRACT_VERSION) -> None:
        self.contract_version = contract_version
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        if tool.name in self._tools:
            raise DuplicateToolError(tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise UnknownToolError(name)
        return self._tools[name]

    def tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def manifest(self) -> dict[str, Any]:
        return {
            "tool_contract_version": self.contract_version,
            "tool_count": len(self._tools),
            "tools": [t.model_dump(mode="json") for t in self.tools()],
        }


def _t(
    name: str,
    description: str,
    category: ToolCategory,
    *,
    read_only: bool,
    side_effect: bool,
    confirmation: ConfirmationPolicy,
    scope: str,
    idempotent: bool = False,
    returns_evidence: bool = False,
    prerequisites: list[str] | None = None,
    allowed_when: list[str] | None = None,
    blocked_when: list[str] | None = None,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    no_guess: list[str] | None = None,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        category=category,
        read_only=read_only,
        side_effect=side_effect,
        confirmation_required=confirmation,
        scientific_scope=scope,
        idempotent=idempotent,
        returns_evidence=returns_evidence,
        prerequisites=prerequisites or [],
        allowed_when=allowed_when or [],
        blocked_when=blocked_when or [],
        input_schema={"type": "object", "properties": properties or {}, "required": required or []},
        no_guess_parameters=no_guess or [],
    )


STR = {"type": "string"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}


def build_default_registry() -> AgentToolRegistry:
    r = AgentToolRegistry()

    # ---------- discovery / inspection ----------
    r.register(
        _t(
            "list_experiments",
            "列出实验库中的实验（分页、可按状态/Demo过滤）",
            ToolCategory.DISCOVERY,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="experiment library",
        )
    )
    r.register(
        _t(
            "inspect_experiment",
            "查看单个实验的高层摘要与最新产物",
            ToolCategory.DISCOVERY,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="experiment",
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "inspect_data_quality",
            "查看电气/超声数据质量聚合（API 计算）",
            ToolCategory.DISCOVERY,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="data quality",
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "inspect_synchronization",
            "查看同步状态（PROVISIONAL 时间基等）",
            ToolCategory.DISCOVERY,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="synchronization",
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "inspect_measurement_events",
            "分页预览测量事件",
            ToolCategory.DISCOVERY,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="measurement events",
            properties={"battery_id": STR, "experiment_id": STR, "limit": INT, "cursor": INT},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "inspect_run",
            "查看运行状态/节点/事件",
            ToolCategory.DISCOVERY,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="runs",
            properties={"run_id": STR},
            required=["run_id"],
        )
    )
    r.register(
        _t(
            "inspect_lineage",
            "查看产物血缘链",
            ToolCategory.DISCOVERY,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="lineage",
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "inspect_intake_capabilities",
            "查看 intake 支持的 adapter/角色/限制",
            ToolCategory.DISCOVERY,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="intake capabilities",
        )
    )

    # ---------- intake ----------
    r.register(
        _t(
            "create_experiment",
            "创建新实验（显式 battery/experiment id 或自动 ID）",
            ToolCategory.INTAKE,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_CONFIRMATION,
            scope="experiment lifecycle",
            idempotent=False,
            properties={"battery_id": STR, "experiment_id": STR, "name": STR, "notes": STR},
            required=["battery_id", "name"],
        )
    )
    r.register(
        _t(
            "load_demo",
            "将内置 Demo 实验注册进实验库（is_demo=true，幂等）",
            ToolCategory.INTAKE,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="experiment library",
            idempotent=True,
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "start_intake",
            "为实验启动 intake session",
            ToolCategory.INTAKE,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="intake session",
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "upload_experiment_asset",
            "上传资产到 intake session（经 API multipart，禁止本地路径）",
            ToolCategory.INTAKE,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="intake asset",
            properties={"session_id": STR, "file_ref": STR, "role": STR, "content": STR},
            required=["session_id", "file_ref", "role"],
        )
    )
    r.register(
        _t(
            "detect_asset_format",
            "运行 BRW-007 adapter 格式检测",
            ToolCategory.INTAKE,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="adapter detection",
            properties={"session_id": STR},
            required=["session_id"],
        )
    )
    r.register(
        _t(
            "validate_intake",
            "运行三维度导入验证（格式/元数据/就绪）",
            ToolCategory.INTAKE,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="intake validation",
            properties={"session_id": STR},
            required=["session_id"],
        )
    )
    r.register(
        _t(
            "commit_intake",
            "提交 intake：staging→canonical raw+manifest（需确认）",
            ToolCategory.INTAKE,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_CONFIRMATION,
            scope="intake commit",
            idempotent=True,
            properties={"session_id": STR},
            required=["session_id"],
        )
    )
    r.register(
        _t(
            "cancel_intake",
            "取消 intake session",
            ToolCategory.INTAKE,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="intake session",
            properties={"session_id": STR},
            required=["session_id"],
        )
    )

    # ---------- parameters ----------
    r.register(
        _t(
            "inspect_missing_parameters",
            "查看缺失的科学参数（fs/trigger/timezone 等）",
            ToolCategory.PARAMETERS,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="parameters",
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "set_experiment_parameter",
            "设置实验参数（必须由用户提供，禁止推断）",
            ToolCategory.PARAMETERS,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_INPUT_REQUIRED,
            scope="parameters",
            properties={
                "battery_id": STR,
                "experiment_id": STR,
                "parameter_name": STR,
                "value": STR,
                "unit": STR,
                "verified": {"type": "boolean"},
                "run_id": STR,
                "source": STR,
            },
            required=["battery_id", "experiment_id", "parameter_name", "value"],
            no_guess=[
                "ultrasound.sampling_rate_hz",
                "ultrasound.trigger_sample_index",
                "experiment.timezone",
                "experiment.ultrasound_path_length_m",
                "experiment.reference_capacity_ah",
            ],
        )
    )

    # ---------- waveforms / gates ----------
    r.register(
        _t(
            "list_waveform_frames",
            "列出波形帧元数据（不含波形体）",
            ToolCategory.WAVEFORM_GATES,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="waveform",
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "inspect_waveform_frame",
            "有界降采样预览一帧波形（不传全量 3999×1250）",
            ToolCategory.WAVEFORM_GATES,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="waveform",
            properties={
                "battery_id": STR,
                "experiment_id": STR,
                "frame_index": INT,
                "max_points": INT,
            },
            required=["battery_id", "experiment_id", "frame_index"],
        )
    )
    r.register(
        _t(
            "list_gates",
            "列出已提交闸门",
            ToolCategory.WAVEFORM_GATES,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="gates",
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "propose_gate",
            "提议闸门（draft，只读无副作用）",
            ToolCategory.WAVEFORM_GATES,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="gates proposal",
            properties={
                "battery_id": STR,
                "experiment_id": STR,
                "start_sample": INT,
                "end_sample": INT,
                "waveform_length": INT,
                "gate_name": STR,
            },
            required=["battery_id", "experiment_id", "start_sample", "end_sample"],
        )
    )
    r.register(
        _t(
            "create_gate",
            "提交闸门（side effect + 确认）",
            ToolCategory.WAVEFORM_GATES,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_CONFIRMATION,
            scope="gates",
            idempotent=True,
            properties={
                "battery_id": STR,
                "experiment_id": STR,
                "gate_name": STR,
                "start_sample": INT,
                "end_sample": INT,
                "waveform_length": INT,
            },
            required=["battery_id", "experiment_id", "gate_name", "start_sample", "end_sample"],
        )
    )

    # ---------- features / analysis ----------
    r.register(
        _t(
            "list_available_features",
            "列出特征清单（CORE/DERIVED/AUXILIARY，含 blocked 原因）",
            ToolCategory.FEATURES_ANALYSIS,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="features",
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "inspect_feature",
            "查看单个特征详情（availability/gate/missing reason）",
            ToolCategory.FEATURES_ANALYSIS,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="features",
            properties={"battery_id": STR, "experiment_id": STR, "feature_name": STR},
            required=["battery_id", "experiment_id", "feature_name"],
        )
    )
    r.register(
        _t(
            "analyze_feature_relationships",
            "运行 BRW-021 特征分析（EXPLORATORY 或 TRAIN_ONLY_ML_SAFE）",
            ToolCategory.FEATURES_ANALYSIS,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_CONFIRMATION,
            scope="feature analysis",
            returns_evidence=True,
            properties={
                "battery_id": STR,
                "experiment_id": STR,
                "analysis_mode": {
                    "type": "string",
                    "enum": ["EXPLORATORY_FULL_DATA", "TRAIN_ONLY_ML_SAFE"],
                },
                "target": STR,
                "candidate_features": {"type": "array", "items": STR},
            },
            required=[
                "battery_id",
                "experiment_id",
                "analysis_mode",
                "target",
                "candidate_features",
            ],
        )
    )
    r.register(
        _t(
            "propose_feature_selection",
            "提议特征选择（draft，只读）",
            ToolCategory.FEATURES_ANALYSIS,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="feature selection",
            properties={
                "battery_id": STR,
                "experiment_id": STR,
                "selected_features": {"type": "array", "items": STR},
            },
            required=["battery_id", "experiment_id", "selected_features"],
        )
    )
    r.register(
        _t(
            "confirm_feature_selection",
            "确认特征选择（UserAction 合同）",
            ToolCategory.FEATURES_ANALYSIS,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_CONFIRMATION,
            scope="feature selection",
            properties={
                "battery_id": STR,
                "experiment_id": STR,
                "selected_features": {"type": "array", "items": STR},
            },
            required=["battery_id", "experiment_id", "selected_features"],
        )
    )

    # ---------- dataset / evaluation ----------
    r.register(
        _t(
            "prepare_soc_dataset",
            "构建 SOC 数据集（保留 leakage/forbidden guard）",
            ToolCategory.DATASET_EVALUATION,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_CONFIRMATION,
            scope="dataset",
            idempotent=True,
            returns_evidence=True,
            properties={
                "battery_id": STR,
                "experiment_id": STR,
                "selected_features": {"type": "array", "items": STR},
            },
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "prepare_grouped_evaluation_split",
            "创建分组评估划分（LEAVE_ONE_GROUP_OUT；组不足→WAITING_FOR_USER）",
            ToolCategory.DATASET_EVALUATION,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_CONFIRMATION,
            scope="split",
            idempotent=True,
            properties={"battery_id": STR, "experiment_id": STR, "dataset_id": STR},
            required=["battery_id", "experiment_id", "dataset_id"],
        )
    )
    r.register(
        _t(
            "run_limited_soc_baselines",
            "运行固定基线协议（无 tuning）",
            ToolCategory.DATASET_EVALUATION,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_CONFIRMATION,
            scope="modeling",
            idempotent=True,
            returns_evidence=True,
            properties={
                "battery_id": STR,
                "experiment_id": STR,
                "dataset_id": STR,
                "split_id": STR,
            },
            required=["battery_id", "experiment_id", "dataset_id", "split_id"],
        )
    )
    r.register(
        _t(
            "inspect_model_comparison",
            "查看模型对比（含 Dummy 基线）",
            ToolCategory.DATASET_EVALUATION,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="modeling",
            returns_evidence=True,
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )

    # ---------- run execution ----------
    r.register(
        _t(
            "start_run",
            "启动 orchestrator run（仅限固定 profile；确认后执行）",
            ToolCategory.DISCOVERY,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_CONFIRMATION,
            scope="runs",
            properties={
                "profile": {
                    "type": "string",
                    "enum": ["INGEST_TO_MEASUREMENT_EVENTS", "SCIENTIFIC_ANALYSIS"],
                },
                "battery_id": STR,
                "experiment_id": STR,
                "stages": {"type": "array", "items": STR},
                "parameters": {"type": "object"},
                "split": {"type": "object"},
                "dry_run": BOOL,
            },
            required=["profile", "battery_id", "experiment_id"],
        )
    )

    # ---------- human interaction (resume loop) ----------
    r.register(
        _t(
            "list_pending_user_actions",
            "列出 run 的待处理科学动作（WAITING_FOR_USER）",
            ToolCategory.DISCOVERY,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="runs",
            properties={"run_id": STR},
            required=["run_id"],
        )
    )
    r.register(
        _t(
            "submit_user_action",
            "提交用户对科学动作的显式回答（必须来自用户，禁止 Agent 猜值）",
            ToolCategory.DISCOVERY,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_CONFIRMATION,
            scope="runs",
            properties={"run_id": STR, "action_id": STR, "values": {"type": "object"}},
            required=["run_id", "action_id", "values"],
            no_guess=[
                "ultrasound.sampling_rate_hz",
                "ultrasound.trigger_sample_index",
                "experiment.timezone",
                "experiment.ultrasound_path_length_m",
            ],
        )
    )
    r.register(
        _t(
            "resume_run",
            "恢复原 run（保留 lineage，追加 RUN_RESUMED 事件）",
            ToolCategory.DISCOVERY,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="runs",
            properties={"run_id": STR},
            required=["run_id"],
        )
    )

    # ---------- reporting / provenance ----------
    r.register(
        _t(
            "generate_scientific_report",
            "生成科学报告（聚合既有产物，幂等 REUSED）",
            ToolCategory.REPORTING,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_CONFIRMATION,
            scope="reporting",
            idempotent=True,
            returns_evidence=True,
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "inspect_scientific_report",
            "查看报告内容",
            ToolCategory.REPORTING,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="reporting",
            properties={"report_id": STR},
            required=["report_id"],
        )
    )
    r.register(
        _t(
            "explain_result_evidence",
            "解释科学数值的证据链（ClaimGuard 保护）",
            ToolCategory.REPORTING,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="evidence",
            returns_evidence=True,
            properties={"battery_id": STR, "experiment_id": STR, "result_id": STR, "claim": STR},
            required=["battery_id", "experiment_id", "result_id"],
        )
    )
    r.register(
        _t(
            "inspect_evidence",
            "查看证据注册表",
            ToolCategory.REPORTING,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="evidence",
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )

    # ---------- BRW-027R high-level semantic adapters (thin; orchestrate only) ----------
    r.register(
        _t(
            "inspect_research_state",
            "聚合当前研究会话上下文：目标/对齐/闸门/特征/数据集/划分/模型/报告（page-aware）",
            ToolCategory.DISCOVERY,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="research session state",
            idempotent=True,
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "select_target",
            "选择研究目标（Reference SOC/Temperature/SOH/Voltage/Current），带 readiness 检查",
            ToolCategory.FEATURES_ANALYSIS,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="target selection",
            idempotent=True,
            properties={"battery_id": STR, "experiment_id": STR, "target_id": STR},
            required=["battery_id", "experiment_id", "target_id"],
        )
    )
    r.register(
        _t(
            "inspect_alignment",
            "查看 canonical 同步对齐（matched unique/ambiguous/unmatched/eligible + provisional 语义）",
            ToolCategory.DISCOVERY,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="synchronization alignment",
            idempotent=True,
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "inspect_gate_readiness",
            "查看闸门标定就绪状态（gate templates/confirmed/frozen）",
            ToolCategory.WAVEFORM_GATES,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="gate calibration",
            idempotent=True,
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "inspect_canonical_tof",
            "BRW-017R2 规范 TOF 审计（包络峰值 surface→bottom；fs 来自参数注册表；XCorr 不参与）",
            ToolCategory.WAVEFORM_GATES,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="canonical tof audit",
            idempotent=True,
            properties={"battery_id": STR, "experiment_id": STR, "limit": {"type": "integer"}},
            required=["battery_id", "experiment_id"],
        )
    )
    r.register(
        _t(
            "analyze_target_relationships",
            "特征-目标关系与排序（SOC/Temperature/SOH/Voltage/Current 分支；exploratory 或 TRAIN-only）",
            ToolCategory.FEATURES_ANALYSIS,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="feature-target relationship",
            idempotent=True,
            properties={"battery_id": STR, "experiment_id": STR, "target_id": STR,
                        "features": {"type": "array", "items": {"type": "string"}},
                        "mode": STR},
            required=["battery_id", "experiment_id", "target_id", "features"],
        )
    )
    r.register(
        _t(
            "prepare_ml_safe_dataset",
            "构建 ML-safe 数据集（需 TRAIN-only selection 已确认）",
            ToolCategory.DATASET_EVALUATION,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_CONFIRMATION,
            scope="dataset",
            idempotent=True,
            properties={"battery_id": STR, "experiment_id": STR, "target_id": STR},
            required=["battery_id", "experiment_id", "target_id"],
        )
    )
    r.register(
        _t(
            "run_baseline_suite",
            "运行固定 baseline 套件（Dummy-first，无超参搜索）",
            ToolCategory.DATASET_EVALUATION,
            read_only=False,
            side_effect=True,
            confirmation=ConfirmationPolicy.USER_CONFIRMATION,
            scope="baseline modeling",
            properties={"battery_id": STR, "experiment_id": STR, "dataset_id": STR, "split_id": STR},
            required=["battery_id", "experiment_id", "dataset_id", "split_id"],
        )
    )
    r.register(
        _t(
            "get_model_comparison",
            "获取模型对比（Dummy-first 解释）",
            ToolCategory.DATASET_EVALUATION,
            read_only=True,
            side_effect=False,
            confirmation=ConfirmationPolicy.NO_CONFIRMATION,
            scope="model comparison",
            idempotent=True,
            properties={"battery_id": STR, "experiment_id": STR},
            required=["battery_id", "experiment_id"],
        )
    )
    return r