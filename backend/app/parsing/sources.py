"""Map DuckDB table names back to dossier source files for citation deep-links."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TableSource:
    """Where a DuckDB table was loaded from."""

    path: str  # relative to dossier root
    has_header: bool = False


def find_line(
    file_path: Path,
    needles: list[str],
    *,
    max_scan_bytes: int = 8_000_000,
) -> int | None:
    """
    Return 1-based line number where all non-empty needles appear,
    else first line matching any needle, else None.
    """
    if not file_path.is_file():
        return None
    cleaned = [n.strip() for n in needles if n and str(n).strip()]
    cleaned = [n for n in cleaned if len(n) >= 2]
    if not cleaned:
        return None
    try:
        raw = file_path.read_bytes()[:max_scan_bytes]
        text = raw.decode("utf-8", errors="replace")
    except OSError:
        return None

    lines = text.splitlines()
    # Prefer line containing every needle (best pinpoint)
    for i, line in enumerate(lines, start=1):
        if all(n in line for n in cleaned):
            return i
    # Fall back: strongest single needle (longest first)
    for n in sorted(cleaned, key=len, reverse=True):
        for i, line in enumerate(lines, start=1):
            if n in line:
                return i
    return None


def needles_from_locator_quote(locator: str, quote: str) -> list[str]:
    """Extract searchable tokens from citation locator/quote."""
    needles: list[str] = []
    for part in (locator or "").split(";"):
        part = part.strip()
        if "=" in part:
            _, _, val = part.partition("=")
            for piece in val.split(","):
                piece = piece.strip()
                if piece and piece.lower() not in {"null", "none"}:
                    needles.append(piece)
        elif part:
            needles.append(part)
    # Quote often has "key=value" fragments
    for token in (quote or "").replace(";", " ").split():
        token = token.strip(" ,;")
        if "=" in token:
            token = token.split("=", 1)[1]
        if len(token) >= 3 and not token.endswith("%"):
            needles.append(token)
    # Dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for n in needles:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out[:12]
