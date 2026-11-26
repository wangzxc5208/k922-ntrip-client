#!/usr/bin/env python3
"""Launch the K922 NTRIP desktop interface."""

import os
import sys
from pathlib import Path


# Keep these handles alive for the full process lifetime. PySide6's bundled Qt
# DLLs must be resolved from the frozen application's private directories,
# especially on machines that have another Qt installation on PATH.
_DLL_DIRECTORY_HANDLES = []


def _prepare_frozen_dll_search() -> None:
    if not getattr(sys, "frozen", False) or not hasattr(os, "add_dll_directory"):
        return

    bundle_root = Path(sys._MEIPASS)
    private_directories = (
        bundle_root / "PySide6",
        bundle_root / "shiboken6",
        bundle_root,
    )
    for directory in private_directories:
        if directory.is_dir():
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(directory)))
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")


_prepare_frozen_dll_search()

from k922_ntrip.ui.app import main


if __name__ == "__main__":
    raise SystemExit(main())
