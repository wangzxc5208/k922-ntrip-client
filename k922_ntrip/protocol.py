"""NTRIP wire protocol helpers, independent of the UI framework."""

from __future__ import annotations

import base64
import errno
import re
import select
import socket
import ssl
import threading
import time
from concurrent.futures import Future
from typing import Callable

from .config import ClientConfig, ConfigError
from .nmea import parse_gga


MAX_RESPONSE_HEADERS = 64 * 1024
MAX_CHUNK_SIZE = 1024 * 1024
CONNECT_POLL_SECONDS = 0.5
# The system resolver cannot cancel an outstanding getaddrinfo on all platforms.
_DNS_SLOTS = threading.BoundedSemaphore(4)


class CasterRejectedError(ConnectionError):
    """The CORS caster rejected the request; retrying unchanged is not useful."""


def format_tls_error(error: ssl.SSLError) -> str:
    """Turn common TLS protocol mismatches into actionable NTRIP guidance."""
    if (
        getattr(error, "reason", None) == "WRONG_VERSION_NUMBER"
        or "WRONG_VERSION_NUMBER" in str(error)
    ):
        return (
            "TLS 握手失败：该端口返回的不是 TLS 数据。请取消勾选 TLS，"
            "或改用服务商明确提供的 TLS 专用端口。"
        )
    return f"TLS 连接失败：{error}"


class ChunkedDecoder:
    """Decode HTTP chunk framing while preserving the RTCM stream bytes."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._chunk_size: int | None = None
        self._reading_trailers = False
        self.finished = False

    def feed(self, data: bytes) -> bytes:
        if self.finished:
            if data:
                raise ConnectionError("CORS sent data after the final HTTP chunk")
            return b""
        self._buffer.extend(data)
        output = bytearray()

        while True:
            if self._reading_trailers:
                if self._buffer.startswith(b"\r\n"):
                    del self._buffer[:2]
                    if self._buffer:
                        raise ConnectionError("CORS sent data after the final HTTP chunk")
                    self.finished = True
                    break
                trailer_end = self._buffer.find(b"\r\n\r\n")
                if trailer_end > 8192:
                    raise ConnectionError("NTRIP chunk trailers exceed 8 KiB")
                if trailer_end < 0:
                    if len(self._buffer) > 8192:
                        raise ConnectionError("NTRIP chunk trailers exceed 8 KiB")
                    break
                del self._buffer[: trailer_end + 4]
                if self._buffer:
                    raise ConnectionError("CORS sent data after the final HTTP chunk")
                self.finished = True
                break

            if self._chunk_size is None:
                line_end = self._buffer.find(b"\r\n")
                if line_end > 8192:
                    raise ConnectionError("NTRIP chunk header exceeds 8 KiB")
                if line_end < 0:
                    if len(self._buffer) > 8192:
                        raise ConnectionError("NTRIP chunk header exceeds 8 KiB")
                    break
                size_field = bytes(self._buffer[:line_end]).split(b";", 1)[0].strip()
                if not re.fullmatch(rb"[0-9a-fA-F]+", size_field):
                    raise ConnectionError("Invalid chunk size in NTRIP response")
                self._chunk_size = int(size_field, 16)
                if self._chunk_size > MAX_CHUNK_SIZE:
                    raise ConnectionError("NTRIP chunk exceeds the 1 MiB safety limit")
                del self._buffer[: line_end + 2]

                if self._chunk_size == 0:
                    self._chunk_size = None
                    self._reading_trailers = True
                    continue

            size = self._chunk_size
            if size is None or len(self._buffer) < size + 2:
                break
            if self._buffer[size : size + 2] != b"\r\n":
                raise ConnectionError("Invalid NTRIP chunk terminator")
            output.extend(self._buffer[:size])
            del self._buffer[: size + 2]
            self._chunk_size = None

        return bytes(output)


class _ContentLengthDecoder:
    def __init__(self, length: int) -> None:
        self.remaining = length

    @property
    def finished(self) -> bool:
        return self.remaining == 0

    def feed(self, data: bytes) -> bytes:
        if len(data) > self.remaining:
            raise ConnectionError("收到的数据超过 CORS 声明的 Content-Length")
        self.remaining -= len(data)
        return data


BodyDecoder = ChunkedDecoder | _ContentLengthDecoder


def is_gga(line: bytes) -> bool:
    """Use the same fix validation for CORS uploads and the position display."""
    position = parse_gga(line)
    return position is not None and position.has_fix


def build_ntrip_request(
    config: ClientConfig,
    initial_gga: bytes | None = None,
    *,
    keep_alive: bool = False,
) -> bytes:
    config = ClientConfig.from_mapping(config.to_mapping())
    host = config.cors_host
    if any(ord(character) < 32 or ord(character) == 127 for character in host):
        raise ConfigError("CORS 主机包含非法控制字符")
    if any(character in config.mountpoint for character in "\r\n\\/"):
        raise ConfigError("挂载点不能包含换行符或路径分隔符")
    if config.username and not config.tls and not config.allow_insecure_auth:
        raise ConfigError("未启用 TLS 时必须确认明文账号传输风险")

    protocol_minor = "1" if config.ntrip_version == "2.0" else "0"
    authority_host = f"[{host}]" if ":" in host else host
    headers = [
        f"GET /{config.mountpoint} HTTP/1.{protocol_minor}",
        f"Host: {authority_host}:{config.cors_port}",
        "User-Agent: NTRIP K922Client/1.0",
        "Accept: */*",
        "Connection: keep-alive" if keep_alive else "Connection: close",
    ]
    if config.ntrip_version == "2.0":
        headers.insert(2, "Ntrip-Version: Ntrip/2.0")
        if initial_gga:
            gga_sentence = initial_gga.rstrip(b"\r\n")
            if b"\r" in gga_sentence or b"\n" in gga_sentence or not is_gga(gga_sentence):
                raise ConfigError("初始 GGA 报文格式无效")
            gga_header = gga_sentence.decode("ascii")
            headers.append(f"Ntrip-GGA: {gga_header}")
    if config.username:
        credentials = base64.b64encode(f"{config.username}:{config.password}".encode("utf-8"))
        headers.append(f"Authorization: Basic {credentials.decode('ascii')}")
    return ("\r\n".join(headers) + "\r\n\r\n").encode("ascii")


def read_ntrip_response(sock: socket.socket) -> tuple[bytes, bool, bool]:
    """Return initial payload, chunked status, and whether the caster used ICY."""
    payload, decoder, icy = read_caster_stream(sock)
    return payload, isinstance(decoder, ChunkedDecoder), icy


def read_caster_stream(sock: socket.socket) -> tuple[bytes, BodyDecoder | None, bool]:
    """Return response bytes and the decoder that tracks HTTP message completion."""
    timeout = sock.gettimeout()
    deadline = time.monotonic() + timeout if timeout is not None else None
    try:
        return _read_response_headers(sock, deadline)
    finally:
        if sock.fileno() >= 0:
            sock.settimeout(timeout)


def _read_response_headers(sock: socket.socket, deadline: float | None) -> tuple[bytes, BodyDecoder | None, bool]:
    received = bytearray()
    first_line_end = -1
    while len(received) < MAX_RESPONSE_HEADERS:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("等待 CORS 响应头超时")
            sock.settimeout(remaining)
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("CORS closed the connection before sending a response")
        received.extend(chunk)

        if first_line_end < 0:
            first_line_end = received.find(b"\r\n")
            if first_line_end < 0:
                continue
            if first_line_end + 2 > MAX_RESPONSE_HEADERS:
                raise ConnectionError("CORS response headers exceed 64 KiB")
            status_line = bytes(received[:first_line_end]).decode("latin-1", errors="replace")
            if status_line.upper().startswith("SOURCETABLE "):
                raise CasterRejectedError("CORS returned a source table; check the mountpoint and credentials")
            if status_line.upper().startswith("ICY "):
                parts = status_line.split()
                if len(parts) < 2 or parts[1] != "200":
                    raise CasterRejectedError(f"CORS rejected the request: {status_line}")
                return bytes(received[first_line_end + 2 :]), None, True

        header_end = received.find(b"\r\n\r\n")
        if header_end < 0:
            continue
        if header_end + 4 > MAX_RESPONSE_HEADERS:
            raise ConnectionError("CORS response headers exceed 64 KiB")
        header = bytes(received[:header_end]).decode("latin-1", errors="replace")
        status_line = header.split("\r\n", 1)[0]
        if status_line.upper().startswith("SOURCETABLE "):
            raise CasterRejectedError("CORS returned a source table; check the mountpoint and credentials")
        parts = status_line.split()
        if len(parts) < 2 or not parts[0].startswith("HTTP/"):
            raise ConnectionError(f"Unrecognized CORS response: {status_line}")
        try:
            status_code = int(parts[1])
        except ValueError as exc:
            raise ConnectionError(f"Unrecognized CORS response: {status_line}") from exc
        if status_code != 200:
            if 300 <= status_code < 400:
                raise CasterRejectedError(f"CORS 返回重定向（{status_code}），请核对服务商的主机和挂载点")
            if 400 <= status_code < 500 and status_code not in (408, 429):
                raise CasterRejectedError(f"CORS rejected the request: {status_line}")
            raise ConnectionError(f"CORS returned an unsuccessful response: {status_line}")

        header_lines = header.split("\r\n")[1:]
        headers: dict[str, list[str]] = {}
        for line in header_lines:
            name, separator, value = line.partition(":")
            if separator:
                headers.setdefault(name.lower(), []).append(value.strip().lower())
        for value in headers.get("content-type", []):
            media_type = value.partition(";")[0].strip()
            if media_type.startswith("text/") or media_type in (
                "gnss/sourcetable", "application/json", "application/xhtml+xml",
            ):
                raise CasterRejectedError(f"CORS 返回 {media_type}，请检查挂载点和地址")
        if any(value != "identity" for value in headers.get("content-encoding", [])):
            raise ConnectionError("CORS 返回了不支持的压缩数据")
        transfer_encoding = ",".join(headers.get("transfer-encoding", []))
        encodings = [part.strip() for part in transfer_encoding.split(",") if part.strip()]
        chunked = encodings == ["chunked"]
        if transfer_encoding and not chunked:
            raise ConnectionError(f"Unsupported NTRIP transfer encoding: {transfer_encoding}")
        decoder: BodyDecoder | None = None
        if chunked:
            decoder = ChunkedDecoder()
        elif "content-length" in headers:
            lengths = headers["content-length"]
            if len(set(lengths)) != 1 or not re.fullmatch(r"[0-9]{1,19}", lengths[0]):
                raise ConnectionError("无效的 CORS Content-Length")
            decoder = _ContentLengthDecoder(int(lengths[0]))
        return bytes(received[header_end + 4 :]), decoder, False

    raise ConnectionError("CORS response headers exceed 64 KiB")


def _resolve_caster(host: str, port: int, deadline: float, cancel: threading.Event | None):
    def wait_for(wait: Callable[[float], bool]) -> None:
        while True:
            if cancel is not None and cancel.is_set():
                raise ConnectionAbortedError("连接已取消")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("解析 CORS 地址超时")
            if wait(min(CONNECT_POLL_SECONDS, remaining)):
                return

    wait_for(lambda timeout: _DNS_SLOTS.acquire(timeout=timeout))
    result = Future()
    ready = threading.Event()

    def lookup() -> None:
        try:
            result.set_result(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except Exception as exc:
            result.set_exception(exc)
        finally:
            _DNS_SLOTS.release()
            ready.set()

    try:
        threading.Thread(target=lookup, name="k922-dns", daemon=True).start()
    except RuntimeError:
        _DNS_SLOTS.release()
        raise
    wait_for(ready.wait)
    return result.result()


def connect_caster(
    config: ClientConfig,
    cancel_event: threading.Event | None = None,
    on_socket: Callable[[socket.socket | None], None] | None = None,
) -> socket.socket:
    """Connect with short polling intervals so stop requests interrupt setup."""
    deadline = time.monotonic() + config.connect_timeout
    addresses = _resolve_caster(config.cors_host, config.cors_port, deadline, cancel_event)

    last_error: OSError | None = None
    raw: socket.socket | None = None
    pending_codes = {errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, errno.EINTR}
    for index, (family, socktype, proto, _, sockaddr) in enumerate(addresses):
        if cancel_event is not None and cancel_event.is_set():
            raise ConnectionAbortedError("连接已取消")
        now = time.monotonic()
        if now >= deadline:
            break
        address_deadline = now + (deadline - now) / (len(addresses) - index)
        candidate = None
        try:
            candidate = socket.socket(family, socktype, proto)
            candidate.setblocking(False)
            error = candidate.connect_ex(sockaddr)
            while error in pending_codes:
                if cancel_event is not None and cancel_event.is_set():
                    raise ConnectionAbortedError("连接已取消")
                remaining = address_deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("连接 CORS 超时")
                _, writable, failed = select.select(
                    [], [candidate], [candidate], min(CONNECT_POLL_SECONDS, remaining)
                )
                if writable or failed:
                    error = candidate.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if error:
                raise OSError(error, "连接 CORS 失败")
            candidate.settimeout(config.connect_timeout)
            raw = candidate
            break
        except OSError as exc:
            last_error = exc
        finally:
            if candidate is not None and candidate is not raw:
                candidate.close()

    if raw is None:
        if cancel_event is not None and cancel_event.is_set():
            raise ConnectionAbortedError("连接已取消")
        if last_error:
            raise last_error
        raise socket.timeout("连接 CORS 超时")

    if on_socket:
        on_socket(raw)
    if cancel_event is not None and cancel_event.is_set():
        raw.close()
        if on_socket:
            on_socket(None)
        raise ConnectionAbortedError("连接已取消")
    if not config.tls:
        return raw

    secured = None
    try:
        context = ssl.create_default_context()
        secured = context.wrap_socket(raw, server_hostname=config.cors_host, do_handshake_on_connect=False)
        if on_socket:
            on_socket(secured)
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise ConnectionAbortedError("TLS 握手已取消")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout("TLS 握手超时")
            secured.settimeout(min(CONNECT_POLL_SECONDS, remaining))
            try:
                secured.do_handshake()
                return secured
            except socket.timeout:
                continue
    except Exception:
        try:
            (secured if secured is not None else raw).close()
        except OSError:
            pass
        if on_socket:
            on_socket(None)
        raise
