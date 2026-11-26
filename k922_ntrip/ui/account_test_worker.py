"""Background Qt worker for the CORS account probe."""

from __future__ import annotations

import socket
import ssl
import threading

from PySide6.QtCore import QThread, Signal

from ..account_test import AccountTestProgress, AccountTestResult, verify_account
from ..config import ClientConfig
from ..protocol import format_tls_error


class AccountTestWorker(QThread):
    progress_changed = Signal(object)

    def __init__(self, config: ClientConfig, gga_sentence: bytes, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.gga_sentence = gga_sentence
        self.result = AccountTestResult(False, 0, "账号测试尚未完成")
        self.progress = AccountTestProgress(False, 0, 0, 0.0)
        self._cancel_event = threading.Event()
        self._socket_lock = threading.Lock()
        self._active_socket: socket.socket | None = None

    def run(self) -> None:
        try:
            self.result = verify_account(
                config=self.config,
                gga_sentence=self.gga_sentence,
                cancel_event=self._cancel_event,
                on_socket=self._set_active_socket,
                on_progress=self._publish_progress,
                continuous=True,
            )
        except Exception as exc:
            if self._cancel_event.is_set():
                progress = self.progress
                if progress.authenticated:
                    self.result = AccountTestResult(
                        authenticated=True,
                        bytes_received=progress.bytes_received,
                        message=(
                            f"持续测试已停止：运行 {progress.duration_seconds:.1f} 秒，"
                            f"发送合成 GGA {progress.gga_sent_count} 次，"
                            f"共收到 {progress.bytes_received} 字节。"
                        ),
                        data_preview=progress.data_preview,
                        rtcm_frames=progress.rtcm_frames,
                        gga_sent_count=progress.gga_sent_count,
                        duration_seconds=progress.duration_seconds,
                        rtcm_confirmed=progress.rtcm_confirmed,
                        last_gga=progress.last_gga,
                        stopped=True,
                    )
                    return
                message = "账号测试已取消。"
            elif isinstance(exc, ssl.SSLError):
                message = f"账号测试失败：{format_tls_error(exc)}"
            else:
                message = f"账号测试失败：{exc}"
            self.result = AccountTestResult(False, 0, message, stopped=self._cancel_event.is_set())

    def _publish_progress(self, progress: AccountTestProgress) -> None:
        self.progress = progress
        self.progress_changed.emit(progress)

    def request_cancel(self) -> None:
        self._cancel_event.set()
        with self._socket_lock:
            active_socket = self._active_socket
        if active_socket is not None:
            try:
                active_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                active_socket.close()
            except OSError:
                pass

    def _set_active_socket(self, active_socket: socket.socket | None) -> None:
        with self._socket_lock:
            self._active_socket = active_socket
