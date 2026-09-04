"""BRW-024 shared request-scoped dependencies."""

from __future__ import annotations

from fastapi import Request

from battery_workbench.api.service import WorkbenchService


def get_service(request: Request) -> WorkbenchService:
    return request.app.state.workbench_service  # type: ignore[no-any-return]
