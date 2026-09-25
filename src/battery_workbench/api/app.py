"""BRW-024 FastAPI application factory — /api/v1 only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from battery_workbench.api.errors import (
    APIError,
    ErrorCode,
    error_response,
    generic_error_handler,
    new_request_id,
)
from battery_workbench.api.service import WorkbenchService


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns request_id, sets X-Request-ID header, injects it into envelope meta."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = new_request_id()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            body = b""
            async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                body += chunk
            try:
                data = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                data = None
            if isinstance(data, dict):
                meta = data.get("meta")
                if isinstance(meta, dict):
                    meta.setdefault("request_id", request_id)
                elif "meta" in data:
                    data["meta"] = {"request_id": request_id}
                if isinstance(data.get("error"), dict):
                    data["error"]["request_id"] = request_id
                response = JSONResponse(content=data, status_code=response.status_code)
                response.headers["X-Request-ID"] = request_id
        return response


def create_app(
    *,
    raw_root: Path | None = None,
    processed_root: Path | None = None,
    runs_root: Path | None = None,
    static_dir: Path | str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Battery Research Workbench API",
        version="1.0.0",
        openapi_url="/openapi.json",
        docs_url="/docs",
        tags=[
            {"name": "system"},
            {"name": "experiments"},
            {"name": "runs"},
            {"name": "scientific-resources"},
            {"name": "artifacts"},
        ],
    )

    def _custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        original = FastAPI.openapi
        schema = original(app)
        schema["tags"] = [
            {"name": "system"},
            {"name": "experiments"},
            {"name": "runs"},
            {"name": "scientific-resources"},
            {"name": "artifacts"},
        ]
        schema.setdefault("components", {}).setdefault("schemas", {})
        schema["components"]["schemas"]["ErrorEnvelope"] = {
            "type": "object",
            "properties": {
                "error": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "enum": [c.value for c in ErrorCode],
                        },
                        "message": {"type": "string"},
                        "details": {"type": "object"},
                        "request_id": {"type": "string"},
                    },
                    "required": ["code", "message", "request_id"],
                }
            },
            "required": ["error"],
        }
        schema["components"]["schemas"]["ResponseEnvelope"] = {
            "type": "object",
            "properties": {"data": {}, "meta": {"type": "object"}},
            "required": ["data"],
        }
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi  # type: ignore[method-assign]
    app.state.workbench_service = WorkbenchService(
        raw_root=raw_root, processed_root=processed_root, runs_root=runs_root
    )

    @app.exception_handler(APIError)
    async def _api_error_handler(request: Request, exc: APIError) -> JSONResponse:  # type: ignore[misc]
        request_id = getattr(request.state, "request_id", None) or new_request_id()
        resp = error_response(exc.code, exc.message, request_id, exc.details)
        resp.headers["X-Request-ID"] = request_id
        return resp

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:  # type: ignore[misc]
        request_id = getattr(request.state, "request_id", None) or new_request_id()
        resp = error_response(
            ErrorCode.VALIDATION_ERROR,
            "request validation failed",
            request_id,
            {
                "errors": [
                    {"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()
                ]
            },
        )
        resp.headers["X-Request-ID"] = request_id
        return resp

    app.add_exception_handler(APIError, _api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, generic_error_handler)
    app.add_middleware(RequestContextMiddleware)

    from battery_workbench.api.routes import (
        assistant,
        data,
        experiments,
        extensions,
        features_v2,
        intake,
        resources,
        runs,
        system,
        waveform,
    )

    app.include_router(system.router, prefix="/api/v1")
    app.include_router(intake.router, prefix="/api/v1")
    app.include_router(experiments.router, prefix="/api/v1")
    app.include_router(extensions.router, prefix="/api/v1")
    app.include_router(runs.router, prefix="/api/v1")
    app.include_router(resources.router, prefix="/api/v1")
    app.include_router(waveform.router, prefix="/api/v1")
    app.include_router(data.router, prefix="/api/v1")
    app.include_router(features_v2.router, prefix="/api/v1")
    app.include_router(assistant.router, prefix="/api/v1")

    if static_dir is not None:
        _mount_spa(app, Path(static_dir))
    return app


def _mount_spa(app: FastAPI, dist: Path) -> None:
    """Serve a built SPA (vite output) on the same origin: hashed assets under
    /assets, index.html for every non-/api GET path so deep links resolve."""
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    index = dist / "index.html"
    if not index.is_file():
        raise ValueError(f"static dir {dist} has no index.html")
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="spa-assets")
    api_prefixes = ("api", "docs", "redoc", "openapi.json")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(request: Request, full_path: str) -> FileResponse:
        if request.url.path.startswith("/api"):
            # keep the API envelope contract — the SPA fallback never
            # impersonates a missing endpoint
            raise APIError(ErrorCode.NOT_FOUND, "endpoint not found")
        candidate = (dist / full_path).resolve() if full_path else index
        if (
            full_path
            and not str(full_path).startswith(api_prefixes)
            and candidate.is_file()
            and dist.resolve() in candidate.parents
        ):
            return FileResponse(candidate)
        return FileResponse(index)


def as_envelope(data: Any, meta: dict | None = None) -> dict[str, Any]:
    return {"data": data, "meta": meta or {}}
