"""Shared types and DuckDB table helpers for detectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import duckdb

from app.schemas import Citation


@dataclass
class DetectorHit:
    """Pre-score hit from a category detector."""

    category: str
    title: str
    summary: str
    base: float
    statistical_strength: float
    citations: list[Citation]
    # Tokens used by Stage 2 document lookup (ids, names, beleg numbers, amounts)
    search_tokens: list[str] = field(default_factory=list)
    # Entity keys for multi-category boost (e.g. vendor:200062)
    entity_keys: list[str] = field(default_factory=list)
    expects_document: bool = False


def list_tables(conn: duckdb.DuckDBPyConnection) -> list[str]:
    rows = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
        """
    ).fetchall()
    return [str(r[0]) for r in rows]


def tables_matching(conn: duckdb.DuckDBPyConnection, patterns: list[str]) -> list[str]:
    pats = [p.lower() for p in patterns]
    return [t for t in list_tables(conn) if any(p in t.lower() for p in pats)]


def first_table(conn: duckdb.DuckDBPyConnection, patterns: list[str]) -> str | None:
    matched = tables_matching(conn, patterns)
    return matched[0] if matched else None


def table_columns(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    rows = conn.execute(f'DESCRIBE "{table}"').fetchall()
    return {str(r[0]) for r in rows}


def has_columns(conn: duckdb.DuckDBPyConnection, table: str, required: set[str]) -> bool:
    return required.issubset(table_columns(conn, table))


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def cfg_tables(cfg: dict[str, Any], role: str) -> list[str]:
    tables = cfg.get("tables") or {}
    raw = tables.get(role) or []
    return [str(x) for x in raw]
