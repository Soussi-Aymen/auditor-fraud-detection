"""FastAPI entry: upload → SSE analysis stream → verify/dismiss → source viewer."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from pathlib import Path

import duckdb
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from app.jobs import store
from app.schemas import (
    FindingStatus,
    JobStatus,
    UploadResponse,
    VerdictResponse,
)

load_dotenv()

app = FastAPI(title="Auditor Fraud Detection", version="0.5.0")


class SourceLine(BaseModel):
    n: int
    text: str


class SourceViewResponse(BaseModel):
    path: str
    kind: str  # text | document_extract | binary_note
    lines: list[SourceLine] = Field(default_factory=list)
    focus_line: int | None = None
    focus_end: int | None = None
    note: str | None = None
    quote: str | None = None


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


@app.get("/api/analyze/{job_id}/source", response_model=SourceViewResponse)
def view_source(
    job_id: str,
    path: str = Query(..., min_length=1, description="Dossier-relative path"),
    line: int | None = Query(None, ge=1),
    locator: str | None = Query(None),
    quote: str | None = Query(None),
) -> SourceViewResponse:
    """Open a cited source file and optionally focus a line / extract."""
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status != JobStatus.ready or job.extract_dir is None:
        raise HTTPException(status_code=409, detail="job not ready")

    # Prevent path traversal
    rel = path.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        raise HTTPException(status_code=400, detail="invalid path")
    root = job.extract_dir.resolve()
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="path outside dossier") from exc

    suffix = target.suffix.lower()
    focus = line

    # PDF / DOCX: serve extracted text chunks from DuckDB, focused by locator
    if suffix in {".pdf", ".docx"}:
        return _document_extract(job.session_dir / "session.duckdb", rel, locator, quote, focus)

    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {rel}")

    if suffix in {".xlsx", ".xls"}:
        return SourceViewResponse(
            path=rel,
            kind="binary_note",
            note=(
                "Excel workbook — open in your spreadsheet app. "
                f"Citation locator: {locator or '—'}. Quote: {quote or '—'}"
            ),
            quote=quote,
            focus_line=focus,
        )

    try:
        from app.parsing.encoding import read_text_file

        text = read_text_file(target)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    raw_lines = text.splitlines()
    # Cap very large files for UI; keep window around focus
    max_lines = 4000
    start = 1
    if focus and len(raw_lines) > max_lines:
        start = max(1, focus - max_lines // 2)
        end = min(len(raw_lines), start + max_lines - 1)
        slice_lines = raw_lines[start - 1 : end]
        numbered = [SourceLine(n=start + i, text=ln) for i, ln in enumerate(slice_lines)]
    else:
        numbered = [SourceLine(n=i, text=ln) for i, ln in enumerate(raw_lines, start=1)]

    # If no line provided, try quote/locator search
    if focus is None and (quote or locator):
        needles = []
        if quote:
            needles.append(quote[:80])
        if locator:
            for part in locator.split(";"):
                if "=" in part:
                    needles.append(part.split("=", 1)[1].split(",")[0].strip())
        for ln in numbered:
            if any(n and n in ln.text for n in needles):
                focus = ln.n
                break

    return SourceViewResponse(
        path=rel,
        kind="text",
        lines=numbered,
        focus_line=focus,
        focus_end=focus,
        quote=quote,
    )


def _document_extract(
    db_path: Path,
    rel: str,
    locator: str | None,
    quote: str | None,
    focus: int | None,
) -> SourceViewResponse:
    if not db_path.is_file():
        raise HTTPException(status_code=404, detail="session database missing")
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT locator, text FROM doc_chunks
            WHERE source_path = ?
            ORDER BY locator
            """,
            [rel],
        ).fetchall()
    except duckdb.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        conn.close()

    if not rows:
        return SourceViewResponse(
            path=rel,
            kind="binary_note",
            note="No extracted text cache for this document.",
            quote=quote,
        )

    lines: list[SourceLine] = []
    focus_n: int | None = focus
    for i, (loc, text) in enumerate(rows, start=1):
        body = str(text or "").replace("\n", " ").strip()
        label = f"[{loc}] {body}"
        lines.append(SourceLine(n=i, text=label))
        if locator and str(loc) == locator:
            focus_n = i
        elif quote and quote[:40] in body and focus_n is None:
            focus_n = i
        elif focus is not None:
            # page:N / para:N — match numeric part
            m = re.search(r"(\d+)", locator or "")
            if m and str(loc).endswith(m.group(1)):
                focus_n = i

    return SourceViewResponse(
        path=rel,
        kind="document_extract",
        lines=lines,
        focus_line=focus_n,
        focus_end=focus_n,
        note="Showing extracted text (PDF/DOCX). Focus jumps to the cited passage.",
        quote=quote,
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
