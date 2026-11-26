from __future__ import annotations

import socket
import threading
import time

from k922_ntrip.rtcm import crc24q


def build_rtcm_frame(message_type: int = 1005, station_id: int = 42, extra_payload: bytes = b"\x00") -> bytes:
    """Build a small valid RTCM3 frame for local simulation tests."""
    header = ((message_type & 0x0FFF) << 12) | (station_id & 0x0FFF)
    payload = header.to_bytes(3, "big") + extra_payload
    frame_without_crc = bytes((0xD3, (len(payload) >> 8) & 0x03, len(payload) & 0xFF)) + payload
    return frame_without_crc + crc24q(frame_without_crc).to_bytes(3, "big")


class LocalResponseCaster:
    def __init__(
        self,
        response: bytes,
        *,
        stream_chunks: tuple[bytes, ...] = (),
        stream_interval: float = 0.0,
    ) -> None:
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(3)
        self.port = self.listener.getsockname()[1]
        self.response = response
        self.stream_chunks = stream_chunks
        self.stream_interval = stream_interval
        self.request = b""
        self.extra_data = b""
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        connection: socket.socket | None = None
        try:
            connection, _ = self.listener.accept()
            connection.settimeout(0.25)
            request = bytearray()
            while b"\r\n\r\n" not in request:
                chunk = connection.recv(4096)
                if not chunk:
                    raise ConnectionError("client closed before request headers")
                request.extend(chunk)
            self.request = bytes(request)
            connection.sendall(self.response)
            for chunk in self.stream_chunks:
                if self.stream_interval:
                    time.sleep(self.stream_interval)
                connection.sendall(chunk)
            received = bytearray()
            while True:
                chunk = connection.recv(1024)
                if not chunk:
                    break
                received.extend(chunk)
            self.extra_data = bytes(received)
        except socket.timeout:
            pass
        except BaseException as exc:
            self.error = exc
        finally:
            if connection is not None:
                connection.close()

    def close(self) -> None:
        self.listener.close()
        self._thread.join(timeout=2)
