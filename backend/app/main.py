"""FastAPI entry: upload → SSE analysis stream → verify/dismiss."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.jobs import store
from app.schemas import (
    FindingStatus,
    JobStatus,
    UploadResponse,
    VerdictResponse,
)

load_dotenv()

app = FastAPI(title="Auditor Fraud Detection", version="0.4.0")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)) -> UploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty upload")
    job = await store.create_from_upload(file.filename, content)
    return UploadResponse(job_id=job.id)


@app.get("/api/analyze/{job_id}/stream", response_class=EventSourceResponse)
async def analyze_stream(job_id: str) -> AsyncIterator[ServerSentEvent]:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    yield ServerSentEvent(
        event="status",
        data={"job_id": job.id, "status": job.status.value},
    )

    while not job.ready.is_set():
        yield ServerSentEvent(
            event="status",
            data={"job_id": job.id, "status": job.status.value},
        )
        try:
            await asyncio.wait_for(job.ready.wait(), timeout=1.0)
        except TimeoutError:
            continue

    if job.status == JobStatus.error:
        yield ServerSentEvent(
            event="error",
            data={"job_id": job.id, "message": job.error or "unknown error"},
        )
        return

    yield ServerSentEvent(
        event="status",
        data={
            "job_id": job.id,
            "status": job.status.value,
            "tables": len(job.table_counts),
        },
    )

    # Skip-band findings are already filtered in the detector runner.
    ordered = sorted(job.findings, key=lambda f: f.confidence, reverse=True)
    for finding in ordered:
        if finding.band.value == "skip":
            continue
        yield ServerSentEvent(
            event="finding",
            data=finding.model_dump(mode="json"),
        )

    emitted = [f for f in ordered if f.band.value != "skip"]
    yield ServerSentEvent(
        event="done",
        data={"job_id": job.id, "count": len(emitted)},
    )


@app.post(
    "/api/analyze/{job_id}/findings/{finding_id}/verify",
    response_model=VerdictResponse,
)
async def verify_finding(job_id: str, finding_id: str) -> VerdictResponse:
    return _set_verdict(job_id, finding_id, FindingStatus.verified)


@app.post(
    "/api/analyze/{job_id}/findings/{finding_id}/dismiss",
    response_model=VerdictResponse,
)
async def dismiss_finding(job_id: str, finding_id: str) -> VerdictResponse:
    return _set_verdict(job_id, finding_id, FindingStatus.dismissed)


def _set_verdict(job_id: str, finding_id: str, status: FindingStatus) -> VerdictResponse:
    try:
        finding = store.set_verdict(job_id, finding_id, status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return VerdictResponse(job_id=job_id, finding_id=finding.id, status=finding.status)
