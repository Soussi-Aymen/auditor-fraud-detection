"""Finding / job API schemas for the SSE pipeline."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ConfidenceBand(str, Enum):
    skip = "skip"
    needs_human_verification = "needs_human_verification"
    high = "high"


class FindingStatus(str, Enum):
    open = "open"
    verified = "verified"
    dismissed = "dismissed"


class JobStatus(str, Enum):
    queued = "queued"
    parsing = "parsing"
    ready = "ready"
    error = "error"


class Citation(BaseModel):
    n: int
    file: str
    locator: str
    quote: str
    # Deep-link fields for UI source viewer (optional for backwards compat)
    source_path: str | None = None
    line: int | None = None
    row: int | None = None
    detail: str | None = None


class Finding(BaseModel):
    id: str
    title: str
    summary: str
    confidence: float = Field(ge=0, le=100)
    band: ConfidenceBand
    categories: list[str]
    citations: list[Citation]
    status: FindingStatus = FindingStatus.open


class UploadResponse(BaseModel):
    job_id: str


class VerdictResponse(BaseModel):
    job_id: str
    finding_id: str
    status: FindingStatus
