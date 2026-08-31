"""Persist BRW-008 anchor state and QA reports.

The canonical machine state is ``time_anchors.json`` (consumed by BRW-009).
QA reports (JSON + HTML) are written under ``data/artifacts/...``.

Nothing here mutates inputs; every write targets the processed/artifacts
output roots only.
"""

from __future__ import annotations

import json
from pathlib import Path

from battery_workbench.synchronization.schemas import (
    TimeAnchorReport,
    TimeAnchorState,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _state_payload(state: TimeAnchorState) -> dict:
    return {
        "battery_id": state.battery_id,
        "experiment_id": state.experiment_id,
        "anchor_version": state.anchor_version,
        "experiment_reference": state.experiment_reference,
        "assets": [asset.model_dump(mode="json") for asset in state.assets],
        "warnings": list(state.warnings),
        "limitations": list(state.limitations),
        "validated_sync": state.validated_sync,
    }


def write_time_anchor_state(
    state: TimeAnchorState,
    *,
    processed_root: Path,
    artifacts_root: Path,
    html_report: TimeAnchorReport | None = None,
) -> dict[str, Path]:
    """Write the canonical state and (optionally) the QA report.

    Returns a map of artifact kind -> written path (at least ``time_anchors``).
    """
    processed_root = Path(processed_root)
    artifacts_root = Path(artifacts_root)

    canonical_dir = processed_root / "synchronization" / state.battery_id / state.experiment_id
    canonical_path = canonical_dir / "time_anchors.json"
    _write_json(canonical_path, _state_payload(state))

    result = {"time_anchors": canonical_path}

    if html_report is not None:
        report_dir = artifacts_root / state.battery_id / state.experiment_id / "time_anchor"
        json_path = report_dir / "time_anchor_report.json"
        _write_json(json_path, html_report.model_dump(mode="json"))
        html_path = report_dir / "time_anchor_report.html"
        html_path.write_text(_render_html(html_report), encoding="utf-8")
        result["report_json"] = json_path
        result["report_html"] = html_path

    return result


def _render_html(report: TimeAnchorReport) -> str:
    """Minimal valid HTML report with the required sections."""
    assets_section = "\n".join(
        f"<li><code>{asset.get('asset_id', '?')}</code> — "
        f"status: {asset.get('anchor_status', 'N/A')} — "
        f"validated_sync: {asset.get('validated_sync', False)}</li>"
        for asset in report.assets
    )
    warnings = "\n".join(f"<li>{w}</li>" for w in report.warnings) or "<li>none</li>"
    limitations = "\n".join(f"<li>{l}</li>" for l in report.limitations) or "<li>none</li>"
    return (
        "<!doctype html>\n"
        "<html><head><meta charset='utf-8'><title>Time Anchor Report</title></head>\n"
        "<body>\n"
        f"<h1>Time Anchor Report</h1>\n"
        f"<p>experiment_id: {report.experiment_id} — battery_id: {report.battery_id}</p>\n"
        f"<p>status: {report.status}</p>\n"
        f"<p>validated_sync: {report.validated_sync}</p>\n"
        "<h2>Assets</h2>\n"
        f"<ul>{assets_section}</ul>\n"
        "<h2>Warnings</h2>\n"
        f"<ul>{warnings}</ul>\n"
        "<h2>Limitations</h2>\n"
        f"<ul>{limitations}</ul>\n"
        "</body></html>\n"
    )
