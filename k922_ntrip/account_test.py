"""CORS credential and mountpoint probe without opening the board serial port."""

from __future__ import annotations

import math
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .config import ClientConfig
from .protocol import build_ntrip_request, connect_caster, is_gga, read_caster_stream
from .rtcm import MAX_RTCM3_FRAME_BYTES, RtcmFrameInfo, parse_rtcm3_frames


DATA_PROBE_SECONDS = 10.0
GGA_UPLOAD_INTERVAL_SECONDS = 5.0
MAX_ACCOUNT_PREVIEW_BYTES = 4096


@dataclass(frozen=True)
class AccountTestResult:
    authenticated: bool
    bytes_received: int
    message: str
    data_preview: bytes = b""
    rtcm_frames: tuple[RtcmFrameInfo, ...] = ()
    gga_sent_count: int = 0
    duration_seconds: float = 0.0
    rtcm_confirmed: bool = False
    last_gga: bytes = b""
    stopped: bool = False
    stream_error: bool = False


@dataclass(frozen=True)
class AccountTestProgress:
    authenticated: bool
    bytes_received: int
    gga_sent_count: int
    duration_seconds: float
    data_preview: bytes = b""
    rtcm_frames: tuple[RtcmFrameInfo, ...] = ()
    rtcm_confirmed: bool = False
    last_gga: bytes = b""


class _ProbeSample:
    """Keep a bounded preview and look for the first valid RTCM across socket reads."""

    def __init__(self) -> None:
        self.preview = b""
        self.frames: tuple[RtcmFrameInfo, ...] = ()
        self.confirmed = False
        self.tail = b""
        self.total = 0

    def consume(self, data: bytes) -> None:
        if not data:
            return
        self.total += len(data)
        room = MAX_ACCOUNT_PREVIEW_BYTES - len(self.preview)
        if room:
            self.preview += data[:room]
            self.frames = parse_rtcm3_frames(self.preview)
            self.confirmed |= any(f.crc_valid and f.message_type is not None for f in self.frames)
        if not self.confirmed:
            window = self.tail + data
            for frame in parse_rtcm3_frames(window, max_frames=len(window)):
                if frame.crc_valid and frame.message_type is not None:
                    self.preview = window[frame.offset:frame.offset + MAX_ACCOUNT_PREVIEW_BYTES]
                    self.frames = parse_rtcm3_frames(self.preview)
                    self.confirmed = True
                    break
            self.tail = window[-(MAX_RTCM3_FRAME_BYTES - 1):]


def _format_nmea_coordinate(value: float | str, *, latitude: bool) -> tuple[str, str]:
    try:
        decimal_degrees = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("测试坐标必须是十进制度数") from exc
    degree_limit = 90 if latitude else 180
    if not math.isfinite(decimal_degrees) or abs(decimal_degrees) > degree_limit:
        label = "纬度" if latitude else "经度"
        raise ValueError(f"{label}超出有效范围")

    degrees = int(abs(decimal_degrees))
    minutes = round((abs(decimal_degrees) - degrees) * 60.0, 5)
    if minutes >= 60.0:
        degrees += 1
        minutes = 0.0
    if degrees > degree_limit:
        raise ValueError("测试坐标超出有效范围")

    degree_width = 2 if latitude else 3
    hemisphere = ("N" if decimal_degrees >= 0 else "S") if latitude else (
        "E" if decimal_degrees >= 0 else "W"
    )
    return f"{degrees:0{degree_width}d}{minutes:08.5f}", hemisphere


def build_synthetic_gga(
    latitude: float | str,
    longitude: float | str,
    *,
    now: datetime | None = None,
) -> bytes:
    """Build a checksummed GPGGA sentence from decimal-degree test coordinates."""
    latitude_field, north_south = _format_nmea_coordinate(latitude, latitude=True)
    longitude_field, east_west = _format_nmea_coordinate(longitude, latitude=False)
    observation_time = now or datetime.now(timezone.utc)
    if observation_time.tzinfo is not None:
        observation_time = observation_time.astimezone(timezone.utc)
    timestamp = observation_time.strftime("%H%M%S")
    body = (
        f"GPGGA,{timestamp},{latitude_field},{north_south},{longitude_field},{east_west},"
        "1,12,0.8,0.0,M,0.0,M,,"
    )
    return _encode_gga(body)


def _encode_gga(body: str) -> bytes:
    checksum = 0
    for byte in body.encode("ascii"):
        checksum ^= byte
    return f"${body}*{checksum:02X}\r\n".encode("ascii")


def _refresh_gga(sentence: bytes) -> bytes:
    fields = sentence[1:].split(b"*", 1)[0].rstrip(b"\r\n").decode("ascii").split(",")
    fields[1] = datetime.now(timezone.utc).strftime("%H%M%S")
    return _encode_gga(",".join(fields))


def verify_account(
    config: ClientConfig,
    gga_sentence: bytes,
    cancel_event: threading.Event | None = None,
    on_socket: Callable[[socket.socket | None], None] | None = None,
    on_progress: Callable[[AccountTestProgress], None] | None = None,
    continuous: bool = False,
) -> AccountTestResult:
    """Verify a caster and optionally simulate a continuing NTRIP client.

    The supplied synthetic GGA is sent in the NTRIP 2.0 request or immediately after
    a successful NTRIP 1.0 / ICY response, then refreshed every five seconds. This
    test does not open RS232 or change the board configuration. Continuous mode
    runs until the socket closes or ``cancel_event`` is set.
    """
    config = ClientConfig.from_mapping(config.to_mapping())
    gga_sentence = gga_sentence.rstrip(b"\r\n") + b"\r\n"
    if not is_gga(gga_sentence.rstrip(b"\r\n")):
        raise ValueError("合成 GGA 报文无效")
    caster = connect_caster(config, cancel_event, on_socket)
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise ConnectionAbortedError("账号测试已取消")
        caster.settimeout(config.connect_timeout)
        initial_gga = gga_sentence if config.ntrip_version == "2.0" else None
        caster.sendall(build_ntrip_request(config, initial_gga, keep_alive=continuous))
        last_gga_sent = time.monotonic()
        gga_sent_count = 1 if initial_gga else 0
        initial_payload, decoder, used_icy = read_caster_stream(caster)
        data = decoder.feed(initial_payload) if decoder else initial_payload

        if config.ntrip_version == "1.0" or used_icy:
            caster.sendall(gga_sentence)
            last_gga_sent = time.monotonic()
            gga_sent_count += 1

        started_at = time.monotonic()
        deadline = None if continuous else started_at + DATA_PROBE_SECONDS
        sample = _ProbeSample()
        sample.consume(data)
        last_progress_at = 0.0

        def publish_progress(*, force: bool = False) -> None:
            nonlocal last_progress_at
            if on_progress is None:
                return
            now = time.monotonic()
            if not force and now - last_progress_at < 0.5:
                return
            on_progress(
                AccountTestProgress(
                    authenticated=True,
                    bytes_received=sample.total,
                    gga_sent_count=gga_sent_count,
                    duration_seconds=now - started_at,
                    data_preview=sample.preview,
                    rtcm_frames=sample.frames,
                    rtcm_confirmed=sample.confirmed,
                    last_gga=gga_sentence,
                )
            )
            last_progress_at = now

        publish_progress(force=True)
        stream_error = False
        end_reason = ""
        while (continuous or not sample.confirmed) and not (decoder and decoder.finished):
            if cancel_event is not None and cancel_event.is_set():
                break
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                break
            if now - last_gga_sent >= GGA_UPLOAD_INTERVAL_SECONDS:
                outgoing_gga = _refresh_gga(gga_sentence)
                try:
                    caster.sendall(outgoing_gga)
                except OSError as exc:
                    stream_error = True
                    end_reason = f"GGA 上传中断（{exc}）"
                    break
                gga_sentence = outgoing_gga
                last_gga_sent = now
                gga_sent_count += 1
                publish_progress(force=True)
            until_probe_end = (
                max(0.01, deadline - time.monotonic())
                if deadline is not None
                else 0.25
            )
            until_next_gga = max(
                0.01,
                GGA_UPLOAD_INTERVAL_SECONDS - (time.monotonic() - last_gga_sent),
            )
            try:
                caster.settimeout(min(0.25, until_probe_end, until_next_gga))
                payload = caster.recv(4096)
                if not payload:
                    end_reason = "服务端已关闭连接"
                    stream_error = continuous or (decoder is not None and not decoder.finished)
                    break
                data = decoder.feed(payload) if decoder else payload
            except socket.timeout:
                publish_progress()
                continue
            except OSError as exc:
                stream_error = True
                end_reason = f"接收中断（{exc}）"
                break
            sample.consume(data)
            publish_progress()

        duration_seconds = time.monotonic() - started_at
        stopped = cancel_event is not None and cancel_event.is_set()
        if stopped:
            end_reason = "测试已停止"
        elif decoder and decoder.finished:
            end_reason = "服务端已结束数据流"
        summary = (
            f"已认证，运行 {duration_seconds:.1f} 秒，已发送合成 GGA {gga_sent_count} 次，"
            f"共收到 {sample.total} 字节。"
        )
        diagnosis = "已验证 RTCM 3 帧和 CRC。" if sample.confirmed else "尚未收到校验通过的 RTCM 3 帧。"
        return AccountTestResult(
            authenticated=True,
            bytes_received=sample.total,
            message=(end_reason + "。" if end_reason else "") + summary + diagnosis,
            data_preview=sample.preview,
            rtcm_frames=sample.frames,
            gga_sent_count=gga_sent_count,
            duration_seconds=duration_seconds,
            rtcm_confirmed=sample.confirmed,
            last_gga=gga_sentence,
            stopped=stopped,
            stream_error=stream_error and not stopped,
        )
    finally:
        try:
            caster.close()
        except OSError:
            pass
        if on_socket:
            on_socket(None)
