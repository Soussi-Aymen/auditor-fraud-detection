"""CSV and XLSX loaders for Begleitdokumente-style files."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from app.config import apply_aliases
from app.parsing.encoding import pandas_encoding_for
from app.parsing.normalize import normalize_dataframe


def _safe_name(relative: str) -> str:
    stem = Path(relative).stem.lower()
    stem = stem.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9_]+", "_", stem).strip("_")


def _read_csv(path: Path) -> pd.DataFrame:
    enc = pandas_encoding_for(path)
    # Prefer semicolon (DE); fall back to comma if single column
    df = pd.read_csv(
        path,
        sep=";",
        dtype=str,
        encoding=enc,
        encoding_errors="strict",
        engine="python",
    )
    if df.shape[1] == 1:
        df = pd.read_csv(
            path,
            sep=",",
            dtype=str,
            encoding=enc,
            encoding_errors="strict",
            engine="python",
        )
    return df


def load_csv_tables(
    root: Path, aliases: dict[str, str]
) -> tuple[dict[str, pd.DataFrame], dict[str, "TableSource"]]:
    from app.parsing.sources import TableSource

    frames: dict[str, pd.DataFrame] = {}
    sources: dict[str, TableSource] = {}
    for path in sorted(root.rglob("*.csv")):
        rel = str(path.relative_to(root))
        df = _read_csv(path)
        df.columns = apply_aliases([str(c) for c in df.columns], aliases)
        key = f"csv_{_safe_name(rel)}"
        frames[key] = normalize_dataframe(df)
        sources[key] = TableSource(path=rel, has_header=True)
    return frames, sources


def load_xlsx_tables(
    root: Path, aliases: dict[str, str]
) -> tuple[dict[str, pd.DataFrame], dict[str, "TableSource"]]:
    from app.parsing.sources import TableSource

    frames: dict[str, pd.DataFrame] = {}
    sources: dict[str, TableSource] = {}
    for path in sorted(root.rglob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        rel = str(path.relative_to(root))
        base = _safe_name(rel)
        xl = pd.ExcelFile(path, engine="openpyxl")
        for sheet in xl.sheet_names:
            df = xl.parse(sheet, dtype=str)
            df.columns = apply_aliases([str(c) for c in df.columns], aliases)
            sheet_key = re.sub(r"[^a-z0-9_]+", "_", sheet.lower()).strip("_")
            key = f"xlsx_{base}" if len(xl.sheet_names) == 1 else f"xlsx_{base}__{sheet_key}"
            frames[key] = normalize_dataframe(df)
            # Point at workbook; sheet noted in path fragment for display
            sources[key] = TableSource(path=rel, has_header=True)
    return frames, sources
