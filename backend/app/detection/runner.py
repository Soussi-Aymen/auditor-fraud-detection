"""Run all detectors → Stage 2 → score → filter skip band."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb

from app.config import load_detector_config
from app.detection.citations import enrich_citations
from app.detection.detectors import run_all_detectors
from app.detection.scoring import (
    band_for_confidence,
    compute_confidence,
    filter_skip_band,
)
from app.detection.stage2 import corroborate
from app.parsing.documents import DocumentChunk
from app.parsing.pipeline import ParseResult
from app.schemas import Citation, Finding, FindingStatus


def _finding_id(category: str, title: str, citations: list[Citation]) -> str:
    raw = "|".join(
        [category, title] + [f"{c.file}:{c.locator}:{c.quote[:80]}" for c in citations[:2]]
    )
    return f"{category[:3]}-{hashlib.sha1(raw.encode()).hexdigest()[:10]}"


def run_detectors(
    parse: ParseResult,
    cfg: dict[str, Any] | None = None,
) -> list[Finding]:
    """
    Execute config-driven detectors against a parsed DuckDB session.

    Confidence = clamp(0..100, base + statistical_strength + stage2_delta + multi_category_boost).
    Skip-band findings are removed before return.
    """
    cfg = cfg or load_detector_config()
    multi_boost_value = float(cfg.get("multi_category_boost", 8))

    conn = duckdb.connect(str(parse.db_path), read_only=True)
    try:
        hits = run_all_detectors(conn, cfg)

        # Multi-category: entity keys that appear under 2+ categories get a boost later
        entity_categories: dict[str, set[str]] = defaultdict(set)
        for hit in hits:
            for key in hit.entity_keys:
                entity_categories[key].add(hit.category)

        findings: list[Finding] = []
        for hit in hits:
            stage = corroborate(
                conn,
                parse.document_chunks,
                hit.search_tokens,
                cfg=cfg,
                expects_document=hit.expects_document,
                citation_start_n=len(hit.citations) + 1,
            )
            citations = list(hit.citations) + stage.citations
            # renumber
            for i, c in enumerate(citations, start=1):
                c.n = i

            multi = 0.0
            if any(len(entity_categories[k]) >= 2 for k in hit.entity_keys):
                multi = multi_boost_value

            confidence = compute_confidence(
                base=hit.base,
                statistical_strength=hit.statistical_strength,
                stage2_delta=stage.delta,
                multi_category_boost=multi,
            )
            band = band_for_confidence(confidence, cfg)
            findings.append(
                Finding(
                    id=_finding_id(hit.category, hit.title, citations),
                    title=hit.title,
                    summary=hit.summary,
                    confidence=confidence,
                    band=band,
                    categories=[hit.category],
                    citations=citations,
                    status=FindingStatus.open,
                )
            )
    finally:
        conn.close()

    findings = filter_skip_band(findings)
    findings = sorted(findings, key=lambda f: f.confidence, reverse=True)
    return enrich_citations(parse, findings)


def run_detectors_on_db(
    db_path: Path,
    document_chunks: list[DocumentChunk] | None = None,
    cfg: dict[str, Any] | None = None,
) -> list[Finding]:
    """Test helper when a ParseResult is not available."""
    parse = ParseResult(
        session_id="adhoc",
        db_path=db_path,
        extract_dir=db_path.parent,
        document_chunks=document_chunks or [],
    )
    return run_detectors(parse, cfg=cfg)
