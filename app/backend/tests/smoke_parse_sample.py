#!/usr/bin/env python3
"""Phase 1 smoke: load sample zip → print table counts + one PDF/DOCX excerpt."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "app" / "backend"
sys.path.insert(0, str(BACKEND))

from app.parsing import load_dossier  # noqa: E402

SAMPLE_ZIP = ROOT / "data" / "Uebungsdaten_Muster_Verpackungen.zip"
SESSIONS = BACKEND / "data" / "sessions"


def main() -> int:
    if not SAMPLE_ZIP.is_file():
        print(f"MISSING sample zip: {SAMPLE_ZIP}", file=sys.stderr)
        return 1

    result = load_dossier(SAMPLE_ZIP, SESSIONS, session_id="smoke_phase1")
    print(f"session_id={result.session_id}")
    print(f"db_path={result.db_path}")
    print(f"extract_dir={result.extract_dir}")
    print(f"tables={len(result.table_counts)}")
    for name, count in sorted(result.table_counts.items()):
        print(f"  {name}: {count}")

    pdf_or_docx = [
        c
        for c in result.document_chunks
        if c.source_path.lower().endswith((".pdf", ".docx"))
    ]
    if not pdf_or_docx:
        print("ERROR: no PDF/DOCX chunks extracted", file=sys.stderr)
        return 1

    sample = pdf_or_docx[0]
    preview = sample.text[:240].replace("\n", " ")
    print("--- document excerpt ---")
    print(f"file={sample.source_path}")
    print(f"locator={sample.locator}")
    print(f"quote={preview!r}")
    print(f"doc_chunks_total={len(result.document_chunks)}")
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
