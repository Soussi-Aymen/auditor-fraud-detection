#!/usr/bin/env python3
"""Phase 2 smoke: upload sample zip → SSE findings → verify/dismiss persist."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from app.jobs import SESSIONS_ROOT, store  # noqa: E402
from app.main import app  # noqa: E402

SAMPLE_ZIP = ROOT / "data" / "Uebungsdaten_Muster_Verpackungen.zip"


def _parse_sse(raw: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name = "message"
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal event_name, data_lines
        if data_lines:
            payload = "\n".join(data_lines)
            events.append((event_name, json.loads(payload)))
        event_name = "message"
        data_lines = []

    for line in raw.splitlines():
        if line == "":
            flush()
        elif line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    flush()
    return events


def main() -> int:
    if not SAMPLE_ZIP.is_file():
        print(f"MISSING sample zip: {SAMPLE_ZIP}", file=sys.stderr)
        return 1

    # Isolate smoke jobs under a dedicated prefix root already used by store
    SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)

    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200, health.text

        with SAMPLE_ZIP.open("rb") as fh:
            up = client.post(
                "/api/upload",
                files={"file": ("Uebungsdaten_Muster_Verpackungen.zip", fh, "application/zip")},
            )
        assert up.status_code == 200, up.text
        job_id = up.json()["job_id"]
        print(f"job_id={job_id}")

        with client.stream("GET", f"/api/analyze/{job_id}/stream") as resp:
            assert resp.status_code == 200, resp.read()
            body = "".join(resp.iter_text())

        events = _parse_sse(body)
        kinds = [name for name, _ in events]
        print(f"sse_events={kinds}")

        assert "finding" in kinds, f"no finding events: {events}"
        assert "done" in kinds, f"no done event: {events}"
        assert "error" not in kinds, events

        findings = [data for name, data in events if name == "finding"]
        confidences = [f["confidence"] for f in findings]
        assert confidences == sorted(confidences, reverse=True), confidences
        print(f"findings={len(findings)} confidences={confidences}")

        for key in ("id", "title", "summary", "confidence", "band", "categories", "citations", "status"):
            assert key in findings[0], findings[0]

        fid = findings[0]["id"]
        verify = client.post(f"/api/analyze/{job_id}/findings/{fid}/verify")
        assert verify.status_code == 200, verify.text
        assert verify.json()["status"] == "verified"

        other = next(f["id"] for f in findings if f["id"] != fid)
        dismiss = client.post(f"/api/analyze/{job_id}/findings/{other}/dismiss")
        assert dismiss.status_code == 200, dismiss.text
        assert dismiss.json()["status"] == "dismissed"

        job = store.get(job_id)
        assert job is not None
        by_id = {f.id: f.status.value for f in job.findings}
        assert by_id[fid] == "verified"
        assert by_id[other] == "dismissed"

        verdicts_path = job.session_dir / "verdicts.json"
        assert verdicts_path.is_file(), verdicts_path
        saved = json.loads(verdicts_path.read_text(encoding="utf-8"))
        assert saved[fid] == "verified"
        assert saved[other] == "dismissed"
        print(f"verdicts={saved}")

    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
