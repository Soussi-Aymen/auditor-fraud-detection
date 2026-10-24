"""German number/date normalization shared by tabular loaders."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import pandas as pd

_DATE_FORMATS = (
    "%d.%m.%Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d.%m.%y",
)


def parse_german_number(value: Any) -> float | None:
    """Parse DE-style numbers (1.234,56 / -6940,00) to float. Empty → None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    text = text.replace("\u00a0", "").replace(" ", "")
    text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_german_date(value: Any) -> datetime | None:
    """Parse common DE/ISO date strings to datetime (date precision)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    text = str(value).strip()
    if not text:
        return None
    # Strip time portion if present (dd.mm.yyyy HH:MM:SS)
    text = re.split(r"\s+", text, maxsplit=1)[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def looks_like_amount_column(name: str) -> bool:
    upper = name.upper()
    return any(
        token in upper
        for token in (
            "BETRAG",
            "AMOUNT",
            "WERT",
            "SUMME",
            "LIMIT",
            "AUSNUTZUNG",
        )
    )


def looks_like_date_column(name: str) -> bool:
    upper = name.upper()
    return any(
        token in upper
        for token in (
            "DATUM",
            "DATE",
            "WERTSTELLUNG",
        )
    ) and "ZEIT" not in upper


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce obvious amount/date columns; leave others as strings trimmed."""
    out = df.copy()
    for col in out.columns:
        name = str(col)
        if looks_like_amount_column(name):
            out[col] = out[col].map(parse_german_number)
        elif looks_like_date_column(name):
            out[col] = out[col].map(parse_german_date)
        else:
            out[col] = out[col].map(
                lambda v: None
                if v is None or (isinstance(v, float) and pd.isna(v))
                else str(v).strip()
            )
    return out
