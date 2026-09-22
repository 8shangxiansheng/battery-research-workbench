"""BRW-021R2 — Feature Ranking, Target-Conditional Relationship & Selection Handoff.

R01–R32 against the REAL CELL_001/EXP_001 artifacts (ranking is read-only;
only the assistant-session test touches session state, which is expected
selection/session audit state per §28).

The reported bug ("无法加载此视图" on Relationships/Step 4) was:
POST feature-target-ranking with tof_us → 404 NOT_FOUND unknown features.
R01 pins that regression; the rest pins the scientific contract (§3–§33).
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"
RAW = REPO / "data" / "raw"

B, E = "CELL_001", "EXP_001"
RANK_URL = f"/api/v1/experiments/{B}/{E}/feature-target-ranking"
SPLIT_ID = "SPLIT::23ebb24fe8e7732fac780dde"
SPLIT_DIR = (
    PROCESSED / "splits" / B / E / "DS::83013a61b316f3489093b358" / SPLIT_ID
)

has_real = (PROCESSED / "multimodal" / B / E).is_dir() and SPLIT_DIR.is_dir()

pytestmark = pytest.mark.skipif(not has_real, reason="CELL_001/EXP_001 + split artifacts required")


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = create_app(raw_root=RAW, processed_root=PROCESSED, runs_root=REPO / "data/artifacts/runs")
    return TestClient(app)


def _rank(client: TestClient, **body) -> dict:
    resp = client.post(RANK_URL, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _by_code(data: dict) -> dict[str, dict]:
    return {r["feature_code"]: r for r in data["ranking"]}


# ---------------------------------------------------------------- load / join

def test_r01_ranking_loads_including_canonical_tof(client: TestClient) -> None:
    """The exact failing request from the bug report must now succeed."""
    data = _rank(client, target_id="reference_soc_percent",
                 features=["tof_us", "BOTTOM_AMP", "SWA", "BPS"], mode="EXPLORATORY")
    assert set(_by_code(data)) == {"tof_us", "BOTTOM_AMP", "SWA", "BPS"}
    assert data["mode"] == "EXPLORATORY"


def test_r03_measurement_event_join_counts(client: TestClient) -> None:
    """Event-grain join: 3999 aligned frames, 3995 target-eligible (§17)."""
    data = _rank(client, target_id="reference_soc_percent", features=["SWA"], mode="EXPLORATORY")
    s = data["summary"]
    assert s["aligned_events"] == 3999
    assert s["target_eligible_rows"] == 3995
    assert _by_code(data)["SWA"]["n_valid"] == 3995


# ------------------------------------------------------- correlation contract

@pytest.fixture(scope="module")
def soc_ranking(client: TestClient) -> dict:
    return _rank(client, target_id="reference_soc_percent",
                 features=["BOTTOM_AMP", "SWA", "amplitude_a_u"], mode="EXPLORATORY")


def test_r04_pearson_present(client: TestClient, soc_ranking: dict) -> None:
    e = _by_code(soc_ranking)["BOTTOM_AMP"]
    assert e["pearson_overall"] is not None and e["pearson_overall"] > 0.8


def test_r05_spearman_present_and_independent(client: TestClient, soc_ranking: dict) -> None:
    e = _by_code(soc_ranking)["BOTTOM_AMP"]
    assert e["spearman_overall"] is not None
    assert abs(e["spearman_overall"] - e["pearson_overall"]) > 1e-9


def test_r06_n_valid_and_missing_accounting(client: TestClient, soc_ranking: dict) -> None:
    for e in soc_ranking["ranking"]:
        assert isinstance(e["n_valid"], int) and isinstance(e["n_missing"], int)
        assert e["n_valid"] + e["n_missing"] <= 3999


def test_r07_overall_charge_discharge_fields(client: TestClient, soc_ranking: dict) -> None:
    for e in soc_ranking["ranking"]:
        for k in ("pearson_overall", "pearson_charge", "pearson_discharge",
                  "spearman_overall", "spearman_charge", "spearman_discharge"):
            assert k in e


def test_r08_direction_enum(client: TestClient, soc_ranking: dict) -> None:
    allowed = {"SAME_DIRECTION", "DIRECTION_DEPENDENT", "WEAK_ASSOCIATION",
               "INSUFFICIENT_VARIATION", "UNAVAILABLE"}
    for e in soc_ranking["ranking"]:
        assert e["direction_status"] in allowed


def test_r09_overall_cancellation_does_not_demote(client: TestClient, soc_ranking: dict) -> None:
    """SWA: tiny overall Pearson but reversed charge/discharge lobes → DIRECTION_DEPENDENT."""
    swa = _by_code(soc_ranking)["SWA"]
    assert abs(swa["pearson_overall"]) < 0.15  # overall nearly cancels
    assert swa["pearson_charge"] > 0 > swa["pearson_discharge"]
    assert swa["direction_status"] == "DIRECTION_DEPENDENT"
    assert swa["direction_dependent"] is True  # legacy boolean kept in sync


def test_r10_direction_classifier_unit() -> None:
    from battery_workbench.api.routes.features_v2 import _rank_direction_status
    assert _rank_direction_status("VALID", 0.47, -0.56, -0.19) == "DIRECTION_DEPENDENT"
    assert _rank_direction_status("VALID", 0.4, 0.5, 0.45) == "SAME_DIRECTION"
    assert _rank_direction_status("VALID", 0.05, -0.04, 0.03) == "WEAK_ASSOCIATION"
    assert _rank_direction_status("INSUFFICIENT_VARIATION", None, None, None) == "INSUFFICIENT_VARIATION"
    assert _rank_direction_status("TEMPERATURE_UNAVAILABLE", None, None, None) == "UNAVAILABLE"


# ------------------------------------------------------------ targets & gates

def test_r11_temperature_unavailable_no_fake_numbers(client: TestClient) -> None:
    data = _rank(client, target_id="temperature_c", features=["SWA"], mode="EXPLORATORY")
    e = _by_code(data)["SWA"]
    assert e["status"] == "TEMPERATURE_UNAVAILABLE"
    assert e["direction_status"] == "UNAVAILABLE"
    assert e["pearson_overall"] is None and e["spearman_overall"] is None


def test_r24_soh_cycle_level_only(client: TestClient) -> None:
    data = _rank(client, target_id="soh_capacity_reference_percent",
                 features=["SWA"], mode="EXPLORATORY")
    assert data["ranking"] == []
    assert data["group_summary"]


def test_r25_direct_target_branch(client: TestClient) -> None:
    data = _rank(client, target_id="voltage_v", features=["BOTTOM_AMP"], mode="EXPLORATORY")
    e = _by_code(data)["BOTTOM_AMP"]
    assert e["scope_note"]
    assert e["pearson_charge"] is None  # no fake state-stratified stats


# ----------------------------------------------------------- canonical TOF

def test_r12_canonical_tof_provenance(client: TestClient) -> None:
    data = _rank(client, target_id="reference_soc_percent", features=["tof_us"], mode="EXPLORATORY")
    p = data["tof_provenance"]
    assert p["tof_method_id"] == "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1"
    assert p["sampling_rate_hz"] == 50_000_000 and p["sampling_rate_verified"] is True
    ct = pd.read_parquet(PROCESSED / "features_physical" / B / E / "canonical_tof.parquet",
                         columns=["gate_calibration_id"])
    assert p["gate_calibration_id"] == ct["gate_calibration_id"].iloc[0]  # values' source
    assert p["current_gate_calibration_id"].startswith("GC-TOF::")
    assert isinstance(p["current_gate_calibration_version"], int)
    assert isinstance(p["gate_calibration_window_matches_current"], bool)
    assert p["gate_calibration_refresh_required"] is False


def test_r13_legacy_xcorr_marked_diagnostic(client: TestClient) -> None:
    data = _rank(client, target_id="reference_soc_percent", features=["TOF_XCORR"], mode="EXPLORATORY")
    e = _by_code(data)["TOF_XCORR"]
    assert e["legacy_diagnostic"] is True
    assert "canonical" in e["note"]


def test_r14_association_only_semantics(client: TestClient, soc_ranking: dict) -> None:
    assert "EXPLORATORY_NOT_ML_SAFE" in soc_ranking["limitations"]
    assert "RANKING_DESCRIBES_ASSOCIATION_ONLY" in soc_ranking["limitations"]
    assert "Default display ordering" in soc_ranking["ordering"]
    # the only best/causal/predictive wording allowed is an explicit disclaimer
    blob = soc_ranking["note"].lower()
    assert "association" in blob
    assert "not imply causation" in blob or "does not" in blob


# --------------------------------------------------------------- ML-safe §12/13

def _train_ids(fold: str) -> set[str]:
    sa = pd.read_parquet(SPLIT_DIR / "split_assignments.parquet",
                         columns=["measurement_event_id", "role", "fold"])
    return set(sa[(sa["fold"].astype(str) == fold) & (sa["role"] == "TRAIN")]["measurement_event_id"])


def test_r15_ml_safe_requires_split_and_fold(client: TestClient) -> None:
    r = client.post(RANK_URL, json={"target_id": "reference_soc_percent", "features": ["SWA"],
                                    "mode": "TRAIN_ONLY_ML_SAFE"})
    assert r.status_code == 422 or "INVALID_SPLIT" in r.text
    r2 = client.post(RANK_URL, json={"target_id": "reference_soc_percent", "features": ["SWA"],
                                     "mode": "TRAIN_ONLY_ML_SAFE", "split_id": SPLIT_ID})
    assert "INVALID_SPLIT" in r2.text  # fold missing → LEGAO TRAIN-union would leak


def test_r16_train_only_structural_membership(client: TestClient) -> None:
    data = _rank(client, target_id="reference_soc_percent", features=["SWA"],
                 mode="TRAIN_ONLY_ML_SAFE", split_id=SPLIT_ID, fold_index="fold1")
    assert data["mode"] == "TRAIN_ONLY_ML_SAFE"
    assert data["split_id"] == SPLIT_ID and data["fold_index"] == "fold1"
    labels = pd.read_parquet(PROCESSED / "labels" / B / E / "event_labels.parquet")
    me = pd.read_parquet(PROCESSED / "multimodal" / B / E / "measurement_events.parquet",
                         columns=["measurement_event_id", "analysis_eligible"])
    eligible_soc = set(me[me["analysis_eligible"]]["measurement_event_id"]) & set(
        labels[labels["soc_reference_percent"].notna()]["measurement_event_id"])
    expected = len(_train_ids("fold1") & eligible_soc)
    assert _by_code(data)["SWA"]["n_valid"] == expected
    assert "TRAIN_ONLY_ML_SAFE" in data["limitations"]


def test_r18_fold_specific_rankings(client: TestClient) -> None:
    f1 = _rank(client, target_id="reference_soc_percent", features=["SWA"],
               mode="TRAIN_ONLY_ML_SAFE", split_id=SPLIT_ID, fold_index="fold1")
    f2 = _rank(client, target_id="reference_soc_percent", features=["SWA"],
               mode="TRAIN_ONLY_ML_SAFE", split_id=SPLIT_ID, fold_index="fold2")
    labels = pd.read_parquet(PROCESSED / "labels" / B / E / "event_labels.parquet")
    me = pd.read_parquet(PROCESSED / "multimodal" / B / E / "measurement_events.parquet",
                         columns=["measurement_event_id", "analysis_eligible"])
    eligible_soc = set(me[me["analysis_eligible"]]["measurement_event_id"]) & set(
        labels[labels["soc_reference_percent"].notna()]["measurement_event_id"])
    n1 = _by_code(f1)["SWA"]["n_valid"]
    n2 = _by_code(f2)["SWA"]["n_valid"]
    assert n1 == len(_train_ids("fold1") & eligible_soc)
    assert n2 == len(_train_ids("fold2") & eligible_soc)
    assert n1 < 3995 and n2 < 3995  # fold-specific TRAIN subsets, not the full data


def test_r17_heldout_permutation_invariance(client: TestClient, monkeypatch) -> None:
    """Permuting held-out y must not change a TRAIN-only ranking by one bit."""
    from battery_workbench.api.routes import features_v2

    held = set(_train_ids("fold2")) ^ set(
        pd.read_parquet(SPLIT_DIR / "split_assignments.parquet", columns=["measurement_event_id"])
        ["measurement_event_id"])
    original = _rank(client, target_id="reference_soc_percent", features=["SWA", "BOTTOM_AMP"],
                     mode="TRAIN_ONLY_ML_SAFE", split_id=SPLIT_ID, fold_index="fold2")

    real_load = features_v2._load_events_labels

    def shuffled(request, battery_id, experiment_id):
        events, labels = real_load(request, battery_id, experiment_id)
        labels = labels.copy()
        mask = labels["measurement_event_id"].isin(held)
        vals = list(labels.loc[mask, "soc_reference_percent"])
        random.Random(20260922).shuffle(vals)  # held-out y destroyed; TRAIN untouched
        labels.loc[mask, "soc_reference_percent"] = vals
        return events, labels

    monkeypatch.setattr(features_v2, "_load_events_labels", shuffled)
    permuted = _rank(client, target_id="reference_soc_percent", features=["SWA", "BOTTOM_AMP"],
                     mode="TRAIN_ONLY_ML_SAFE", split_id=SPLIT_ID, fold_index="fold2")
    assert json.dumps(permuted["ranking"]) == json.dumps(original["ranking"])

    # control: the same permutation MUST move an exploratory ranking (it reads held-out y)
    monkeypatch.undo()
    expl_before = _rank(client, target_id="reference_soc_percent", features=["SWA"], mode="EXPLORATORY")
    monkeypatch.setattr(features_v2, "_load_events_labels", shuffled)
    expl_after = _rank(client, target_id="reference_soc_percent", features=["SWA"], mode="EXPLORATORY")
    assert _by_code(expl_before)["SWA"]["pearson_overall"] != _by_code(expl_after)["SWA"]["pearson_overall"]


# ------------------------------------------------------------------ vocab

def test_r19_alias_dedup_single_series(client: TestClient) -> None:
    data = _rank(client, target_id="reference_soc_percent",
                 features=["amplitude_a_u", "waveform_abs_peak_a_u"], mode="EXPLORATORY")
    dropped = {a["dropped"] for a in data["alias_dedup"]}
    assert "waveform_abs_peak_a_u" in dropped or "amplitude_a_u" in dropped
    codes = [e["feature_code"] for e in data["ranking"]]
    assert len(codes) == 1


def test_r20_forbidden_predictor_formally_blocked(client: TestClient) -> None:
    data = _rank(client, target_id="reference_soc_percent",
                 features=["soc_dod_percent", "SWA"], mode="EXPLORATORY")
    blocked = {b["feature_code"]: b for b in data["blocked_forbidden"]}
    assert blocked["soc_dod_percent"]["status"] == "BLOCKED_FORBIDDEN_PREDICTOR"
    assert blocked["soc_dod_percent"]["commit_eligible"] is False
    assert "soc_dod_percent" not in _by_code(data)


def test_r21_unknown_feature_still_404(client: TestClient) -> None:
    r = client.post(RANK_URL, json={"target_id": "reference_soc_percent",
                                    "features": ["totally_made_up_x"], "mode": "EXPLORATORY"})
    assert r.status_code == 404
    assert "unknown features" in r.json()["error"]["message"]


def test_r22_source_movmean5_exploratory_only(client: TestClient) -> None:
    data = _rank(client, target_id="reference_soc_percent", features=["SWA"],
                 mode="EXPLORATORY", variant="SOURCE_MOVMEAN5")
    e = _by_code(data)["SWA"]
    assert e["exploratory_only"] is True and e["commit_eligible"] is False
    r = client.post(RANK_URL, json={"target_id": "reference_soc_percent", "features": ["SWA"],
                                     "mode": "TRAIN_ONLY_ML_SAFE", "split_id": SPLIT_ID,
                                     "fold_index": "fold1", "variant": "SOURCE_MOVMEAN5"})
    assert r.json()["error"]["code"] == "SCIENTIFIC_ACTION_REQUIRED"


def test_r23_detail_scatter_backend_computed(client: TestClient) -> None:
    data = _rank(client, target_id="reference_soc_percent", features=["SWA"],
                 mode="EXPLORATORY", detail_feature="SWA")
    det = data["detail"]
    assert det["feature_code"] == "SWA"
    for scope, expect in (("overall", 3995), ("charge", None), ("discharge", None)):
        sc = det["scopes"][scope]
        assert sc["n"] > 0 and 0 < len(sc["points"]) <= 300
        if scope == "overall":
            assert sc["n"] == expect
    assert det["excluded_ineligible"] == 4


# ------------------------------------------------------------- selection handoff

def test_r26_ranking_selection_parity_with_preview(client: TestClient) -> None:
    """Committed ranking locators must equal the Preview X columns (§27 parity)."""
    feats = ["tof_us", "BOTTOM_AMP", "SWA", "amplitude_a_u"]
    data = _rank(client, target_id="reference_soc_percent", features=feats, mode="EXPLORATORY")
    ranked = [e["feature_code"] for e in data["ranking"]]
    prev = client.post(
        f"/api/v1/experiments/{B}/{E}/feature-label-preview",
        json={"target_id": "reference_soc_percent", "features": ranked, "limit": 5},
    )
    assert prev.status_code == 200
    pd_ = prev.json()["data"]
    assert sorted(pd_["features"]) == sorted(ranked)
    assert set(pd_["rows"][0]["values"]) == set(ranked)


def test_r27_retry_refetch_is_stable(client: TestClient) -> None:
    a = _rank(client, target_id="reference_soc_percent", features=["SWA"], mode="EXPLORATORY")
    b = _rank(client, target_id="reference_soc_percent", features=["SWA"], mode="EXPLORATORY")
    assert json.dumps(a["ranking"]) == json.dumps(b["ranking"])


# -------------------------------------------------------------- read-only §37

KEY_ARTIFACTS = [
    "multimodal/CELL_001/EXP_001/measurement_events.parquet",
    "labels/CELL_001/EXP_001/event_labels.parquet",
    "features_physical/CELL_001/EXP_001/canonical_tof.parquet",
    "features_physical/CELL_001/EXP_001/canonical_tof_manifest.json",
    "datasets/CELL_001/EXP_001/SOC/DS::83013a61b316f3489093b358/dataset.parquet",
    f"splits/CELL_001/EXP_001/DS::83013a61b316f3489093b358/{SPLIT_ID}/split_assignments.parquet",
    "models/CELL_001/EXP_001/DS::83013a61b316f3489093b358/SPLIT::23ebb24fe8e7732fac780dde/model_comparison.parquet",
]


def test_r28_ranking_is_read_only_artifact_hash_invariance(client: TestClient) -> None:
    def hashes() -> dict[str, str]:
        return {p: hashlib.sha256((PROCESSED / p).read_bytes()).hexdigest() for p in KEY_ARTIFACTS}

    before = hashes()
    _rank(client, target_id="reference_soc_percent",
          features=["tof_us", "SWA", "BOTTOM_AMP", "BPS"], mode="EXPLORATORY")
    _rank(client, target_id="reference_soc_percent", features=["SWA"],
          mode="TRAIN_ONLY_ML_SAFE", split_id=SPLIT_ID, fold_index="fold1")
    _rank(client, target_id="reference_soc_percent", features=["SWA"],
          mode="EXPLORATORY", detail_feature="SWA")
    assert hashes() == before


# ------------------------------------------------------------------- agent §32/33

def test_r29_agent_exploratory_ranking_via_session(client: TestClient) -> None:
    sid = client.post(f"/api/v1/experiments/{B}/{E}/assistant/session").json()["data"]["session_id"]
    resp = client.post(
        f"/api/v1/experiments/{B}/{E}/assistant/session/{sid}/message",
        json={"message": "哪些超声特征与 Reference SOC 的关系明显？给出 ranking", "current_page": "analysis"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "EXPLORATORY" in data["message"]
    assert "非 ML-safe" in data["message"] or "ML-safe" in data["message"]
    assert "不代表因果" in data["message"]


def _planner_ctx(mode: str, split_id: str | None, fold: str | None = "fold1"):
    from battery_workbench.agent_assistant.intents import classify_intent
    from battery_workbench.agent_assistant.planner import ResearchPlanner
    from battery_workbench.agent_assistant.session import AgentResearchSession, SessionStore
    from battery_workbench.agent_tools.gateway import ToolGateway
    from battery_workbench.api.service import WorkbenchService

    service = WorkbenchService(raw_root=RAW, processed_root=PROCESSED,
                               runs_root=REPO / "data/artifacts/runs")
    store_root = Path("/tmp") / "brw021r2-store"
    store_root.mkdir(exist_ok=True)
    planner = ResearchPlanner(gateway=ToolGateway(service=service),
                              store=SessionStore(store_root))
    ctx = AgentResearchSession(session_id="t-r30", battery_id=B, experiment_id=E,
                               selected_target="reference_soc_percent",
                               feature_selection_mode=mode, split_id=split_id,
                               ranking_fold=fold)
    classified = classify_intent("哪些特征与 SOC 关系明显", mode=mode)
    return planner, ctx, classified


def test_r30_agent_ml_safe_without_split_is_scientific_block() -> None:
    planner, ctx, classified = _planner_ctx("ML_SAFE", None)
    resp = planner._relationship_result(ctx, classified, ranking=True)
    assert resp.status == "SCIENTIFIC_BLOCK"
    assert "grouped split" in resp.message


def test_r31_agent_ml_safe_ranking_is_train_only() -> None:
    planner, ctx, classified = _planner_ctx("ML_SAFE", SPLIT_ID, "fold2")
    resp = planner._relationship_result(ctx, classified, ranking=True)
    assert resp.status != "SCIENTIFIC_BLOCK"
    assert "TRAIN-only" in resp.message and "fold2" in resp.message
    assert "held-out y 未进入 ranking" in resp.message


def test_r32_agent_cannot_bypass_structural_guard(client: TestClient) -> None:
    """Even a direct tool call cannot produce TRAIN_ONLY ranking without split+fold."""
    planner, ctx, _ = _planner_ctx("ML_SAFE", None)
    result = planner._execute("analyze_target_relationships", ctx, {
        "battery_id": B, "experiment_id": E, "target_id": "reference_soc_percent",
        "features": ["SWA"], "mode": "TRAIN_ONLY_ML_SAFE",
    })
    assert result.status != "SUCCEEDED"
    assert "INVALID_SPLIT" in json.dumps(result.error, default=str)
