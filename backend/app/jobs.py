"""In-memory job store: parse zip, run detectors, persist verdicts."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.config import load_detector_config
from app.detection import run_detectors
from app.llm import enrich_findings, policy_config_overrides
from app.parsing.pipeline import load_dossier
from app.schemas import (
    Finding,
    FindingStatus,
    JobStatus,
)

SESSIONS_ROOT = Path(__file__).resolve().parents[1] / "data" / "sessions"


@dataclass
class Job:
    id: str
    status: JobStatus
    session_dir: Path
    zip_path: Path
    error: str | None = None
    findings: list[Finding] = field(default_factory=list)
    table_counts: dict[str, int] = field(default_factory=dict)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


class JobStore:
    def __init__(self, sessions_root: Path | None = None) -> None:
        self.sessions_root = sessions_root or SESSIONS_ROOT
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def create_from_upload(self, filename: str, content: bytes) -> Job:
        job_id = uuid.uuid4().hex[:12]
        session_dir = self.sessions_root / job_id
        # Keep zip outside session_dir — load_dossier clears that directory.
        safe_name = Path(filename).name or "upload.zip"
        zip_path = self.sessions_root / f"{job_id}.{safe_name}"
        zip_path.write_bytes(content)

        job = Job(
            id=job_id,
            status=JobStatus.queued,
            session_dir=session_dir,
            zip_path=zip_path,
        )
        async with self._lock:
            self._jobs[job_id] = job
            job.task = asyncio.create_task(self._run(job))
        return job

    async def _run(self, job: Job) -> None:
        job.status = JobStatus.parsing
        try:
            parse = await asyncio.to_thread(
                load_dossier,
                job.zip_path,
                self.sessions_root,
                job.id,
            )
            # load_dossier clears session_dir; re-ensure verdicts path parent exists
            job.session_dir = self.sessions_root / job.id
            job.status = JobStatus.parsing  # detecting / LLM still under parsing for SSE

            def _detect_and_enrich() -> list[Finding]:
                cfg = policy_config_overrides(
                    parse.document_chunks,
                    load_detector_config(),
                )
                stage2 = cfg.get("stage2") or {}
                max_quote = int(stage2.get("max_quote_chars", 160))
                raw = run_detectors(parse, cfg=cfg)
                return enrich_findings(raw, max_quote_chars=max_quote)

            findings = await asyncio.to_thread(_detect_and_enrich)
            self._apply_saved_verdicts(job.session_dir, findings)
            job.findings = findings
            job.table_counts = dict(parse.table_counts)
            self._write_findings(job)
            job.status = JobStatus.ready
        except Exception as exc:  # noqa: BLE001 — surface to client via SSE
            job.status = JobStatus.error
            job.error = str(exc)
        finally:
            job.ready.set()

    def _findings_path(self, session_dir: Path) -> Path:
        return session_dir / "findings.json"

    def _verdicts_path(self, session_dir: Path) -> Path:
        return session_dir / "verdicts.json"

    def _write_findings(self, job: Job) -> None:
        path = self._findings_path(job.session_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [f.model_dump(mode="json") for f in job.findings]
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_verdicts(self, session_dir: Path) -> dict[str, str]:
        path = self._verdicts_path(session_dir)
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}

    def _apply_saved_verdicts(self, session_dir: Path, findings: list[Finding]) -> None:
        verdicts = self._load_verdicts(session_dir)
        for finding in findings:
            raw = verdicts.get(finding.id)
            if raw in (FindingStatus.verified.value, FindingStatus.dismissed.value):
                finding.status = FindingStatus(raw)

    def set_verdict(self, job_id: str, finding_id: str, status: FindingStatus) -> Finding:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError("job not found")
        if job.status != JobStatus.ready:
            raise RuntimeError(f"job not ready (status={job.status.value})")

        target: Finding | None = None
        for finding in job.findings:
            if finding.id == finding_id:
                finding.status = status
                target = finding
                break
        if target is None:
            raise KeyError("finding not found")

        verdicts = self._load_verdicts(job.session_dir)
        verdicts[finding_id] = status.value
        job.session_dir.mkdir(parents=True, exist_ok=True)
        self._verdicts_path(job.session_dir).write_text(
            json.dumps(verdicts, indent=2),
            encoding="utf-8",
        )
        self._write_findings(job)
        return target


store = JobStore()
