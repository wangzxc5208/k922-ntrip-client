"""Resolve packaged UI assets in source and PyInstaller builds."""

from __future__ import annotations

import sys
from pathlib import Path


def asset_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parents[2]
    return base_path / "assets" / name
