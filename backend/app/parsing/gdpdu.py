"""GDPdU index.xml → semicolon TXT table loaders."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

from app.config import apply_aliases
from app.parsing.encoding import pandas_encoding_for
from app.parsing.normalize import normalize_dataframe


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def parse_index_xml(index_path: Path) -> list[dict[str, object]]:
    """Return table specs: {name, url, columns}."""
    tree = ET.parse(index_path)
    root = tree.getroot()
    tables: list[dict[str, object]] = []
    for el in root.iter():
        if _local(el.tag) != "Table":
            continue
        name = None
        url = None
        columns: list[str] = []
        for child in el:
            tag = _local(child.tag)
            if tag == "Name" and child.text:
                name = child.text.strip()
            elif tag == "URL" and child.text:
                url = child.text.strip()
            elif tag == "VariableLength":
                for col_el in child:
                    if _local(col_el.tag) != "VariableColumn":
                        continue
                    for c in col_el:
                        if _local(c.tag) == "Name" and c.text:
                            columns.append(c.text.strip())
        if name and url and columns:
            tables.append({"name": name, "url": url, "columns": columns})
    return tables


def _safe_table_name(folder: str, table: str) -> str:
    raw = f"{folder}_{table}".lower()
    raw = raw.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")


def load_gdpdu_tables(
    root: Path,
    aliases: dict[str, str],
) -> tuple[dict[str, pd.DataFrame], dict[str, "TableSource"]]:
    """Load all GDPdU packages under root (folders with index.xml + TXT)."""
    from app.parsing.sources import TableSource

    frames: dict[str, pd.DataFrame] = {}
    sources: dict[str, TableSource] = {}
    for index_path in sorted(root.rglob("index.xml")):
        folder = index_path.parent.name
        for spec in parse_index_xml(index_path):
            url = str(spec["url"])
            columns = list(spec["columns"])  # type: ignore[arg-type]
            txt_path = index_path.parent / url
            if not txt_path.is_file():
                continue
            df = pd.read_csv(
                txt_path,
                sep=";",
                header=None,
                names=columns,
                dtype=str,
                quotechar='"',
                encoding=pandas_encoding_for(txt_path),
                encoding_errors="strict",
                engine="python",
            )
            # Drop empty trailing columns if row shorter — pandas already aligns
            renamed = apply_aliases(list(df.columns.astype(str)), aliases)
            df.columns = renamed
            df = normalize_dataframe(df)
            key = _safe_table_name(folder, str(spec["name"]))
            frames[key] = df
            sources[key] = TableSource(
                path=str(txt_path.relative_to(root)),
                has_header=False,
            )
    return frames, sources
