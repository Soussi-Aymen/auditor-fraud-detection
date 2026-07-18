"""Stage 2: corroborate detector hits against PDF/DOCX (and tabular) text cache."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from app.parsing.documents import DocumentChunk
from app.schemas import Citation


@dataclass
class Stage2Result:
    delta: float
    citations: list[Citation]


def _normalize_token(token: str) -> str:
    return " ".join(str(token).strip().lower().split())


def corroborate(
    conn: duckdb.DuckDBPyConnection,
    document_chunks: list[DocumentChunk],
    search_tokens: list[str],
    *,
    cfg: dict[str, Any],
    expects_document: bool,
    citation_start_n: int,
) -> Stage2Result:
    """
    Search doc_chunks (+ DuckDB doc_chunks table if present) for any search token.

    hit  → +hit_delta and citation(s)
    miss → miss_delta, or expected_miss_delta when the detector expected a doc
    """
    stage_cfg = cfg.get("stage2") or {}
    hit_delta = float(stage_cfg.get("hit_delta", 12))
    miss_delta = float(stage_cfg.get("miss_delta", -8))
    expected_miss = float(stage_cfg.get("expected_miss_delta", 10))
    max_quote = int(stage_cfg.get("max_quote_chars", 160))

    tokens = [_normalize_token(t) for t in search_tokens if t and str(t).strip()]
    tokens = [t for t in tokens if len(t) >= 3]
    if not tokens:
        return Stage2Result(delta=0.0, citations=[])

    # Prefer in-memory chunks from parse; fall back to DB table.
    chunks = document_chunks
    if not chunks:
        try:
            rows = conn.execute(
                "SELECT source_path, locator, text FROM doc_chunks"
            ).fetchall()
            chunks = [
                DocumentChunk(source_path=str(r[0]), locator=str(r[1]), text=str(r[2] or ""))
                for r in rows
            ]
        except duckdb.Error:
            chunks = []

    matches: list[Citation] = []
    n = citation_start_n
    seen: set[tuple[str, str]] = set()
    for chunk in chunks:
        text_l = chunk.text.lower()
        if not any(t in text_l for t in tokens):
            continue
        key = (chunk.source_path, chunk.locator)
        if key in seen:
            continue
        seen.add(key)
        quote = chunk.text.strip().replace("\n", " ")
        if len(quote) > max_quote:
            quote = quote[: max_quote - 1] + "…"
        matches.append(
            Citation(n=n, file=chunk.source_path, locator=chunk.locator, quote=quote)
        )
        n += 1
        if len(matches) >= 3:
            break

    if matches:
        return Stage2Result(delta=hit_delta, citations=matches)
    if expects_document:
        return Stage2Result(delta=expected_miss, citations=[])
    return Stage2Result(delta=miss_delta, citations=[])
