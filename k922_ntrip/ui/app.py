"""Qt application startup."""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .resources import asset_path


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("K922 NTRIP Client")
    app.setOrganizationName("GNSS Tools")
    app.setWindowIcon(QIcon(str(asset_path("k922_ntrip.ico"))))
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()
