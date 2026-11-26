"""Qt thread adapter for the UI-independent client service."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..config import ClientConfig
from ..service import NtripService, ServiceEvent


class ConnectionWorker(QThread):
    event_received = Signal(object)

    def __init__(self, config: ClientConfig, parent=None) -> None:
        super().__init__(parent)
        self._service = NtripService(config, self.event_received.emit)

    def run(self) -> None:
        self._service.run()

    def request_stop(self) -> None:
        self._service.request_stop()
