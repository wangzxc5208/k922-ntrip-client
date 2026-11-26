from __future__ import annotations

import json
import os
import socket
import ssl
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from k922_ntrip.account_test import build_synthetic_gga
from k922_ntrip.config import ClientConfig, ConfigError, ConfigStore
from k922_ntrip.protocol import ChunkedDecoder, connect_caster, format_tls_error, is_gga, read_ntrip_response


BASE_CONFIG = {
    "serial_port": "COM_TEST",
    "baudrate": 115200,
    "cors_host": "127.0.0.1",
    "cors_port": 2101,
    "mountpoint": "TEST",
}


def nmea_sentence(body: str) -> bytes:
    checksum = 0
    for byte in body.encode("ascii"):
        checksum ^= byte
    return f"${body}*{checksum:02X}".encode("ascii")


class ConfigValidationTests(unittest.TestCase):
    def test_gga_output_rate_defaults_migrates_and_stays_within_registration_limit(self) -> None:
        self.assertEqual(ClientConfig.from_mapping(BASE_CONFIG).gga_output_rate_hz, 0.2)
        self.assertEqual(
            ClientConfig.from_mapping({**BASE_CONFIG, "gga_output_interval": 5}).gga_output_rate_hz,
            0.2,
        )
        self.assertAlmostEqual(
            ClientConfig.from_mapping({**BASE_CONFIG, "gga_output_rate_hz": 1.0 / 60.0}).gga_output_rate_hz,
            1.0 / 60.0,
        )
        self.assertEqual(
            ClientConfig.from_mapping({**BASE_CONFIG, "gga_output_rate_hz": 20}).gga_output_rate_hz,
            20,
        )
        for rate in (0, 20.1):
            with self.subTest(rate=rate), self.assertRaisesRegex(ConfigError, "20 Hz"):
                ClientConfig.from_mapping({**BASE_CONFIG, "gga_output_rate_hz": rate})
        with self.assertRaises(ConfigError):
            ClientConfig.from_mapping({**BASE_CONFIG, "gga_output_interval": 0})

    def test_plain_auth_requires_explicit_acknowledgement(self) -> None:
        config = {**BASE_CONFIG, "username": "user", "password": "secret"}
        with self.assertRaisesRegex(ConfigError, "TLS"):
            ClientConfig.from_mapping(config)

        accepted = ClientConfig.from_mapping({**config, "allow_insecure_auth": True})
        self.assertTrue(accepted.allow_insecure_auth)

    def test_tls_values_are_strict_booleans(self) -> None:
        with self.assertRaisesRegex(ConfigError, "tls"):
            ClientConfig.from_mapping({**BASE_CONFIG, "tls": "false"})

    def test_header_injection_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            ClientConfig.from_mapping({**BASE_CONFIG, "cors_host": "localhost\r\nX-Evil: yes"})
        with self.assertRaises(ConfigError):
            ClientConfig.from_mapping({**BASE_CONFIG, "mountpoint": "TEST\r\nX-Evil: yes"})


class ConfigStoreCompatibilityTests(unittest.TestCase):
    def test_failed_replace_preserves_previous_config_and_releases_new_secret(self) -> None:
        config = ClientConfig.from_mapping({**BASE_CONFIG, "username": "demo", "password": "secret", "tls": True})
        self.assertNotIn("secret", repr(config))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{}", encoding="utf-8")
            with (
                patch("k922_ntrip.config.protect_password", return_value="new-reference"),
                patch("k922_ntrip.config.delete_password") as cleanup,
                patch.object(Path, "replace", side_effect=PermissionError),
                self.assertRaises(PermissionError),
            ):
                ConfigStore(path).save(config)
            cleanup.assert_called_once_with(str(path.resolve()), "new-reference")
            self.assertEqual(path.read_text(), "{}")
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_caps_a_saved_rate_above_current_board_registration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({**BASE_CONFIG, "gga_output_rate_hz": 100}),
                encoding="utf-8",
            )

            loaded = ConfigStore(path).load()

            self.assertEqual(loaded.gga_output_rate_hz, 20)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["gga_output_rate_hz"], 20)


class TlsErrorTests(unittest.TestCase):
    def test_plaintext_ntrip_port_gets_actionable_tls_guidance(self) -> None:
        error = ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number")

        message = format_tls_error(error)

        self.assertIn("该端口返回的不是 TLS 数据", message)
        self.assertIn("取消勾选 TLS", message)


class GgaValidationTests(unittest.TestCase):
    def test_valid_gga_with_and_without_checksum(self) -> None:
        body = "GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,"
        self.assertTrue(is_gga(nmea_sentence(body)))
        self.assertTrue(is_gga(f"${body}".encode("ascii")))

    def test_bad_checksum_or_coordinates_are_rejected(self) -> None:
        valid = nmea_sentence("GNGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,")
        self.assertFalse(is_gga(valid[:-2] + b"00"))
        self.assertFalse(
            is_gga(b"$GPGGA,123519,nan,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,")
        )
        self.assertFalse(
            is_gga(b"$GPGGA,123519,9960.000,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,")
        )
        self.assertFalse(
            is_gga(b"$GPGGA,123519,4807.038,X,01131.000,E,1,08,0.9,545.4,M,46.9,M,,")
        )

    def test_synthetic_gga_uses_decimal_coordinates_and_valid_checksum(self) -> None:
        gga = build_synthetic_gga("31.2304", "121.4737")
        self.assertTrue(is_gga(gga.rstrip(b"\r\n")))
        self.assertIn(b"3113.82400,N,12128.42200,E", gga)

        southern = build_synthetic_gga(-31.2304, -121.4737)
        self.assertIn(b"3113.82400,S,12128.42200,W", southern)
        with self.assertRaises(ValueError):
            build_synthetic_gga("91", "121.4")


class ChunkedDecoderTests(unittest.TestCase):
    def test_decodes_split_chunks_and_empty_trailers(self) -> None:
        decoder = ChunkedDecoder()
        self.assertEqual(decoder.feed(b"5\r\nhe"), b"")
        self.assertEqual(decoder.feed(b"llo\r\n0\r\n\r\n"), b"hello")
        self.assertTrue(decoder.finished)

    def test_rejects_oversized_chunks_and_data_after_terminal_chunk(self) -> None:
        decoder = ChunkedDecoder()
        with self.assertRaisesRegex(ConnectionError, "1 MiB"):
            decoder.feed(b"100001\r\n")

        decoder = ChunkedDecoder()
        with self.assertRaisesRegex(ConnectionError, "after the final"):
            decoder.feed(b"0\r\n\r\nextra")


class ConnectionCancellationTests(unittest.TestCase):
    def test_partial_headers_share_one_deadline(self) -> None:
        sock = Mock()
        sock.gettimeout.return_value = 1.0
        sock.fileno.return_value = 1
        sock.recv.return_value = b"HTTP"
        with patch("k922_ntrip.protocol.time.monotonic", side_effect=[0, 0.4, 1.1]):
            with self.assertRaises(TimeoutError):
                read_ntrip_response(sock)
        sock.recv.assert_called_once()
        sock.settimeout.assert_called_with(1.0)

    def test_stop_after_tcp_connect_closes_socket_before_request(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        config = ClientConfig.from_mapping(
            {
                **BASE_CONFIG,
                "cors_port": listener.getsockname()[1],
                "connect_timeout": 1,
            }
        )
        cancel_event = threading.Event()
        socket_updates: list[socket.socket | None] = []

        def register_socket(active_socket: socket.socket | None) -> None:
            socket_updates.append(active_socket)
            if active_socket is not None:
                cancel_event.set()

        try:
            with self.assertRaises(ConnectionAbortedError):
                connect_caster(config, cancel_event, register_socket)
            self.assertIsNotNone(socket_updates[0])
            self.assertIsNone(socket_updates[-1])
        finally:
            listener.close()


@unittest.skipUnless(os.name == "nt", "DPAPI persistence test requires Windows")
class ConfigStoreTests(unittest.TestCase):
    def test_legacy_plaintext_password_is_migrated_to_dpapi(self) -> None:
        legacy_config = {
            **BASE_CONFIG,
            "username": "demo-user",
            "password": "demo-password",
            "tls": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(legacy_config), encoding="utf-8")

            store = ConfigStore(path)
            loaded = store.load()

            self.assertEqual(loaded.password, "demo-password")
            saved_text = path.read_text(encoding="utf-8")
            self.assertNotIn("demo-password", saved_text)
            self.assertIn("password_protected", saved_text)
            self.assertEqual(store.load().password, "demo-password")


if __name__ == "__main__":
    unittest.main()
