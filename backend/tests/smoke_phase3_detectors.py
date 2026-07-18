#!/usr/bin/env python3
"""Phase 3 smoke: detectors + scoring + skip filter on sample zip."""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.detection import run_detectors  # noqa: E402
from app.parsing import load_dossier  # noqa: E402
from app.schemas import ConfidenceBand  # noqa: E402

SAMPLE_ZIP = ROOT / "data" / "Uebungsdaten_Muster_Verpackungen.zip"
SESSIONS = BACKEND / "data" / "sessions"
APP_DIR = BACKEND / "app"

EXPECTED_CATEGORIES = {
    "segregation_of_duties",
    "misclassification",
    "cutoff_timing",
    "threshold_structuring",
    "near_duplicate_entities",
    "unsupported_transaction",
}

# Sealed-dossier entities must never appear as hardcoded lists in app/ (anti-bias).
FORBIDDEN_APP_PATTERNS = [
    r"\b209101\b",
    r"\bMV-U05\b",
    r"UEBUNG_GROUND-TRUTH_SEALED",
]


def _grep_app_for_forbidden() -> list[str]:
    hits: list[str] = []
    for path in APP_DIR.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".py", ".yaml", ".yml", ".json", ".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pat in FORBIDDEN_APP_PATTERNS:
            if re.search(pat, text):
                hits.append(f"{path.relative_to(BACKEND)}: matched {pat}")
    return hits


def main() -> int:
    if not SAMPLE_ZIP.is_file():
        print(f"MISSING sample zip: {SAMPLE_ZIP}", file=sys.stderr)
        return 1

    forbidden = _grep_app_for_forbidden()
    if forbidden:
        print("FORBIDDEN sealed-entity references in app/:", file=sys.stderr)
        for h in forbidden:
            print(f"  {h}", file=sys.stderr)
        return 1
    print("anti_bias_grep=clean")

    parse = load_dossier(SAMPLE_ZIP, SESSIONS, session_id="smoke_phase3")
    findings = run_detectors(parse)
    print(f"findings={len(findings)}")

    if not findings:
        print("ERROR: expected at least one finding", file=sys.stderr)
        return 1

    bands = Counter(f.band.value for f in findings)
    cats = Counter(c for f in findings for c in f.categories)
    print(f"bands={dict(bands)}")
    print(f"categories={dict(cats)}")

    if ConfidenceBand.skip.value in bands:
        print("ERROR: skip-band findings must be filtered", file=sys.stderr)
        return 1

    unknown = set(cats) - EXPECTED_CATEGORIES
    if unknown:
        print(f"ERROR: unexpected categories {unknown}", file=sys.stderr)
        return 1

    if not (EXPECTED_CATEGORIES & set(cats)):
        print("ERROR: no known detector categories fired", file=sys.stderr)
        return 1

    confidences = [f.confidence for f in findings]
    if confidences != sorted(confidences, reverse=True):
        print(f"ERROR: findings not sorted by confidence: {confidences[:10]}", file=sys.stderr)
        return 1

    # Spot-check: citations point at real duckdb tables or document paths
    extract = parse.extract_dir
    checked = 0
    for finding in findings[:8]:
        for cite in finding.citations:
            checked += 1
            if cite.file.startswith("duckdb:"):
                table = cite.file.removeprefix("duckdb:")
                if table not in parse.table_counts:
                    print(f"ERROR: citation table missing: {table}", file=sys.stderr)
                    return 1
            else:
                path = extract / cite.file
                if not path.is_file():
                    # Stage 2 docs are relative to dossier root
                    print(f"ERROR: citation file missing: {cite.file}", file=sys.stderr)
                    return 1
            if not cite.quote.strip():
                print(f"ERROR: empty citation quote on {finding.id}", file=sys.stderr)
                return 1

    print(f"citations_spot_checked={checked}")
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
