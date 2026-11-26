from __future__ import annotations

import socket
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from k922_ntrip.config import ClientConfig
from k922_ntrip.service import LatestGga, NtripService, ServiceEvent
import k922_ntrip.service as service_module


GGA_BODY = b"GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,"
GGA_CHECKSUM = 0
for _byte in GGA_BODY:
    GGA_CHECKSUM ^= _byte
GGA_LINE = b"$" + GGA_BODY + b"*" + f"{GGA_CHECKSUM:02X}".encode("ascii") + b"\r\n"
RTCM_PAYLOAD = b"\xd3\x00\x13K922-SIMULATED-RTCM"


class LatestGgaTests(unittest.TestCase):
    def test_no_fix_clears_previous_position_for_future_uploads(self) -> None:
        latest = LatestGga()
        latest.update(GGA_LINE)
        self.assertEqual(latest.get()[0], GGA_LINE)

        latest.clear()

        self.assertIsNone(latest.get()[0])


class FakeSerialPort:
    def __init__(self, **kwargs) -> None:
        self.timeout = kwargs.get("timeout", 0.02)
        self.writes = bytearray()
        self._gga_sent = False
        self._lock = threading.Lock()

    def __enter__(self) -> "FakeSerialPort":
        return self

    def __exit__(self, *_args) -> None:
        return None

    @property
    def in_waiting(self) -> int:
        return 0 if self._gga_sent else len(GGA_LINE)

    def read(self, size: int) -> bytes:
        with self._lock:
            if not self._gga_sent:
                self._gga_sent = True
                return GGA_LINE
        time.sleep(min(self.timeout, 0.02))
        return b""

    def write(self, payload: bytes) -> int:
        with self._lock:
            self.writes.extend(payload)
        return len(payload)

    def flush(self) -> None:
        return None


class BoardSetupCommandTests(unittest.TestCase):
    def test_startup_configures_ins_heading_and_gga_in_order(self) -> None:
        config = ClientConfig.from_mapping(
            {
                "serial_port": "SIMULATED",
                "baudrate": 115200,
                "cors_host": "127.0.0.1",
                "cors_port": 2101,
                "mountpoint": "SIM",
                "ins_mode": "enable",
                "imu_axis_type": 1,
                "dr_leverarm_x_m": 0.25,
                "dr_leverarm_y_m": -0.1,
                "dr_leverarm_z_m": 0.5,
                "dr_init_speed_mps": 1.0,
                "dr_timeout_seconds": 30,
                "heading_mode": "enable",
                "attitude_output_rate_hz": 10.0,
                "gga_output_rate_hz": 20.0,
                "command_delay": 0,
            }
        )
        serial_port = FakeSerialPort()
        service = NtripService(config, lambda _event: None)

        service._send_board_setup(serial_port)

        self.assertEqual(
            bytes(serial_port.writes),
            (
                b"set imuaxestype 1\r\n"
                b"set drleverarm 0.25 -0.1 0.5\r\n"
                b"set drconfig 1\r\n"
                b"set drtimeout 30\r\n"
                b"inscontrol enable\r\n"
                b"log headinga ontime 0.1\r\n"
                b"log gphpr ontime 0.1\r\n"
                b"log gpgga ontime 0.05\r\n"
                b"saveconfig\r\n"
            ),
        )

    def test_disable_modes_stop_ins_and_heading_outputs(self) -> None:
        config = ClientConfig.from_mapping(
            {
                "serial_port": "SIMULATED",
                "baudrate": 115200,
                "cors_host": "127.0.0.1",
                "cors_port": 2101,
                "mountpoint": "SIM",
                "ins_mode": "disable",
                "heading_mode": "disable",
                "command_delay": 0,
            }
        )
        serial_port = FakeSerialPort()
        service = NtripService(config, lambda _event: None)

        service._send_board_setup(serial_port)

        self.assertEqual(
            bytes(serial_port.writes),
            b"inscontrol disable\r\nunlog heading\r\nunlog gphpr\r\n"
            b"log gpgga ontime 5\r\nsaveconfig\r\n",
        )


class FailingCorrectionSerialPort(FakeSerialPort):
    def write(self, payload: bytes) -> int:
        if payload.startswith(b"\xd3"):
            raise OSError("simulated serial write failure")
        return super().write(payload)


class SimulatedCaster:
    """Loopback caster that serves a scripted NTRIP response."""

    def __init__(self, response: bytes) -> None:
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(5)
        self.port = self.listener.getsockname()[1]
        self.response = response
        self.request = b""
        self.gga_lines: list[bytes] = []
        self.two_gga_received = threading.Event()
        self.error: BaseException | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="simulated-caster", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        connection: socket.socket | None = None
        try:
            connection, _ = self.listener.accept()
            connection.settimeout(0.25)
            request_buffer = bytearray()
            while b"\r\n\r\n" not in request_buffer:
                chunk = connection.recv(4096)
                if not chunk:
                    raise ConnectionError("client closed before completing its request")
                request_buffer.extend(chunk)
                if len(request_buffer) > 32 * 1024:
                    raise ConnectionError("request headers exceed simulation limit")
            header_end = request_buffer.index(b"\r\n\r\n") + 4
            self.request = bytes(request_buffer[:header_end])
            if request_buffer[header_end:]:
                raise AssertionError("unexpected client body after NTRIP headers")

            connection.sendall(self.response)
            pending = bytearray()
            while not self._stop.is_set():
                try:
                    chunk = connection.recv(1024)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                pending.extend(chunk)
                while b"\r\n" in pending:
                    line_end = pending.index(b"\r\n") + 2
                    self.gga_lines.append(bytes(pending[:line_end]))
                    del pending[:line_end]
                    if len(self.gga_lines) >= 2:
                        self.two_gga_received.set()
        except BaseException as exc:
            if not self._stop.is_set():
                self.error = exc
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass

    def close(self) -> None:
        self._stop.set()
        try:
            self.listener.close()
        except OSError:
            pass
        self._thread.join(timeout=2)


class ServiceSimulationTests(unittest.TestCase):
    def test_silent_open_stream_reconnects_while_board_has_a_fix(self) -> None:
        caster = SimulatedCaster(b"HTTP/1.1 200 OK\r\n\r\n")
        config = ClientConfig("SIM", 115200, "127.0.0.1", caster.port, "SIM", command_delay=0)
        events = []
        def observe(event: ServiceEvent):
            events.append(event)
            if event.kind == "state" and event.data["state"] == "reconnecting":
                service.request_stop()

        service = NtripService(config, observe)
        try:
            with patch.object(service_module, "serial", SimpleNamespace(Serial=FakeSerialPort)), \
                    patch.object(service_module, "CORRECTION_IDLE_SECONDS", 0.1):
                thread = threading.Thread(target=service.run, daemon=True)
                thread.start()
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
            self.assertTrue(any("未收到差分数据" in e.data.get("message", "") for e in events))
        finally:
            service.request_stop()
            caster.close()

    def test_serial_fragments_survive_timeout_and_resync_after_oversized_line(self) -> None:
        events = []
        config = ClientConfig("SIM", 115200, "localhost", 2101, "SIM")
        service = NtripService(config, events.append)
        reads = iter((b"x" * 4096, b"invalid" + GGA_LINE, GGA_LINE[:15], b"", GGA_LINE[15:] + GGA_LINE))

        def read(_size):
            block = next(reads, None)
            if block is None:
                service.request_stop()
            return block or b""

        service._read_serial(SimpleNamespace(in_waiting=4096, read=read))
        self.assertEqual([e.data["sentence"] for e in events], [GGA_LINE.decode().strip()] * 2)

    def test_gga_expires_and_allows_slow_board_output(self) -> None:
        for rate, max_age in ((20, 10), (1 / 60, 120)):
            with self.subTest(rate=rate):
                config = ClientConfig("SIM", 115200, "localhost", 2101, "SIM", gga_output_rate_hz=rate)
                service = NtripService(config, lambda _: None)
                with patch.object(service_module.time, "monotonic", side_effect=(1000, 1001, 1000 + max_age + 1)):
                    service._latest_gga.update(GGA_LINE)
                    self.assertEqual(service._fresh_gga(), GGA_LINE)
                    self.assertIsNone(service._fresh_gga())

    def test_serial_disconnect_interrupts_a_waiting_caster(self) -> None:
        config = ClientConfig("SIM", 115200, "localhost", 2101, "SIM")
        service = NtripService(config, lambda _: None)
        def disconnected(_size):
            raise OSError("串口已拔出")

        reader, caster = socket.socketpair()
        with reader, caster:
            service._set_active_socket(reader)
            service._read_serial(SimpleNamespace(in_waiting=1, read=disconnected))
            caster.settimeout(1)
            self.assertEqual(caster.recv(1), b"")
            self.assertTrue(service._serial_error.is_set())

    def test_ntrip_v2_icy_fallback_forwards_rtcm_and_repeats_gga(self) -> None:
        caster = SimulatedCaster(b"ICY 200 OK\r\n" + RTCM_PAYLOAD)
        fake_serial = FakeSerialPort(timeout=0.02)
        events: list[ServiceEvent] = []
        events_lock = threading.Lock()
        second_gga_uploaded = threading.Event()
        gga_upload_times = []
        run_result: list[int] = []

        def event_sink(event: ServiceEvent) -> None:
            with events_lock:
                events.append(event)
                if event.kind == "gga_upload":
                    gga_upload_times.append(event.data["at"])
                upload_count = sum(item.kind == "gga_upload" for item in events)
            if upload_count >= 2:
                second_gga_uploaded.set()

        config = ClientConfig.from_mapping(
            {
                "serial_port": "SIMULATED",
                "baudrate": 115200,
                "gga_output_rate_hz": 2,
                "cors_host": "127.0.0.1",
                "cors_port": caster.port,
                "mountpoint": "SIM",
                "ntrip_version": "2.0",
                "serial_timeout": 0.02,
                "connect_timeout": 2,
                "reconnect_delay": 0,
                "command_delay": 0,
            }
        )
        service = NtripService(config, event_sink)
        thread = threading.Thread(target=lambda: run_result.append(service.run()), daemon=True)

        try:
            with patch.object(service_module, "serial", SimpleNamespace(Serial=lambda **_kwargs: fake_serial)):
                thread.start()
                self.assertTrue(
                    second_gga_uploaded.wait(timeout=8),
                    "the client did not upload its initial and periodic GGA sentences",
                )
                self.assertTrue(
                    caster.two_gga_received.wait(timeout=2),
                    "the simulated caster did not receive both GGA sentences",
                )
                service.request_stop()
                thread.join(timeout=3)

            self.assertFalse(thread.is_alive(), "the service did not stop promptly")
            self.assertEqual(run_result, [0])
            self.assertIn(b"GET /SIM HTTP/1.1\r\n", caster.request)
            self.assertIn(b"Ntrip-GGA: " + GGA_LINE.rstrip(b"\r\n") + b"\r\n", caster.request)
            self.assertGreaterEqual(len(caster.gga_lines), 2)
            self.assertEqual(caster.gga_lines[0], GGA_LINE)  # ICY fallback GGA after the response.
            self.assertEqual(caster.gga_lines[1], GGA_LINE)  # Periodic GGA at the five-second interval.

            setup = b"log gpgga ontime 0.5\r\nsaveconfig\r\n"
            self.assertTrue(fake_serial.writes.startswith(setup))
            self.assertEqual(bytes(fake_serial.writes[len(setup) :]), RTCM_PAYLOAD)
            self.assertGreaterEqual((gga_upload_times[1] - gga_upload_times[0]).total_seconds(), 4.9)
            self.assertIsNone(caster.error)
            self.assertTrue(any(event.kind == "state" and event.data["state"] == "connected" for event in events))
            gga_event = next(event for event in events if event.kind == "gga")
            self.assertAlmostEqual(gga_event.data["position"].latitude_degrees, 48.1173)
            self.assertEqual(gga_event.data["position"].satellites, 8)
        finally:
            service.request_stop()
            thread.join(timeout=3)
            caster.close()

    def test_http_chunked_stream_is_decoded_and_forwarded(self) -> None:
        chunks = b"4\r\n" + RTCM_PAYLOAD[:4] + b"\r\n"
        chunks += f"{len(RTCM_PAYLOAD[4:]):X}\r\n".encode("ascii") + RTCM_PAYLOAD[4:] + b"\r\n0\r\n\r\n"
        response = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + chunks
        caster = SimulatedCaster(response)
        fake_serial = FakeSerialPort(timeout=0.02)
        corrections_written = threading.Event()
        result: list[int] = []

        def event_sink(event: ServiceEvent) -> None:
            if event.kind == "stats" and event.data["bytes_received"] >= len(RTCM_PAYLOAD):
                corrections_written.set()

        config = ClientConfig.from_mapping(
            {
                "serial_port": "SIMULATED",
                "baudrate": 115200,
                "cors_host": "127.0.0.1",
                "cors_port": caster.port,
                "mountpoint": "SIM",
                "serial_timeout": 0.02,
                "connect_timeout": 2,
                "reconnect_delay": 0,
                "command_delay": 0,
            }
        )
        service = NtripService(config, event_sink)
        thread = threading.Thread(target=lambda: result.append(service.run()), daemon=True)
        try:
            with patch.object(service_module, "serial", SimpleNamespace(Serial=lambda **_kwargs: fake_serial)):
                thread.start()
                self.assertTrue(corrections_written.wait(timeout=2), "chunked RTCM was not forwarded")
                service.request_stop()
                thread.join(timeout=3)

            self.assertFalse(thread.is_alive())
            self.assertEqual(result, [0])
            setup = b"log gpgga ontime 5\r\nsaveconfig\r\n"
            self.assertEqual(bytes(fake_serial.writes[len(setup) :]), RTCM_PAYLOAD)
            self.assertIn(b"GET /SIM HTTP/1.1\r\n", caster.request)
            self.assertIn(b"Ntrip-Version: Ntrip/2.0\r\n", caster.request)
            self.assertIsNone(caster.error)
        finally:
            service.request_stop()
            thread.join(timeout=3)
            caster.close()

    def test_caster_rejection_returns_failure_without_reconnect(self) -> None:
        caster = SimulatedCaster(
            b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n"
        )
        fake_serial = FakeSerialPort(timeout=0.02)
        events: list[ServiceEvent] = []
        config = ClientConfig.from_mapping(
            {
                "serial_port": "SIMULATED",
                "baudrate": 115200,
                "cors_host": "127.0.0.1",
                "cors_port": caster.port,
                "mountpoint": "SIM",
                "serial_timeout": 0.02,
                "connect_timeout": 2,
                "reconnect_delay": 0,
                "command_delay": 0,
            }
        )
        service = NtripService(config, events.append)
        try:
            with patch.object(service_module, "serial", SimpleNamespace(Serial=lambda **_kwargs: fake_serial)):
                result = service.run()

            self.assertEqual(result, 1)
            self.assertFalse(
                any(event.kind == "state" and event.data["state"] == "reconnecting" for event in events)
            )
            self.assertTrue(any(event.kind == "state" and event.data["state"] == "failed" for event in events))
            self.assertIsNone(caster.error)
        finally:
            caster.close()

    def test_serial_write_failure_is_terminal_not_a_network_reconnect(self) -> None:
        caster = SimulatedCaster(b"ICY 200 OK\r\n" + RTCM_PAYLOAD)
        fake_serial = FailingCorrectionSerialPort(timeout=0.02)
        events: list[ServiceEvent] = []
        config = ClientConfig.from_mapping(
            {
                "serial_port": "SIMULATED",
                "baudrate": 115200,
                "cors_host": "127.0.0.1",
                "cors_port": caster.port,
                "mountpoint": "SIM",
                "serial_timeout": 0.02,
                "connect_timeout": 2,
                "reconnect_delay": 0,
                "command_delay": 0,
            }
        )
        service = NtripService(config, events.append)
        try:
            with patch.object(service_module, "serial", SimpleNamespace(Serial=lambda **_kwargs: fake_serial)):
                result = service.run()

            self.assertEqual(result, 1)
            self.assertTrue(any(event.kind == "state" and event.data["state"] == "failed" for event in events))
            self.assertFalse(
                any(event.kind == "state" and event.data["state"] == "reconnecting" for event in events)
            )
            self.assertIsNone(caster.error)
        finally:
            caster.close()


if __name__ == "__main__":
    unittest.main()
