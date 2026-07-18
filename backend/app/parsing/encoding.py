"""Decode German dossier text files (GDPdU often CP1252, not UTF-8)."""

from __future__ import annotations

from pathlib import Path

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def decode_bytes(raw: bytes) -> str:
    """Prefer UTF-8; fall back to CP1252/Latin-1 for classic GDPdU exports."""
    for enc in _ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        # Reject UTF-8 decodes that are mostly replacement garbage from wrong encoding
        if enc.startswith("utf-8") and "\ufffd" in text:
            continue
        return text
    return raw.decode("cp1252", errors="replace")


def read_text_file(path: Path) -> str:
    return decode_bytes(path.read_bytes())


def pandas_encoding_for(path: Path) -> str:
    """
    Pick an encoding for pandas.read_csv.

    Require the *entire* file to decode as UTF-8; otherwise use CP1252
    (common for German GDPdU TXT exports with umlauts).
    """
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "cp1252"
