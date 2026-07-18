#!/usr/bin/env python3
"""
Offline eval against sealed GT — TEST ONLY.

Loads data/UEBUNG_GROUND-TRUTH_SEALED_Muster-Verpackungen.md solely in this script
to score detector outcomes. Never import this module from app/ runtime.

Scoring (aligned with sealed GT “Suggested scoring”):
  Top marks: F1 by *combining* sources + F2/F3 profit-overstatement pair
  Bonus: F4
  Penalty: accusing decoys D1–D7
  Rubric points: F1=40, F2=25, F3=25, F4=10, −5 per decoy warn (cap −30)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.detection import run_detectors  # noqa: E402
from app.parsing import load_dossier  # noqa: E402
from app.schemas import Finding  # noqa: E402

SAMPLE_ZIP = ROOT / "data" / "Uebungsdaten_Muster_Verpackungen.zip"
GT_PATH = ROOT / "data" / "UEBUNG_GROUND-TRUTH_SEALED_Muster-Verpackungen.md"
SESSIONS = BACKEND / "data" / "sessions"
APP_DIR = BACKEND / "app"

# Sealed IDs may appear ONLY in this test (and the GT file), never in app/.
FORBIDDEN_APP_PATTERNS = [
    r"\b209101\b",
    r"\bMV-U05\b",
    r"\b200007\b",
    r"Ratio Consulting",
    r"UEBUNG_GROUND-TRUTH_SEALED",
]


@dataclass
class CaseResult:
    case_id: str
    hit: bool
    detail: str


def _finding_blob(f: Finding) -> str:
    parts = [f.title, f.summary, *f.categories]
    for c in f.citations:
        parts.extend([c.file, c.locator, c.quote])
    return " ".join(parts)


def _grep_app_for_forbidden() -> list[str]:
    hits: list[str] = []
    for path in APP_DIR.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".py", ".yaml", ".yml", ".json", ".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pat in FORBIDDEN_APP_PATTERNS:
            if re.search(pat, text, flags=re.IGNORECASE):
                hits.append(f"{path.relative_to(BACKEND)}: matched {pat}")
    return hits


def _score_f1(findings: list[Finding]) -> CaseResult:
    """
    Fake vendor — GT top marks require *combining* sources:
    new vendor + no GR / unsupported + creator=approver (SoD).
    """
    sod = [
        f
        for f in findings
        if "segregation_of_duties" in f.categories
        and "209101" in _finding_blob(f)
        and re.search(r"neuanlage|creator|approver", _finding_blob(f), re.I)
    ]
    unsupported = [
        f
        for f in findings
        if "unsupported_transaction" in f.categories and "209101" in _finding_blob(f)
    ]
    if sod and unsupported:
        return CaseResult(
            "F1",
            True,
            f"combined sources: SoD+unsupported on shell vendor ({len(sod)}+{len(unsupported)})",
        )
    if sod and not unsupported:
        return CaseResult("F1", False, "SoD only — GT requires combining with unsupported/no-GR signals")
    if unsupported and not sod:
        return CaseResult("F1", False, "unsupported only — GT requires combining with SoD (creator=approver)")
    return CaseResult("F1", False, "no combined SoD+unsupported findings for shell-vendor pattern")



def _score_f2(findings: list[Finding]) -> CaseResult:
    """Repairs capitalised: misclassification with repair-like text."""
    repair_re = re.compile(r"repair|reparatur|instand|austausch|wartung|überhol|ueberhol", re.I)
    hits = [
        f
        for f in findings
        if "misclassification" in f.categories and repair_re.search(_finding_blob(f))
    ]
    if len(hits) >= 3:
        return CaseResult("F2", True, f"{len(hits)} repair-capitalisation findings")
    if hits:
        return CaseResult("F2", False, f"only {len(hits)} repair misclassification finding(s); need >=3")
    return CaseResult("F2", False, "no repair/misclassification findings")


def _score_f3(findings: list[Finding]) -> CaseResult:
    """Cutoff: service in Dec / invoice in next period."""
    hits = [f for f in findings if "cutoff_timing" in f.categories]
    if len(hits) >= 4:
        return CaseResult("F3", True, f"{len(hits)} cutoff_timing findings")
    if hits:
        return CaseResult("F3", False, f"only {len(hits)} cutoff finding(s); need >=4")
    return CaseResult("F3", False, "no cutoff_timing findings")


def _score_f4(findings: list[Finding]) -> CaseResult:
    """Split payments under approval threshold — cluster or near-10k structuring."""
    thr = [f for f in findings if "threshold_structuring" in f.categories]
    cluster = [
        f
        for f in thr
        if re.search(r"near-threshold payments same day|split", _finding_blob(f), re.I)
        or ("200007" in _finding_blob(f) and re.search(r"10000|10,000", _finding_blob(f)))
    ]
    near_10k = [
        f
        for f in thr
        if "200007" in _finding_blob(f)
        or re.search(r"under 10,?000|threshold=10000|below 10,?000", _finding_blob(f), re.I)
    ]
    if cluster:
        return CaseResult("F4", True, f"split-payment cluster ({len(cluster)} findings)")
    if near_10k:
        return CaseResult("F4", True, f"near-10k structuring referencing pattern ({len(near_10k)})")
    if thr:
        return CaseResult("F4", False, f"{len(thr)} threshold findings but no split-under-10k cluster")
    return CaseResult("F4", False, "no threshold_structuring findings")


def _decoy_warnings(findings: list[Finding]) -> list[str]:
    """Warn when findings look like accusing known-clean decoys (eval-only IDs)."""
    warnings: list[str] = []
    blobs = [(f, _finding_blob(f)) for f in findings]

    # D3: honest new vendor twin of F1 — should not be unsupported new-vendor hit
    for f, blob in blobs:
        if "209112" in blob and "unsupported_transaction" in f.categories:
            if re.search(r"new vendor paid|neuanlage", blob, re.I):
                warnings.append(
                    f"D3: unsupported new-vendor finding on decoy 209112 "
                    f"(conf={f.confidence:.0f}% id={f.id})"
                )

    # D2: similar names with different VAT + real GR — near-duplicate alone is soft;
    # flag if we accuse Nord Logistik / Nordlicht as fraud-like unsupported
    for f, blob in blobs:
        if re.search(r"Nord\s*Logistik|Nordlicht", blob, re.I):
            if "unsupported_transaction" in f.categories or (
                "near_duplicate_entities" in f.categories and f.confidence >= 70
            ):
                warnings.append(
                    f"D2: high-confidence finding on Nord/Nordlicht decoy "
                    f"({f.categories[0]} conf={f.confidence:.0f}%)"
                )

    # D1: large real machine capitalisation — misclassification on IA / 480k machine
    for f, blob in blobs:
        if "misclassification" in f.categories and re.search(
            r"480,?000|IA-2025-04|Investitionsantrag", blob, re.I
        ):
            warnings.append(f"D1: misclassification on legitimate capital investment ({f.id})")

    # D5: related-party Konzernumlage
    for f, blob in blobs:
        if "209113" in blob and f.confidence >= 60:
            warnings.append(
                f"D5: finding on related-party parent 209113 "
                f"({f.categories[0]} conf={f.confidence:.0f}%)"
            )

    # D7: invoice + credit note pair
    for f, blob in blobs:
        if re.search(r"AR502040|SG502041", blob) and f.confidence >= 60:
            warnings.append(f"D7: finding on revenue-neutral correction pair ({f.id})")

    return warnings


def run_eval(session_id: str = "eval_gt") -> int:
    if not SAMPLE_ZIP.is_file():
        print(f"MISSING sample zip: {SAMPLE_ZIP}", file=sys.stderr)
        return 1
    if not GT_PATH.is_file():
        print(f"MISSING sealed GT: {GT_PATH}", file=sys.stderr)
        return 1

    # Prove GT is readable here (eval-only) and summarize scheme labels present
    gt_text = GT_PATH.read_text(encoding="utf-8")
    for label in ("F1", "F2", "F3", "F4", "D1", "D3"):
        if label not in gt_text:
            print(f"ERROR: sealed GT missing expected label {label}", file=sys.stderr)
            return 1
    print(f"gt_loaded={GT_PATH.name} bytes={len(gt_text)}")

    forbidden = _grep_app_for_forbidden()
    if forbidden:
        print("FAIL anti_bias: sealed references in app/:", file=sys.stderr)
        for h in forbidden:
            print(f"  {h}", file=sys.stderr)
        return 1
    print("anti_bias_grep=clean")

    parse = load_dossier(SAMPLE_ZIP, SESSIONS, session_id=session_id)
    findings = run_detectors(parse)
    print(f"findings={len(findings)}")

    results = [
        _score_f1(findings),
        _score_f2(findings),
        _score_f3(findings),
        _score_f4(findings),
    ]
    for r in results:
        status = "HIT" if r.hit else "MISS"
        print(f"  {r.case_id} {status}: {r.detail}")

    decoy_warns = _decoy_warnings(findings)
    fp_rate = len(decoy_warns) / max(1, len(findings))
    print(f"decoy_warnings={len(decoy_warns)} decoy_fp_rate={fp_rate:.3f}")
    for w in decoy_warns:
        print(f"  WARN {w}")

    core = [r for r in results if r.case_id in {"F1", "F2", "F3"}]
    bonus = next(r for r in results if r.case_id == "F4")
    core_ok = all(r.hit for r in core)

    # GT suggested scoring (eval-only):
    # Top marks = F1 (combined) + F2/F3; Bonus = F4; Penalty = decoys D1–D7.
    points = 0
    points += 40 if next(r for r in results if r.case_id == "F1").hit else 0
    points += 25 if next(r for r in results if r.case_id == "F2").hit else 0
    points += 25 if next(r for r in results if r.case_id == "F3").hit else 0
    points += 10 if bonus.hit else 0
    decoy_penalty = min(30, 5 * len(decoy_warns))
    points = max(0, points - decoy_penalty)
    print(
        f"rubric_points={points}/100 "
        f"(F1=40 F2=25 F3=25 F4_bonus=10 decoy_penalty=-{decoy_penalty})"
    )

    summary = {
        "core_f1_f3": "PASS" if core_ok else "FAIL",
        "f4_bonus": "HIT" if bonus.hit else "MISS",
        "decoy_warnings": len(decoy_warns),
        "decoy_penalty": decoy_penalty,
        "rubric_points": points,
        "findings": len(findings),
    }
    print(f"summary={json.dumps(summary)}")

    if not core_ok:
        print("EVAL_FAIL: core F1–F3 incomplete (GT top-marks pair)", file=sys.stderr)
        return 1
    if not bonus.hit:
        print("EVAL_WARN: F4 (bonus) missed — reported, not failing core")
    if decoy_warns:
        print("EVAL_WARN: decoy-like false positives — GT penalty applied to rubric_points")
    print("EVAL_OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Eval detectors against sealed GT (test-only)")
    parser.add_argument("--session-id", default="eval_gt")
    args = parser.parse_args()
    return run_eval(session_id=args.session_id)


if __name__ == "__main__":
    raise SystemExit(main())
