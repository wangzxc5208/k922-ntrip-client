"""Serial and NTRIP orchestration. This module has no Qt dependencies."""

from __future__ import annotations

import socket
import ssl
import threading
import time
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

try:
    import serial
except ImportError:  # pragma: no cover - runtime dependency message
    serial = None

from .config import ClientConfig
from .nmea import parse_gga, parse_gphpr
from .protocol import (
    CasterRejectedError,
    build_ntrip_request,
    connect_caster,
    format_tls_error,
    read_caster_stream,
)


GGA_INTERVAL_SECONDS = 5.0
CORRECTION_IDLE_SECONDS = 30.0
SERIAL_WRITE_CHUNK_SIZE = 512
MAX_SERIAL_LINE = 130  # 128-byte sentence plus CRLF
EventSink = Callable[["ServiceEvent"], None]


def freshness_seconds(rate_hz: float) -> float:
    """Allow two expected board periods, with room for two CORS upload intervals."""
    return 2 * max(GGA_INTERVAL_SECONDS, 1.0 / rate_hz)


@dataclass(frozen=True)
class ServiceEvent:
    kind: str
    data: dict[str, Any]


class SerialLinkError(RuntimeError):
    """Raised when the board serial link cannot accept data."""


class LatestGga:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sentence: bytes | None = None
        self._updated_at = 0.0

    def update(self, sentence: bytes) -> None:
        with self._lock:
            self._sentence = sentence
            self._updated_at = time.monotonic()

    def clear(self) -> None:
        with self._lock:
            self._sentence = None
            self._updated_at = 0.0

    def get(self) -> tuple[bytes | None, float]:
        with self._lock:
            return self._sentence, self._updated_at


class NtripService:
    """Owns one client lifecycle, serial reader and caster connection loop."""

    def __init__(self, config: ClientConfig, event_sink: EventSink) -> None:
        self.config = config
        self._event_sink = event_sink
        self._stop = threading.Event()
        self._serial_error = threading.Event()
        self._latest_gga = LatestGga()
        self._socket_lock = threading.Lock()
        self._active_socket: socket.socket | None = None
        self._bytes_received = 0
        self._reconnects = 0
        self._started_at = 0.0
        self._last_stats_at = 0.0
        self._last_stats_bytes = 0

    def request_stop(self) -> None:
        self._stop.set()
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

    def _emit(self, kind: str, **data: Any) -> None:
        self._event_sink(ServiceEvent(kind, data))

    def _log(self, level: str, message: str) -> None:
        self._emit("log", level=level, message=message, at=datetime.now())

    def _set_state(self, state: str, message: str) -> None:
        self._emit("state", state=state, message=message)
        level = {"failed": "ERROR", "reconnecting": "WARNING"}.get(state, "INFO")
        self._log(level, message)

    def _read_serial(self, port: Any) -> None:
        pending = bytearray()
        discard_line = False
        while not self._stop.is_set():
            try:
                block = port.read(max(1, min(port.in_waiting, 4096)))
            except Exception as exc:
                if not self._stop.is_set():
                    self._serial_error.set()
                    self._log("ERROR", f"串口读取失败：{exc}")
                    self.request_stop()
                return
            if not block:
                continue
            fragments = block.split(b"\n")
            for index, fragment in enumerate(fragments):
                if len(pending) + len(fragment) > MAX_SERIAL_LINE:
                    discard_line = True
                    pending.clear()
                if not discard_line:
                    pending.extend(fragment)
                if index < len(fragments) - 1:
                    if pending:
                        self._handle_serial_line(bytes(pending).strip(b"\r\x00 \t"))
                    pending.clear()
                    discard_line = False

    def _handle_serial_line(self, sentence: bytes) -> None:
        attitude = parse_gphpr(sentence)
        if attitude is not None:
            self._emit(
                "attitude",
                sentence=sentence.decode("ascii"),
                attitude=attitude,
                at=datetime.now(),
            )
            return
        position = parse_gga(sentence)
        if position is None:
            return
        if position.has_fix:
            self._latest_gga.update(sentence + b"\r\n")
        else:
            self._latest_gga.clear()
        self._emit("gga", sentence=sentence.decode("ascii"), position=position, at=datetime.now())

    def _fresh_gga(self) -> bytes | None:
        sentence, updated_at = self._latest_gga.get()
        # Allow slow board output (down to one fix per minute) and short serial jitter.
        max_age = freshness_seconds(self.config.gga_output_rate_hz)
        return sentence if time.monotonic() - updated_at <= max_age else None

    def _send_board_setup(self, port: Any) -> None:
        gga_period_seconds = 1.0 / self.config.gga_output_rate_hz
        period_text = format(gga_period_seconds, ".8g")
        commands: list[str] = []
        if self.config.ins_mode == "enable":
            commands.extend(
                (
                    f"set imuaxestype {self.config.imu_axis_type}",
                    "set drleverarm "
                    f"{self.config.dr_leverarm_x_m:.6g} "
                    f"{self.config.dr_leverarm_y_m:.6g} "
                    f"{self.config.dr_leverarm_z_m:.6g}",
                    f"set drconfig {self.config.dr_init_speed_mps:.6g}",
                    f"set drtimeout {self.config.dr_timeout_seconds}",
                    "inscontrol enable",
                )
            )
        elif self.config.ins_mode == "disable":
            commands.append("inscontrol disable")

        if self.config.heading_mode == "enable":
            attitude_period = format(1.0 / self.config.attitude_output_rate_hz, ".8g")
            commands.extend(
                (
                    f"log headinga ontime {attitude_period}",
                    f"log gphpr ontime {attitude_period}",
                )
            )
        elif self.config.heading_mode == "disable":
            commands.extend(("unlog heading", "unlog gphpr"))

        commands.extend((f"log gpgga ontime {period_text}", "saveconfig"))
        for command in commands:
            if self._stop.is_set():
                break
            self._write_serial(port, command.encode("ascii") + b"\r\n")
            self._log("INFO", f"已发送板卡指令：{command}")
            if self.config.command_delay:
                self._stop.wait(self.config.command_delay)

    @staticmethod
    def _write_serial(port: Any, payload: bytes) -> int:
        written_total = 0
        try:
            while written_total < len(payload):
                written = port.write(payload[written_total:])
                if written is None or written <= 0:
                    raise SerialLinkError("串口未写入数据")
                written_total += written
        except SerialLinkError:
            raise
        except Exception as exc:
            raise SerialLinkError(str(exc)) from exc
        return written_total

    def _wait_for_gga(self) -> bool:
        self._set_state("waiting_gga", "等待板卡输出有效 GPGGA 定位")
        while not self._stop.is_set():
            if self._fresh_gga():
                self._log("INFO", "已收到有效 GGA，准备连接 CORS")
                return True
            self._stop.wait(0.25)
        return False

    def _set_active_socket(self, active_socket: socket.socket | None) -> None:
        with self._socket_lock:
            self._active_socket = active_socket

    def _forward_corrections(self, port: Any, payload: bytes) -> None:
        if not payload:
            return
        try:
            for offset in range(0, len(payload), SERIAL_WRITE_CHUNK_SIZE):
                if self._stop.is_set():
                    break
                chunk = payload[offset : offset + SERIAL_WRITE_CHUNK_SIZE]
                self._bytes_received += self._write_serial(port, chunk)
                self._emit_stats()
        except SerialLinkError:
            raise
        except Exception as exc:
            raise SerialLinkError(str(exc)) from exc

    def _emit_stats(self, force: bool = False) -> None:
        now = time.monotonic()
        elapsed = now - self._last_stats_at
        if not force and elapsed < 1.0:
            return
        rate = (self._bytes_received - self._last_stats_bytes) / elapsed if elapsed > 0 else 0.0
        self._last_stats_at = now
        self._last_stats_bytes = self._bytes_received
        self._emit(
            "stats",
            bytes_received=self._bytes_received,
            rate_bytes_per_second=rate,
            runtime_seconds=max(0.0, now - self._started_at),
            reconnects=self._reconnects,
        )

    def _run_connection(self, port: Any) -> None:
        active_socket = connect_caster(self.config, self._stop, self._set_active_socket)
        try:
            with active_socket as caster:
                if self._stop.is_set():
                    return
                caster.settimeout(self.config.connect_timeout)
                initial_gga = self._fresh_gga()
                if initial_gga is None:
                    return
                caster.sendall(build_ntrip_request(self.config, initial_gga))
                last_upload = time.monotonic()
                initial_body, decoder, used_icy = read_caster_stream(caster)
                caster.settimeout(0.5)
                initial_corrections = decoder.feed(initial_body) if decoder else initial_body

                if self.config.ntrip_version == "1.0" or used_icy:
                    initial_gga = self._fresh_gga()
                    if initial_gga is not None:
                        caster.sendall(initial_gga)
                        last_upload = time.monotonic()
                self._set_state("connected", f"CORS 已连接：{self.config.cors_host}/{self.config.mountpoint}")
                if initial_gga:
                    self._emit("gga_upload", sentence=initial_gga.decode("ascii", errors="replace"), at=datetime.now())
                self._forward_corrections(port, initial_corrections)
                last_correction = time.monotonic()
                next_gga_check = last_upload + GGA_INTERVAL_SECONDS
                missing_gga = False
                self._emit_stats(force=True)

                while not self._stop.is_set():
                    if decoder and decoder.finished:
                        raise ConnectionError("CORS 已结束差分数据流")
                    now = time.monotonic()
                    if self._fresh_gga() is None:
                        last_correction = now
                    elif now - last_correction >= CORRECTION_IDLE_SECONDS:
                        raise TimeoutError(f"连续 {CORRECTION_IDLE_SECONDS:g} 秒未收到差分数据")
                    if now >= next_gga_check:
                        sentence = self._fresh_gga()
                        if sentence:
                            caster.sendall(sentence)
                            next_gga_check = now + GGA_INTERVAL_SECONDS
                            missing_gga = False
                            self._emit(
                                "gga_upload",
                                sentence=sentence.decode("ascii", errors="replace"),
                                at=datetime.now(),
                            )
                        else:
                            if not missing_gga:
                                self._log("WARNING", "板卡未提供新的有效定位，暂停上传 GGA")
                            missing_gga = True
                            next_gga_check = now + 0.5

                    until_next_gga = max(
                        0.1,
                        next_gga_check - time.monotonic(),
                    )
                    caster.settimeout(min(0.5, until_next_gga))
                    try:
                        payload = caster.recv(4096)
                    except socket.timeout:
                        self._emit_stats()
                        continue
                    if not payload:
                        raise ConnectionError("CORS closed the connection")
                    corrections = decoder.feed(payload) if decoder else payload
                    self._forward_corrections(port, corrections)
                    if corrections:
                        last_correction = time.monotonic()
        finally:
            self._set_active_socket(None)

    def _stop_reader(self, port: Any, reader: threading.Thread) -> None:
        self._stop.set()
        try:
            port.cancel_read()
        except (AttributeError, OSError):
            pass
        reader.join()

    def run(self) -> int:
        self._started_at = time.monotonic()
        final_state = "stopped"
        exit_code = 0
        self._set_state("starting", "正在打开 RS232 串口")
        try:
            if serial is None:
                raise RuntimeError("缺少 pyserial，请先安装 requirements.txt 中的依赖")
            with serial.Serial(
                port=self.config.serial_port,
                baudrate=self.config.baudrate,
                timeout=min(self.config.serial_timeout, 0.5),
                write_timeout=3.0,
            ) as port, ExitStack() as cleanup:
                self._log("INFO", f"RS232 已打开：{self.config.serial_port} · {self.config.baudrate} baud")
                reader = threading.Thread(
                    target=self._read_serial,
                    args=(port,),
                    name="k922-serial-reader",
                    daemon=True,
                )
                reader.start()
                cleanup.callback(self._stop_reader, port, reader)
                self._send_board_setup(port)
                if not self._wait_for_gga():
                    if self._serial_error.is_set():
                        final_state = "failed"
                        exit_code = 1
                else:
                    while not self._stop.is_set():
                        if self._fresh_gga() is None and not self._wait_for_gga():
                            break
                        self._set_state("connecting", "正在连接 CORS")
                        try:
                            self._run_connection(port)
                        except CasterRejectedError as exc:
                            final_state = "failed"
                            exit_code = 1
                            self._log("ERROR", f"CORS 拒绝连接：{exc}。请检查地址、挂载点和账号后重新启动。")
                            break
                        except SerialLinkError as exc:
                            final_state = "failed"
                            exit_code = 1
                            self._log("ERROR", f"RS232 写入失败，已停止链路：{exc}")
                            break
                        except ssl.SSLError as exc:
                            if self._stop.is_set():
                                break
                            final_state = "failed"
                            exit_code = 1
                            self._log("ERROR", format_tls_error(exc))
                            break
                        except OSError as exc:
                            if self._stop.is_set():
                                break
                            self._reconnects += 1
                            self._set_state("reconnecting", f"连接中断，{self.config.reconnect_delay:g} 秒后重试")
                            self._log("WARNING", f"NTRIP 链路异常：{exc}")
                            if self._stop.wait(self.config.reconnect_delay):
                                break

                    if self._serial_error.is_set():
                        final_state = "failed"
                        exit_code = 1
        except SerialLinkError as exc:
            final_state = "failed"
            exit_code = 1
            self._log("ERROR", f"RS232 操作失败：{exc}")
        except Exception as exc:
            final_state = "failed"
            exit_code = 1
            self._log("ERROR", f"客户端启动失败：{exc}")
        finally:
            self.request_stop()
            self._set_active_socket(None)
            if final_state == "failed":
                self._set_state("failed", "客户端已停止，请查看运行日志")
            else:
                self._set_state("stopped", "客户端已停止")
        return exit_code
