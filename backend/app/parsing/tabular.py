"""CSV and XLSX loaders for Begleitdokumente-style files."""

from __future__ import annotations

import csv
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


def _strip_outer_quotes(value: object) -> object:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return value


def _is_junk_path(path: Path, root: Path) -> bool:
    parts_l = {p.lower() for p in path.relative_to(root).parts}
    if "__macosx" in parts_l:
        return True
    name = path.name
    return name.startswith("._") or name == ".DS_Store"


def _read_csv(path: Path) -> pd.DataFrame:
    enc = pandas_encoding_for(path)
    common = dict(dtype=str, encoding=enc, encoding_errors="strict", engine="python")

    def _try(sep: str, **extra: object) -> pd.DataFrame:
        return pd.read_csv(path, sep=sep, **common, **extra)

    # Prefer semicolon (DE); fall back to comma if single column
    try:
        df = _try(";")
    except (pd.errors.ParserError, csv.Error):
        df = _try(";", quoting=csv.QUOTE_NONE)
        df = df.map(_strip_outer_quotes)

    if df.shape[1] == 1:
        try:
            df = _try(",")
        except (pd.errors.ParserError, csv.Error):
            df = _try(",", quoting=csv.QUOTE_NONE)
            df = df.map(_strip_outer_quotes)
    return df


def load_csv_tables(
    root: Path, aliases: dict[str, str]
) -> tuple[dict[str, pd.DataFrame], dict[str, "TableSource"]]:
    from app.parsing.sources import TableSource

    frames: dict[str, pd.DataFrame] = {}
    sources: dict[str, TableSource] = {}
    for path in sorted(root.rglob("*.csv")):
        if _is_junk_path(path, root):
            continue
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
        if path.name.startswith("~$") or _is_junk_path(path, root):
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
            sources[key] = TableSource(path=rel, has_header=True)
    return frames, sources
