"""System endpoints: health / capabilities / version."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from battery_workbench.api.dependencies import get_service

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    return {"data": get_service(request).health(), "meta": {}}


@router.get("/capabilities")
def capabilities(request: Request) -> dict[str, Any]:
    return {"data": get_service(request).capabilities(), "meta": {}}


@router.get("/version")
def version(request: Request) -> dict[str, Any]:
    return {"data": get_service(request).version(), "meta": {}}
