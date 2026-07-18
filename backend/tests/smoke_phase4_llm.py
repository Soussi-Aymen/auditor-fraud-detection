#!/usr/bin/env python3
"""Phase 4 smoke: LLM narration + offline fallback + anti-bias prompt/repo grep."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.config import load_detector_config  # noqa: E402
from app.detection import run_detectors  # noqa: E402
from app.llm import enrich_findings, policy_config_overrides  # noqa: E402
from app.llm.client import openai_enabled  # noqa: E402
from app.parsing import load_dossier  # noqa: E402
from app.schemas import Citation, Finding, ConfidenceBand, FindingStatus  # noqa: E402

SAMPLE_ZIP = ROOT / "data" / "Uebungsdaten_Muster_Verpackungen.zip"
SESSIONS = BACKEND / "data" / "sessions"
APP_DIR = BACKEND / "app"

FORBIDDEN_APP_PATTERNS = [
    r"\b209101\b",
    r"\bMV-U05\b",
    r"\bRatio Consulting\b",
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
            if re.search(pat, text, flags=re.IGNORECASE):
                hits.append(f"{path.relative_to(BACKEND)}: matched {pat}")
    return hits


def _assert_confidence_unchanged(before: Finding, after: Finding) -> None:
    if before.confidence != after.confidence or before.band != after.band:
        raise AssertionError("LLM must not change confidence or band")
    if before.categories != after.categories:
        raise AssertionError("LLM must not change categories")
    if before.id != after.id:
        raise AssertionError("finding id must remain stable")


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

    # Force offline path for deterministic fallback verification first.
    saved_key = os.environ.pop("OPENAI_API_KEY", None)
    try:
        stub = Finding(
            id="stub-1",
            title="Same user created and approved master-data change",
            summary="User X appears as creator and approver.",
            confidence=72.0,
            band=ConfidenceBand.high,
            categories=["segregation_of_duties"],
            citations=[
                Citation(
                    n=1,
                    file="duckdb:stammdaten",
                    locator="creator=X",
                    quote="creator=X; approver=X; field=Bankverbindung",
                )
            ],
            status=FindingStatus.open,
        )
        fb = enrich_findings([stub])[0]
        _assert_confidence_unchanged(stub, fb)
        if not fb.title or not fb.summary:
            print("ERROR: fallback narration empty", file=sys.stderr)
            return 1
        if not fb.title.startswith("Review:"):
            print(f"ERROR: expected Review: prefix in offline title, got {fb.title!r}", file=sys.stderr)
            return 1
        print(f"fallback_title={fb.title!r}")
        print(f"openai_enabled_without_key={openai_enabled()}")
        if openai_enabled():
            print("ERROR: expected openai disabled without key", file=sys.stderr)
            return 1

        parse = load_dossier(SAMPLE_ZIP, SESSIONS, session_id="smoke_phase4")
        cfg = policy_config_overrides(parse.document_chunks, load_detector_config())
        raw = run_detectors(parse, cfg=cfg)
        if not raw:
            print("ERROR: expected detectors to emit findings", file=sys.stderr)
            return 1
        enriched = enrich_findings(raw[:3], max_quote_chars=160)
        for before, after in zip(raw[:3], enriched, strict=True):
            _assert_confidence_unchanged(before, after)
            if not after.title.strip() or not after.summary.strip():
                print("ERROR: empty narrated fields", file=sys.stderr)
                return 1
            for c in after.citations:
                if len(c.quote) > 200:
                    print(f"ERROR: quote too long ({len(c.quote)})", file=sys.stderr)
                    return 1
        print(f"offline_enriched={len(enriched)}")
        print(f"sample_title={enriched[0].title!r}")
        print(f"sample_summary={enriched[0].summary[:180]!r}...")
    finally:
        if saved_key is not None:
            os.environ["OPENAI_API_KEY"] = saved_key

    # Optional live call when key present (does not fail the smoke if models unavailable).
    if os.environ.get("OPENAI_API_KEY", "").strip():
        print("openai_key=present — attempting live narrate on one finding")
        try:
            parse = load_dossier(SAMPLE_ZIP, SESSIONS, session_id="smoke_phase4_live")
            cfg = policy_config_overrides(parse.document_chunks, load_detector_config())
            raw = run_detectors(parse, cfg=cfg)
            one = enrich_findings(raw[:1], max_quote_chars=160)
            _assert_confidence_unchanged(raw[0], one[0])
            print(f"live_title={one[0].title!r}")
            print(f"live_summary={one[0].summary[:220]!r}...")
            print("live_narrate=ok")
        except Exception as exc:  # noqa: BLE001
            print(f"live_narrate=skipped ({exc})")
    else:
        print("openai_key=absent — live narrate skipped")

    print("phase4_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
