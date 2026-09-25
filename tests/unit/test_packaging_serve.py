"""Packaging entry: SPA static mount + BRW_* env roots (Docker single-port)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from battery_workbench.api.app import create_app

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data" / "processed"


def _dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>SPA</html>")
    (dist / "assets" / "index-abc.js").write_text("console.log(1)")
    return dist


def test_spa_mount_serves_assets_and_deep_links(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    app = create_app(
        raw_root=tmp_path / "raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
        static_dir=dist,
    )
    client = TestClient(app)
    assert client.get("/").text == "<html>SPA</html>"
    js = client.get("/assets/index-abc.js")
    assert js.status_code == 200 and "console.log" in js.text
    # history deep link → index.html, not 404
    deep = client.get("/experiments/CELL_001/EXP_001/models")
    assert deep.status_code == 200 and deep.text == "<html>SPA</html>"


def test_spa_mount_keeps_api_404_envelope(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    app = create_app(
        raw_root=tmp_path / "raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
        static_dir=dist,
    )
    client = TestClient(app)
    missing = client.get("/api/v1/definitely-not-an-endpoint")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    # real API routes win over the fallback
    health = client.get("/api/v1/health")
    assert health.status_code == 200


def test_no_static_dir_means_api_only(tmp_path: Path) -> None:
    app = create_app(
        raw_root=tmp_path / "raw",
        processed_root=tmp_path / "processed",
        runs_root=tmp_path / "runs",
    )
    client = TestClient(app)
    assert client.get("/").status_code == 404


def test_serve_env_roots_applied(monkeypatch, tmp_path: Path) -> None:
    import importlib

    data = tmp_path / "data"
    monkeypatch.setenv("BRW_DATA_ROOT", str(data))
    monkeypatch.setenv("BRW_STATIC_DIR", "")
    for var in ("BRW_RAW_ROOT", "BRW_PROCESSED_ROOT", "BRW_RUNS_ROOT"):
        monkeypatch.delenv(var, raising=False)
    serve = importlib.import_module("battery_workbench.api.serve")
    importlib.reload(serve)
    svc = serve.app.state.workbench_service
    assert svc.raw_root == data / "raw"
    assert svc.processed_root == data / "processed"
    assert svc.runs_root == data / "artifacts" / "runs"
