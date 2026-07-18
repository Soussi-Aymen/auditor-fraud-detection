"""Orchestrate zip → tables + document cache → DuckDB."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.config import load_column_aliases
from app.parsing.documents import DocumentChunk, extract_documents
from app.parsing.gdpdu import load_gdpdu_tables
from app.parsing.sources import TableSource
from app.parsing.tabular import load_csv_tables, load_xlsx_tables
from app.parsing.zip_extract import clear_dir, extract_zip
from app.storage.duckdb_session import DuckDBSession


@dataclass
class ParseResult:
    session_id: str
    db_path: Path
    extract_dir: Path
    table_counts: dict[str, int] = field(default_factory=dict)
    document_chunks: list[DocumentChunk] = field(default_factory=list)
    table_sources: dict[str, TableSource] = field(default_factory=dict)


def load_dossier(
    zip_path: Path,
    sessions_root: Path,
    session_id: str | None = None,
) -> ParseResult:
    """
    Deterministic load of a financial-document zip into a DuckDB session.

    Does not read ground-truth files. No fraud detection.
    """
    zip_path = zip_path.resolve()
    if not zip_path.is_file():
        raise FileNotFoundError(zip_path)

    sid = session_id or uuid.uuid4().hex[:12]
    session_dir = sessions_root / sid
    extract_dir = session_dir / "extract"
    clear_dir(session_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    dossier_root = extract_zip(zip_path, extract_dir)
    aliases = load_column_aliases()

    frames: dict = {}
    sources: dict[str, TableSource] = {}
    gdpdu_frames, gdpdu_sources = load_gdpdu_tables(dossier_root, aliases)
    frames.update(gdpdu_frames)
    sources.update(gdpdu_sources)
    csv_frames, csv_sources = load_csv_tables(dossier_root, aliases)
    frames.update(csv_frames)
    sources.update(csv_sources)
    xlsx_frames, xlsx_sources = load_xlsx_tables(dossier_root, aliases)
    frames.update(xlsx_frames)
    sources.update(xlsx_sources)

    docs = extract_documents(dossier_root)

    db_path = session_dir / "session.duckdb"
    session = DuckDBSession(db_path)
    try:
        for name, df in frames.items():
            session.register_dataframe(name, df)
        session.store_documents(docs)
        session.store_table_sources(sources)
        counts = session.table_row_counts()
    finally:
        session.close()

    return ParseResult(
        session_id=sid,
        db_path=db_path,
        extract_dir=dossier_root,
        table_counts=counts,
        document_chunks=docs,
        table_sources=sources,
    )
