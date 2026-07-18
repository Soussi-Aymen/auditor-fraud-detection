from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


def extract_zip(zip_path: Path, dest_dir: Path) -> Path:
    """Extract zip into dest_dir. Returns root folder that contains data files."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)

    # Prefer a single top-level directory if the archive has one
    children = [p for p in dest_dir.iterdir() if not p.name.startswith(".")]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return dest_dir


def clear_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
