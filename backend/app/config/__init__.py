from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_CONFIG_DIR = Path(__file__).resolve().parent


def load_column_aliases() -> dict[str, str]:
    path = _CONFIG_DIR / "aliases.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("aliases") or {}
    return {str(k): str(v) for k, v in raw.items()}


def load_detector_config() -> dict[str, Any]:
    path = _CONFIG_DIR / "detectors.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("detectors.yaml must be a mapping")
    return data


def apply_aliases(columns: list[str], aliases: dict[str, str]) -> list[str]:
    """Rename columns to canonical names when an alias matches (case-sensitive first, then upper)."""
    upper_map = {k.upper(): v for k, v in aliases.items()}
    result: list[str] = []
    used: set[str] = set()
    for col in columns:
        canonical = aliases.get(col) or upper_map.get(col.upper())
        if canonical and canonical not in used:
            result.append(canonical)
            used.add(canonical)
        else:
            # Keep original if collision on canonical
            name = col
            if name in used:
                name = f"{col}_raw"
            result.append(name)
            used.add(name)
    return result

