"""Typed orchestration models for experiment import.

These models describe the *planning/execution* layer of BRW-007. They do not
carry scientific data: they carry adapter routing decisions, per-modality
outcomes, output locations, warnings and structured errors.

Modality is intentionally ``str`` here (not the closed ``Modality`` Literal
from ``domain.asset``) so that unsupported-but-declared modalities can be
represented without weakening the core ``DataAsset.modality`` contract.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class ImportStatus(str, Enum):
    """Overall outcome of an import plan or execution."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class AssetImportStatus(str, Enum):
    """Outcome of a single DataAsset within a modality adapter."""

    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class ImportError(BaseModel):
    """Structured import error. Never a bare string."""

    code: str
    message: str
    battery_id: str | None = None
    experiment_id: str | None = None
    modality: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    adapter_name: str | None = None


class AssetImportResult(BaseModel):
    asset_id: str
    status: AssetImportStatus
    output_paths: list[Path] = Field(default_factory=list)
    error: ImportError | None = None


class ModalityImportResult(BaseModel):
    """Outcome of dispatching one modality's assets through one adapter."""

    modality: str
    adapter_name: str
    adapter_version: str
    asset_ids: list[str]
    status: ImportStatus
    asset_results: list[AssetImportResult] = Field(default_factory=list)
    output_paths: list[Path] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[ImportError] = Field(default_factory=list)


class ExperimentImportPlan(BaseModel):
    """Dry-run: what would be imported, without invoking any parser."""

    battery_id: str
    experiment_id: str
    modalities: list[str]
    asset_groups: dict[str, list[str]]
    adapter_assignments: dict[str, str]
    expected_output_paths: list[Path]
    unsupported_modalities: dict[str, list[str]]
    warnings: list[str] = Field(default_factory=list)


class ExperimentImportResult(BaseModel):
    """Executed import outcome for one Experiment."""

    battery_id: str
    experiment_id: str
    status: ImportStatus
    requested_modalities: list[str]
    imported_modalities: list[str]
    skipped_modalities: list[str]
    unsupported_modalities: dict[str, list[str]]
    source_asset_ids: list[str]
    modality_results: list[ModalityImportResult] = Field(default_factory=list)
    output_paths: list[Path] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[ImportError] = Field(default_factory=list)
