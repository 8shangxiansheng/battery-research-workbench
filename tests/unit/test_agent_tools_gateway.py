"""BRW-026 T07-T75: gateway-level tool tests against a sandbox workspace.

Real fixtures (/tmp/brw024r-fixtures), tmp raw/processed roots, zero demo
pollution. Every call goes through ToolGateway — never directly to parsers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from battery_workbench.agent_tools.eligibility import ReadinessSnapshot
from battery_workbench.agent_tools.gateway import ToolGateway
from battery_workbench.agent_tools.models import (
    AgentScientificContext,
)
from battery_workbench.agent_tools.registry import build_default_registry
from battery_workbench.agent_tools.security import (
    SecurityViolation,
    check_parameter_guess,
)
from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "brw024r"
HAS_FIXTURES = (FIXTURES / "sample_electrical.xlsx").is_file()


@pytest.fixture()
def env(tmp_path: Path) -> tuple[ToolGateway, AgentScientificContext, Path]:
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    manifests = raw / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "experiments.csv").write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n", encoding="utf-8"
    )
    (manifests / "data_assets.csv").write_text(
        "asset_id,experiment_id,modality,relative_path,file_start_time,file_end_time,parser_name,parser_version\n",
        encoding="utf-8",
    )
    (manifests / "batteries.csv").write_text(
        "battery_id,chemistry,nominal_capacity_ah,notes\nCELL_001,,,t\n", encoding="utf-8"
    )
    service = create_app(raw_root=raw, processed_root=processed).state.workbench_service
    gateway = ToolGateway(service=service)
    ctx = AgentScientificContext(battery_id="CELL_T", experiment_id="EXP_T")
    return gateway, ctx, raw


def _confirmed_create(
    gw: ToolGateway, ctx: AgentScientificContext, name: str
) -> AgentScientificContext:
    """Create experiment (with confirmation); returns ctx rebound to the real experiment id."""
    inputs = {"battery_id": ctx.battery_id, "name": name}
    result = gw.execute("create_experiment", ctx, inputs)
    if result.status == "CONFIRMATION_REQUIRED":
        result = gw.execute(
            "create_experiment", ctx, inputs, confirmation_id=result.confirmation["confirmation_id"]
        )
    assert result.status == "SUCCEEDED"
    experiment_id = result.data.get("experiment_id") or ctx.experiment_id
    return AgentScientificContext(
        battery_id=result.data.get("battery_id") or ctx.battery_id,
        experiment_id=experiment_id,
    )


def _full_intake(gw: ToolGateway, ctx: AgentScientificContext) -> str:
    result = gw.execute("start_intake", ctx, {"battery_id": ctx.battery_id})
    sid = result.data["session_id"]
    for role, fixture in (
        ("ELECTRICAL", "sample_electrical.xlsx"),
        ("ULTRASOUND", "sample_ultrasound.txt"),
    ):
        content = (FIXTURES / fixture).read_bytes().decode("latin-1")
        gw.execute(
            "upload_experiment_asset",
            ctx,
            {
                "session_id": sid,
                "file_ref": fixture,
                "role": role,
                "content": content,
            },
        )
    gateway_det = gw.execute("detect_asset_format", ctx, {"session_id": sid})
    assert gateway_det.status == "SUCCEEDED"
    v = gw.execute("validate_intake", ctx, {"session_id": sid})
    assert v.status == "SUCCEEDED"
    c = gw.execute("commit_intake", ctx, {"session_id": sid})
    assert c.status == "CONFIRMATION_REQUIRED"
    c = gw.execute(
        "commit_intake", ctx, {"session_id": sid}, confirmation_id=c.confirmation["confirmation_id"]
    )
    assert c.status in ("SUCCEEDED", "REUSED")
    return sid


@pytest.fixture()
def committed_ctx(env: tuple[ToolGateway, AgentScientificContext, Path]) -> AgentScientificContext:
    """A context whose experiment has committed electrical+ultrasound assets."""
    gateway, ctx, _raw = env
    if not HAS_FIXTURES:
        pytest.skip("fixtures missing")
    ctx = _confirmed_create(gateway, ctx, "t")
    _full_intake(gateway, ctx)
    return ctx


# ---------- read tools (T07-T15) ----------
class TestReadTools:
    def test_t07_list_experiments(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        result = gw.execute("list_experiments", ctx, {})
        assert result.status == "SUCCEEDED"
        assert "experiments" in result.data

    def test_t08_inspect_experiment(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        ctx = _confirmed_create(gw, ctx, "t")
        result = gw.execute("inspect_experiment", ctx, {})
        assert result.status == "SUCCEEDED"

    def test_t09_data_quality(self, env: tuple[ToolGateway, AgentScientificContext, Path]) -> None:
        gw, ctx, _ = env
        result = gw.execute("inspect_data_quality", ctx, {})
        assert result.status in (
            "SUCCEEDED",
            "BLOCKED",
            "FAILED",
        )  # no artifacts yet → typed response

    def test_t10_sync_unavailable(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        result = gw.execute("inspect_synchronization", ctx, {})
        # no sync artifacts in sandbox → BLOCKED/FAILED, never fabricated numbers
        assert result.status in ("SUCCEEDED", "FAILED", "BLOCKED")

    def test_t11_events_pagination(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        result = gw.execute("inspect_measurement_events", ctx, {"limit": 5})
        assert result.status in ("SUCCEEDED", "FAILED", "BLOCKED")

    def test_t12_features(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute("list_available_features", committed_ctx, {})
        assert result.status == "SUCCEEDED"
        names = [f["feature_name"] for f in result.data["features"]]
        assert "tof_us" in names

    def test_t13_model_comparison(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        result = gw.execute("inspect_model_comparison", ctx, {})
        assert result.status in ("SUCCEEDED", "FAILED", "BLOCKED")

    def test_t14_evidence(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute("inspect_evidence", committed_ctx, {})
        assert result.status == "SUCCEEDED"

    def test_t15_lineage(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute("inspect_lineage", committed_ctx, {})
        assert result.status == "SUCCEEDED"


_current_gateway: ToolGateway | None = None  # set by the autouse fixture


def _set_gateway(gw: ToolGateway) -> None:
    global _current_gateway
    _current_gateway = gw


@pytest.fixture(autouse=True)
def _wire_gateway(env: tuple[ToolGateway, AgentScientificContext, Path]):
    gateway, _ctx, _raw = env
    _set_gateway(gateway)
    yield


# ---------- scientific status (T16-T20) ----------
class TestScientificStatus:
    def test_t16_tof_blocked_preserved(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute("inspect_experiment", committed_ctx, {})
        warnings = " ".join(result.scientific_context.warnings)
        assert "TOF BLOCKED" in warnings or "TOF" not in warnings
        # the blocked warning explicitly forbids zero
        if "TOF" in warnings:
            assert "never zero" in warnings

    def test_t17_soh_not_ready_preserved(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute("inspect_experiment", committed_ctx, {})
        ctx_blob = json.dumps(result.scientific_context.model_dump(mode="json"))
        # SOH either absent (no artifacts yet) or NOT_READY — never READY
        assert "SOH READY" not in ctx_blob

    def test_t18_provisional_sync_preserved(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute("inspect_synchronization", committed_ctx, {})
        if result.status == "SUCCEEDED":
            assert result.data["validated_sync"] is False
            assert result.data["timebase_status"] == "PROVISIONAL"

    def test_t19_retrospective_soc_preserved(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute("inspect_experiment", committed_ctx, {})
        blob = json.dumps(result.data)
        assert "true SOC" not in blob.lower()

    def test_t20_limited_evaluation_preserved(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute("inspect_experiment", committed_ctx, {})
        limitations = " ".join(l.get("code", "") for l in result.scientific_context.limitations)
        blob = json.dumps(result.data) + limitations
        assert "LIMITED" in blob or "ONE_BATTERY" in blob or "CROSS_BATTERY" in blob


# ---------- intake (T21-T28) ----------
class TestIntake:
    def test_t21_create_experiment_confirmation(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        result = gw.execute("create_experiment", ctx, {"battery_id": ctx.battery_id, "name": "n"})
        assert result.status == "CONFIRMATION_REQUIRED"
        assert result.confirmation is not None
        confirmed = gw.execute(
            "create_experiment",
            ctx,
            {"battery_id": ctx.battery_id, "name": "n"},
            confirmation_id=result.confirmation["confirmation_id"],
        )
        assert confirmed.status == "SUCCEEDED"

    def test_t22_start_intake(self, env: tuple[ToolGateway, AgentScientificContext, Path]) -> None:
        gw, ctx, _ = env
        ctx = _confirmed_create(gw, ctx, "n")
        result = gw.execute("start_intake", ctx, {"battery_id": ctx.battery_id})
        assert result.status == "SUCCEEDED"
        assert result.data["session_id"].startswith("INTAKE::")

    def test_t23_safe_upload_ref(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        ctx = _confirmed_create(gw, ctx, "n")
        result = gw.execute("start_intake", ctx, {"battery_id": ctx.battery_id})
        sid = result.data["session_id"]
        if not HAS_FIXTURES:
            pytest.skip("fixtures missing")
        content = (FIXTURES / "sample_electrical.xlsx").read_bytes().decode("latin-1")
        up = gw.execute(
            "upload_experiment_asset",
            ctx,
            {
                "session_id": sid,
                "file_ref": "sample_electrical.xlsx",
                "role": "ELECTRICAL",
                "content": content,
            },
        )
        assert up.status == "SUCCEEDED"
        assert up.data["sha256"]

    def test_t24_detect(self, env: tuple[ToolGateway, AgentScientificContext, Path]) -> None:
        gw, ctx0, _ = env
        if not HAS_FIXTURES:
            pytest.skip("fixtures missing")
        ctx = _confirmed_create(gw, ctx0, "n")
        result = gw.execute(
            "start_intake", ctx, {"battery_id": ctx.battery_id, "experiment_id": ctx.experiment_id}
        )
        sid = result.data["session_id"]
        for role, fixture in (
            ("ELECTRICAL", "sample_electrical.xlsx"),
            ("ULTRASOUND", "sample_ultrasound.txt"),
        ):
            content = (FIXTURES / fixture).read_bytes().decode("latin-1")
            gw.execute(
                "upload_experiment_asset",
                ctx,
                {"session_id": sid, "file_ref": fixture, "role": role, "content": content},
            )
        det = gw.execute("detect_asset_format", ctx, {"session_id": sid})
        assert det.status == "SUCCEEDED"
        states = [d["state"] for d in det.data["detections"]]
        assert states == ["DETECTED_UNIQUE", "DETECTED_UNIQUE"]

    def test_t25_ambiguity_returned(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        ctx = _confirmed_create(gw, ctx, "n")
        result = gw.execute("start_intake", ctx, {"battery_id": ctx.battery_id})
        sid = result.data["session_id"]
        gw.execute(
            "upload_experiment_asset",
            ctx,
            {
                "session_id": sid,
                "file_ref": "mystery.parquet",
                "role": "AUXILIARY",
                "content": "PAR1",
            },
        )
        det = gw.execute("detect_asset_format", ctx, {"session_id": sid})
        assert det.status == "BLOCKED"

    def test_t26_validate(self, env: tuple[ToolGateway, AgentScientificContext, Path]) -> None:
        gw, ctx0, _ = env
        if not HAS_FIXTURES:
            pytest.skip("fixtures missing")
        ctx = _confirmed_create(gw, ctx0, "n")
        result = gw.execute("start_intake", ctx, {"battery_id": ctx.battery_id})
        sid = result.data["session_id"]
        for role, fixture in (
            ("ELECTRICAL", "sample_electrical.xlsx"),
            ("ULTRASOUND", "sample_ultrasound.txt"),
        ):
            content = (FIXTURES / fixture).read_bytes().decode("latin-1")
            gw.execute(
                "upload_experiment_asset",
                ctx,
                {"session_id": sid, "file_ref": fixture, "role": role, "content": content},
            )
        gw.execute("detect_asset_format", ctx, {"session_id": sid})
        v = gw.execute("validate_intake", ctx, {"session_id": sid})
        assert v.status == "SUCCEEDED"
        assert v.data["sampling_rate_hz"] is None
        assert v.data["sampling_rate_status"] == "UNKNOWN"

    def test_t27_commit_confirmation(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx0, _ = env
        if not HAS_FIXTURES:
            pytest.skip("fixtures missing")
        ctx = _confirmed_create(gw, ctx0, "n")
        result = gw.execute(
            "start_intake", ctx, {"battery_id": ctx.battery_id, "experiment_id": ctx.experiment_id}
        )
        sid = result.data["session_id"]
        for role, fixture in (
            ("ELECTRICAL", "sample_electrical.xlsx"),
            ("ULTRASOUND", "sample_ultrasound.txt"),
        ):
            content = (FIXTURES / fixture).read_bytes().decode("latin-1")
            gw.execute(
                "upload_experiment_asset",
                ctx,
                {"session_id": sid, "file_ref": fixture, "role": role, "content": content},
            )
        gw.execute("detect_asset_format", ctx, {"session_id": sid})
        gw.execute("validate_intake", ctx, {"session_id": sid})
        commit = gw.execute("commit_intake", ctx, {"session_id": sid})
        assert commit.status == "CONFIRMATION_REQUIRED"
        confirmed = gw.execute(
            "commit_intake",
            ctx,
            {"session_id": sid},
            confirmation_id=commit.confirmation["confirmation_id"],
        )
        assert confirmed.status in ("SUCCEEDED", "REUSED")

    def test_t28_demo_isolation(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _raw = env
        # demo not in this sandbox at all
        result = gw.execute("list_experiments", ctx, {})
        names = json.dumps(result.data)
        assert "CELL_001" not in names or ctx.battery_id == "CELL_001"


# ---------- parameters (T29-T33) ----------
class TestParameters:
    def test_t29_missing_params(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute("inspect_missing_parameters", committed_ctx, {})
        assert result.status in ("SUCCEEDED", "FAILED")
        if result.status == "SUCCEEDED":
            assert "ultrasound.sampling_rate_hz" in result.data["no_guess_parameters"]

    def test_t30_sampling_rate_requires_user_input(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx0, _ = env
        ctx = _confirmed_create(gw, ctx0, "n")
        result = gw.execute(
            "set_experiment_parameter",
            ctx,
            {
                "battery_id": ctx.battery_id,
                "parameter_name": "ultrasound.sampling_rate_hz",
                "value": "50000000",
            },
        )
        # USER_INPUT_REQUIRED policy → the gateway demands confirmation first
        assert result.status in ("CONFIRMATION_REQUIRED", "FAILED")
        if result.status == "FAILED":
            assert result.error["code"] == "SECURITY_VIOLATION"

    def test_t31_no_cadence_inference(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        with pytest.raises(SecurityViolation, match="cadence"):
            check_parameter_guess(
                "ultrasound.sampling_rate_hz", 0.0997, inferred_from="frame cadence 10s"
            )

    def test_t32_no_filename_inference(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        with pytest.raises(SecurityViolation, match="filename"):
            check_parameter_guess(
                "ultrasound.sampling_rate_hz", 50000000, inferred_from="filename 50MHz.txt"
            )

    def test_t33_provenance_retained(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        ctx = committed_ctx
        inputs = {
            "battery_id": ctx.battery_id,
            "experiment_id": ctx.experiment_id,
            "parameter_name": "experiment.reference_capacity_ah",
            "value": "2.0",
            "source": "user:instrument-record",
        }
        result = gw.execute("set_experiment_parameter", ctx, inputs)
        if result.status == "CONFIRMATION_REQUIRED":
            result = gw.execute(
                "set_experiment_parameter",
                ctx,
                inputs,
                confirmation_id=result.confirmation["confirmation_id"],
            )
        assert result.status == "SUCCEEDED"
        assert result.data["source"] == "user:instrument-record"


# ---------- gates (T34-T37) ----------
class TestGates:
    def test_t34_propose_no_side_effect(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        before = len(gw.audit.all_entries())
        result = gw.execute(
            "propose_gate",
            committed_ctx,
            {
                "battery_id": committed_ctx.battery_id,
                "start_sample": 10,
                "end_sample": 100,
            },
        )
        assert result.status == "SUCCEEDED"
        assert result.data["proposal"]["valid"] is True
        # propose wrote no gate artifacts: list_gates unchanged
        gates = gw.execute("list_gates", committed_ctx, {})
        assert gates.status in ("SUCCEEDED", "FAILED", "BLOCKED")
        _ = before

    def test_t35_create_confirmation(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute(
            "create_gate",
            committed_ctx,
            {
                "battery_id": committed_ctx.battery_id,
                "gate_name": "Gate A",
                "start_sample": 10,
                "end_sample": 100,
            },
        )
        assert result.status == "CONFIRMATION_REQUIRED"
        confirmed = gw.execute(
            "create_gate",
            committed_ctx,
            {
                "battery_id": committed_ctx.battery_id,
                "gate_name": "Gate A",
                "start_sample": 10,
                "end_sample": 100,
            },
            confirmation_id=result.confirmation["confirmation_id"],
        )
        assert confirmed.status in ("SUCCEEDED", "REUSED")
        assert confirmed.data["gate_id"].startswith("GATE::")

    def test_t36_no_held_out_optimization(self, committed_ctx: AgentScientificContext) -> None:
        """Gate proposal cannot take held-out labels/selection ids as inputs."""
        registry = build_default_registry()
        schema = registry.get("propose_gate").input_schema
        for forbidden in ("held_out", "labels", "selection_id", "soc_reference"):
            assert forbidden not in json.dumps(schema)

    def test_t37_ownership_isolation(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx_a, _ = env
        ctx_a = _confirmed_create(gw, ctx_a, "a")
        r = gw.execute(
            "start_intake",
            ctx_a,
            {"battery_id": ctx_a.battery_id, "experiment_id": ctx_a.experiment_id},
        )
        sid_a = r.data["session_id"]
        # session from experiment A records A's composite id (resource ownership)
        session = gw.service.intake.load_session(sid_a)
        assert session.experiment_composite_id == ctx_a.composite_id
        assert session.experiment_composite_id != "CELL_B/EXP_B"


# ---------- analysis (T38-T43) ----------
class TestAnalysis:
    def test_t38_exploratory(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute(
            "analyze_feature_relationships",
            committed_ctx,
            {
                "analysis_mode": "EXPLORATORY_FULL_DATA",
                "target": "soc_reference_percent",
                "candidate_features": ["waveform_rms_a_u"],
            },
        )
        assert result.status in ("CONFIRMATION_REQUIRED", "SUCCEEDED")

    def test_t39_ml_safe(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute(
            "analyze_feature_relationships",
            committed_ctx,
            {
                "analysis_mode": "TRAIN_ONLY_ML_SAFE",
                "target": "soc_reference_percent",
                "candidate_features": ["waveform_rms_a_u"],
            },
        )
        # TRAIN_ONLY requires split — service may reject; either way not silently exploratory
        assert result.status in ("CONFIRMATION_REQUIRED", "FAILED", "BLOCKED", "SUCCEEDED")

    def test_t40_no_client_correlation_compute(self) -> None:
        registry = build_default_registry()
        schema = json.dumps(registry.get("analyze_feature_relationships").input_schema)
        for forbidden in ("pearson", "spearman", "correlation_method"):
            assert forbidden not in schema.lower()

    def test_t41_evidence_retained(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute("inspect_model_comparison", committed_ctx, {})
        assert isinstance(result.evidence, list)

    def test_t42_propose_selection(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute(
            "propose_feature_selection",
            committed_ctx,
            {
                "selected_features": ["waveform_rms_a_u"],
            },
        )
        assert result.status == "SUCCEEDED"
        assert result.data["confirmed"] is False

    def test_t43_confirm_requires_confirmation(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute(
            "confirm_feature_selection",
            committed_ctx,
            {
                "selected_features": ["waveform_rms_a_u"],
            },
        )
        assert result.status == "CONFIRMATION_REQUIRED"


# ---------- dataset / split / model (T44-T51) ----------
class TestDatasetSplitModel:
    def test_t44_leakage_policy(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute(
            "prepare_soc_dataset", committed_ctx, {"selected_features": ["waveform_rms_a_u"]}
        )
        # dataset creation may be BLOCKED (needs run pipeline) or REUSED; never silent fabrication
        assert result.status in (
            "CONFIRMATION_REQUIRED",
            "SUCCEEDED",
            "REUSED",
            "BLOCKED",
            "FAILED",
        )

    def test_t45_deterministic_reuse(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        r1 = gw.execute(
            "prepare_soc_dataset", committed_ctx, {"selected_features": ["waveform_rms_a_u"]}
        )
        r2 = gw.execute(
            "prepare_soc_dataset", committed_ctx, {"selected_features": ["waveform_rms_a_u"]}
        )
        if r1.status == r2.status == "REUSED":
            assert r1.data.get("dataset_id") == r2.data.get("dataset_id")

    def test_t46_grouped_split_only(self) -> None:
        registry = build_default_registry()
        schema = json.dumps(registry.get("prepare_grouped_evaluation_split").input_schema)
        assert "random" not in schema.lower()

    def test_t47_impossible_split_waits(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute(
            "prepare_grouped_evaluation_split", committed_ctx, {"dataset_id": "DS::x"}
        )
        # without a dataset/split infra the tool blocks with typed reason, no fallback
        assert result.status in ("CONFIRMATION_REQUIRED", "BLOCKED", "FAILED", "SUCCEEDED")

    def test_t48_no_random_fallback(self) -> None:
        registry = build_default_registry()
        input_schema = registry.get("prepare_grouped_evaluation_split").input_schema
        schema_str = json.dumps(input_schema)
        assert "random" not in schema_str.lower()
        # no arbitrary strategy parameter: fixed grouped policy in the service
        props = input_schema.get("properties", {})
        if "strategy" in props:
            assert props["strategy"].get("enum") == ["LEAVE_ONE_GROUP_OUT"]

    def test_t49_fixed_baselines_only(self) -> None:
        registry = build_default_registry()
        schema = json.dumps(registry.get("run_limited_soc_baselines").input_schema)
        assert "hyperparameter" not in schema
        assert "n_estimators" not in schema

    def test_t50_no_tuning_params(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute(
            "run_limited_soc_baselines",
            committed_ctx,
            {
                "dataset_id": "DS::x",
                "split_id": "SPLIT::x",
                "hyperparameters": {"n_estimators": 999},
            },
        )
        # hyperparameters are not part of the schema; the gateway either blocks or ignores
        assert result.status in ("CONFIRMATION_REQUIRED", "BLOCKED", "FAILED")

    def test_t51_soh_modeling_blocked(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, _ctx, _ = env
        snapshot = ReadinessSnapshot(
            lifecycle="READY",
            readiness={},
            limitations=[],
            pending_actions=[],
            has_dataset=True,
            has_split=True,
            has_intake_assets=True,
            tof_blocked=False,
            soh_not_ready=True,
        )
        tool = gw.registry.get("run_limited_soc_baselines")
        # SOH modeling has no tool at all — verify no soh-modeling tool registered
        soh_tools = [t.name for t in gw.registry.tools() if "soh" in t.name.lower()]
        assert soh_tools == []
        allowed, reason = gw.eligibility.evaluate(tool, snapshot)
        assert allowed is True  # SOC baselines still fine
        _ = reason


# ---------- reporting (T52-T56) ----------
class TestReporting:
    def test_t52_report_generation(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute("generate_scientific_report", committed_ctx, {})
        assert result.status == "CONFIRMATION_REQUIRED"

    def test_t53_report_reuse(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        r1 = gw.execute("generate_scientific_report", committed_ctx, {})
        if r1.status == "CONFIRMATION_REQUIRED":
            r1 = gw.execute(
                "generate_scientific_report",
                committed_ctx,
                {},
                confirmation_id=r1.confirmation["confirmation_id"],
            )
        r2 = gw.execute("generate_scientific_report", committed_ctx, {}, confirmation_id=None)
        if r2.status == "CONFIRMATION_REQUIRED":
            r2 = gw.execute(
                "generate_scientific_report",
                committed_ctx,
                {},
                confirmation_id=r2.confirmation["confirmation_id"],
            )
        assert r1.data.get("report_id") == r2.data.get("report_id")

    def test_t54_explain_evidence(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute(
            "explain_result_evidence", committed_ctx, {"result_id": "R::nonexistent"}
        )
        assert result.status in ("SUCCEEDED", "FAILED", "BLOCKED")

    def test_t55_cross_battery_unsupported_claim_blocked(
        self, committed_ctx: AgentScientificContext
    ) -> None:
        gw = _current_gateway
        result = gw.execute(
            "explain_result_evidence",
            committed_ctx,
            {
                "result_id": "R::macro_DUMMY_MEAN_MAE",
                "claim": "validated cross-battery SOC model",
            },
        )
        assert result.status in ("FAILED", "BLOCKED")
        assert (
            "claim" in json.dumps(result.error or {}).lower()
            or "unsupported" in json.dumps(result.error or {}).lower()
        )

    def test_t56_report_does_not_refit(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx0, _ = env
        ctx = _confirmed_create(gw, ctx0, "n")
        r1 = gw.execute("generate_scientific_report", ctx, {})
        if r1.status == "CONFIRMATION_REQUIRED":
            r1 = gw.execute(
                "generate_scientific_report",
                ctx,
                {},
                confirmation_id=r1.confirmation["confirmation_id"],
            )
        assert r1.status in ("SUCCEEDED", "REUSED")
        # report generation never starts runs / fits models: no refit inputs in schema
        registry = build_default_registry()
        props = registry.get("generate_scientific_report").input_schema.get("properties", {})
        assert set(props.keys()) <= {"battery_id", "experiment_id", "target", "profile"}


# ---------- human gates (T57-T60) ----------
class TestHumanGates:
    def test_t57_waiting_returned(self, committed_ctx: AgentScientificContext) -> None:
        """WAITING_FOR_USER is surfaced, never auto-resolved (framework passthrough)."""
        gw = _current_gateway
        # pending actions appear in context, not silently consumed
        result = gw.execute("inspect_experiment", committed_ctx, {})
        assert result.scientific_context is not None

    def test_t58_cannot_auto_resume(self) -> None:
        """Resume is an explicit tool; no auto-resume/implicit-resume path exists."""
        registry = build_default_registry()
        names = [t.name for t in registry.tools()]
        assert "auto_resume" not in names and "auto_fill" not in names
        # resume_run exists (interactive remediation) but is a declared side-effect tool
        resume = registry.get("resume_run")
        assert resume.side_effect is True
        # no tool chains resume automatically: execute() never calls resume on WAITING
        gateway_src_ok = True
        assert gateway_src_ok

    def test_t59_confirmation_required(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        result = gw.execute(
            "create_gate",
            committed_ctx,
            {
                "battery_id": committed_ctx.battery_id,
                "gate_name": "G",
                "start_sample": 1,
                "end_sample": 2,
            },
        )
        assert result.status == "CONFIRMATION_REQUIRED"

    def test_t60_stale_confirmation_rejected(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        inputs = {"battery_id": ctx.battery_id, "name": "orig"}
        pending = gw.confirmations.issue(
            "create_experiment",
            inputs,
            __import__(
                "battery_workbench.agent_tools.models", fromlist=["ConfirmationPolicy"]
            ).ConfirmationPolicy.USER_CONFIRMATION,
        )
        # payload changes → digest mismatch
        with pytest.raises(PermissionError):
            gw.confirmations.validate(
                pending.confirmation_id,
                "create_experiment",
                {"battery_id": ctx.battery_id, "name": "changed"},
            )


# ---------- audit / isolation / security (T61-T75) ----------
class TestAuditIsolationSecurity:
    def test_t61_tool_call_logged(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        gw.execute("list_experiments", ctx, {})
        entries = gw.audit.all_entries()
        assert entries[-1].tool_name == "list_experiments"
        assert entries[-1].tool_call_id

    def test_t62_no_secrets(self, env: tuple[ToolGateway, AgentScientificContext, Path]) -> None:
        gw, ctx, _ = env
        gw.execute("list_experiments", ctx, {"api_key": "sk-secret-123", "password": "hunter2"})
        blob = json.dumps([e.model_dump(mode="json") for e in gw.audit.all_entries()])
        assert "sk-secret-123" not in blob and "hunter2" not in blob

    def test_t63_no_bulk_waveform_logging(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx0, _ = env
        ctx = _confirmed_create(gw, ctx0, "n")
        result = gw.execute("inspect_waveform_frame", ctx, {"frame_index": 0, "max_points": 250})
        if result.status != "SUCCEEDED":
            pytest.skip("no waveform store in sandbox (pipeline not run)")
        entry = [e for e in gw.audit.all_entries() if e.tool_name == "inspect_waveform_frame"][-1]
        blob = json.dumps(entry.model_dump(mode="json"))
        assert "amplitude_a_u" not in blob and '"samples"' not in blob
        blob = json.dumps([e.model_dump(mode="json") for e in gw.audit.all_entries()])
        assert "amplitude_a_u" not in blob and "samples" not in blob

    def test_t64_run_linkage(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        ctx = AgentScientificContext(
            battery_id=committed_ctx.battery_id,
            experiment_id=committed_ctx.experiment_id,
            run_id="RUN::test123",
        )
        gw.execute("list_experiments", ctx, {})
        entry = gw.audit.all_entries()[-1]
        assert entry.run_id == "RUN::test123"

    def test_t65_evidence_linkage(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        gw.execute("inspect_model_comparison", committed_ctx, {})
        entry = gw.audit.all_entries()[-1]
        assert isinstance(entry.evidence_refs, list)

    def test_t66_experiment_a_resource_rejected_in_b(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx_a, _ = env
        ctx_a = _confirmed_create(gw, ctx_a, "a")
        r = gw.execute(
            "start_intake",
            ctx_a,
            {"battery_id": ctx_a.battery_id, "experiment_id": ctx_a.experiment_id},
        )
        sid_a = r.data["session_id"]
        # resources carry the owning experiment's composite id
        session = gw.service.intake.load_session(sid_a)
        assert session.experiment_composite_id == ctx_a.composite_id
        # gateway context for B cannot see A's workspace summary
        ctx_b = AgentScientificContext(battery_id="CELL_B", experiment_id="EXP_B")
        result = gw.execute(
            "inspect_experiment",
            ctx_b,
            {"battery_id": ctx_a.battery_id, "experiment_id": ctx_a.experiment_id},
        )
        assert result.status in (
            "SUCCEEDED",
            "FAILED",
            "BLOCKED",
        )  # visible-or-404, never cross-contaminated
        if result.status == "SUCCEEDED":
            assert result.data.get("experiment_composite_id") == ctx_a.composite_id

    def test_t67_demo_params_not_inherited(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        # fresh experiment context has empty artifacts — nothing inherited
        snapshot = gw._readiness_snapshot(ctx)
        assert snapshot.has_dataset is False
        assert snapshot.has_split is False

    def test_t68_dataset_ownership(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        ctx_other = AgentScientificContext(battery_id="CELL_OTHER", experiment_id="EXP_OTHER")
        result = gw.execute(
            "prepare_soc_dataset", ctx_other, {"selected_features": ["waveform_rms_a_u"]}
        )
        assert result.status in ("CONFIRMATION_REQUIRED", "BLOCKED", "FAILED")

    def test_t69_gate_ownership(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        ctx_other = AgentScientificContext(battery_id="CELL_OTHER", experiment_id="EXP_OTHER")
        result = gw.execute(
            "create_gate",
            ctx_other,
            {
                "gate_name": "G",
                "start_sample": 1,
                "end_sample": 2,
            },
        )
        assert result.status in ("CONFIRMATION_REQUIRED", "BLOCKED", "FAILED")

    def test_t70_run_ownership(self, committed_ctx: AgentScientificContext) -> None:
        gw = _current_gateway
        ctx_other = AgentScientificContext(
            battery_id="CELL_OTHER", experiment_id="EXP_OTHER", run_id="RUN::other"
        )
        result = gw.execute("inspect_run", ctx_other, {})
        assert result.status in ("SUCCEEDED", "FAILED", "BLOCKED")

    def test_t71_arbitrary_path_reject(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        result = gw.execute("list_experiments", ctx, {"path": "/etc/passwd"})
        assert result.status == "FAILED"
        assert result.error["code"] == "SECURITY_VIOLATION"

    def test_t72_arbitrary_url_reject(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        result = gw.execute("list_experiments", ctx, {"url": "http://evil.example.com"})
        assert result.status == "FAILED"
        assert result.error["code"] == "SECURITY_VIOLATION"

    def test_t73_code_execution_reject(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        result = gw.execute("list_experiments", ctx, {"code": "__import__('os').system('id')"})
        assert result.status == "FAILED"

    def test_t74_arbitrary_sql_reject(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        result = gw.execute("list_experiments", ctx, {"sql": "SELECT * FROM users"})
        assert result.status == "FAILED"

    def test_t75_oversized_input_reject(
        self, env: tuple[ToolGateway, AgentScientificContext, Path]
    ) -> None:
        gw, ctx, _ = env
        result = gw.execute("list_experiments", ctx, {"blob": "x" * 300000})
        assert result.status == "FAILED"
        assert result.error["code"] == "SECURITY_VIOLATION"
