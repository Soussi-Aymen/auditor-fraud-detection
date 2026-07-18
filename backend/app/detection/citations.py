"""Enrich citations with dossier source paths and line numbers (auditor deep-links)."""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

from app.parsing.pipeline import ParseResult
from app.parsing.sources import TableSource, find_line, needles_from_locator_quote
from app.schemas import Citation, Finding


def _load_sources_from_db(db_path: Path) -> dict[str, TableSource]:
    out: dict[str, TableSource] = {}
    try:
        conn = duckdb.connect(str(db_path), read_only=True)
        try:
            rows = conn.execute(
                "SELECT table_name, source_path, has_header FROM table_sources"
            ).fetchall()
            for name, path, has_header in rows:
                out[str(name)] = TableSource(path=str(path), has_header=bool(has_header))
        finally:
            conn.close()
    except duckdb.Error:
        pass
    return out


def enrich_citations(parse: ParseResult, findings: list[Finding]) -> list[Finding]:
    sources = dict(parse.table_sources) or _load_sources_from_db(parse.db_path)
    root = parse.extract_dir

    for finding in findings:
        for cite in finding.citations:
            _enrich_one(cite, sources, root)
    return findings


def _enrich_one(
    cite: Citation,
    sources: dict[str, TableSource],
    root: Path,
) -> None:
    file_ref = cite.file or ""

    # Already a dossier-relative document path (Stage 2 PDF/DOCX)
    if not file_ref.startswith("duckdb:"):
        cite.source_path = file_ref
        page_m = re.match(r"page:(\d+)", cite.locator or "")
        para_m = re.match(r"para:(\d+)", cite.locator or "")
        if page_m:
            cite.detail = f"PDF page {page_m.group(1)}"
            cite.line = int(page_m.group(1))  # used as focus index in extract view
        elif para_m:
            cite.detail = f"DOCX paragraph {para_m.group(1)}"
            cite.line = int(para_m.group(1))
        else:
            cite.detail = cite.locator or None
        # Try to find quote in extracted text file isn't raw PDF — leave line as locator index
        return

    table = file_ref.removeprefix("duckdb:")
    meta = sources.get(table)
    if meta is None:
        cite.detail = f"DuckDB table `{table}` (source file mapping unavailable)"
        return

    cite.source_path = meta.path
    needles = needles_from_locator_quote(cite.locator, cite.quote)
    path = root / meta.path
    line = find_line(path, needles) if path.suffix.lower() in {".txt", ".csv", ".tsv"} else None
    cite.line = line

    bits = [f"Source file: {meta.path}"]
    if line is not None:
        bits.append(f"line {line}")
    if cite.locator:
        bits.append(cite.locator)
    cite.detail = " · ".join(bits)
    # Keep human locator readable
    if line is not None and "line=" not in (cite.locator or ""):
        cite.locator = f"{cite.locator};line={line}" if cite.locator else f"line={line}"
