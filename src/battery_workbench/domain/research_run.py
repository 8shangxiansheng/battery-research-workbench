from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ResearchRun(BaseModel):
    run_id: str
    project_id: str | None = None
    question: str
    dataset_query: dict[str, object] = Field(default_factory=dict)
    config: dict[str, object] = Field(default_factory=dict)
    git_commit: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
