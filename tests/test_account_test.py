from __future__ import annotations

import base64
import ssl
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from k922_ntrip.account_test import build_synthetic_gga, verify_account
from k922_ntrip.config import ClientConfig
from k922_ntrip.protocol import CasterRejectedError
from k922_ntrip.ui.account_test_worker import AccountTestWorker
try:
    from .support import LocalResponseCaster, build_rtcm_frame
except ImportError:
    from support import LocalResponseCaster, build_rtcm_frame


def client_config(port: int) -> ClientConfig:
    return ClientConfig.from_mapping(
        {
            "serial_port": "ACCOUNT_TEST_ONLY",
            "baudrate": 115200,
            "cors_host": "127.0.0.1",
            "cors_port": port,
            "mountpoint": "TEST",
            "username": "test-user",
            "password": "test-password",
            "tls": False,
            "allow_insecure_auth": True,
            "ntrip_version": "2.0",
            "connect_timeout": 2,
        }
    )


class AccountTestTests(unittest.TestCase):
    def test_tls_protocol_mismatch_is_explained_to_the_user(self) -> None:
        worker = AccountTestWorker(
            client_config(2101),
            build_synthetic_gga("31.2304", "121.4737"),
        )
        with patch(
            "k922_ntrip.ui.account_test_worker.verify_account",
            side_effect=ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number"),
        ):
            worker.run()

        self.assertIn("账号测试失败", worker.result.message)
        self.assertIn("取消勾选 TLS", worker.result.message)

    def test_authenticates_mountpoint_and_counts_chunked_data_with_synthetic_gga(self) -> None:
        corrections = build_rtcm_frame()
        chunks = f"{len(corrections):X}\r\n".encode("ascii") + corrections + b"\r\n0\r\n\r\n"
        response = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + chunks
        caster = LocalResponseCaster(response)
        try:
            result = verify_account(
                client_config(caster.port),
                build_synthetic_gga("31.2304", "121.4737"),
            )

            expected_auth = base64.b64encode(b"test-user:test-password")
            self.assertTrue(result.authenticated)
            self.assertTrue(result.rtcm_confirmed)
            self.assertEqual(result.bytes_received, len(corrections))
            self.assertEqual(result.data_preview, corrections)
            self.assertEqual(len(result.rtcm_frames), 1)
            self.assertTrue(result.rtcm_frames[0].crc_valid)
            self.assertEqual(result.rtcm_frames[0].message_type, 1005)
            self.assertEqual(result.rtcm_frames[0].station_id, 42)
            self.assertIn(b"Authorization: Basic " + expected_auth, caster.request)
            self.assertIn(b"Ntrip-GGA: $GPGGA,", caster.request)
            self.assertIsNone(caster.error)
        finally:
            caster.close()

    def test_sends_post_response_gga_on_icy_fallback(self) -> None:
        caster = LocalResponseCaster(b"ICY 200 OK\r\n")
        try:
            with (
                patch("k922_ntrip.account_test.DATA_PROBE_SECONDS", 0.13),
                patch("k922_ntrip.account_test.GGA_UPLOAD_INTERVAL_SECONDS", 0.05),
                patch("k922_ntrip.account_test.datetime") as clock,
            ):
                clock.now.return_value = datetime(2026, 1, 1, 12, 34, 56, tzinfo=timezone.utc)
                old_time = datetime(2000, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
                result = verify_account(
                    client_config(caster.port),
                    build_synthetic_gga("31.2304", "121.4737", now=old_time),
                )

            self.assertTrue(result.authenticated)
            self.assertEqual(result.bytes_received, 0)
            self.assertIn("已发送合成 GGA", result.message)
            self.assertIn(b"Ntrip-GGA:", caster.request)
            deadline = time.monotonic() + 1.0
            while caster.extra_data.count(b"\r\n") < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertGreaterEqual(caster.extra_data.count(b"\r\n"), 2)
            sentences = caster.extra_data.splitlines()
            self.assertEqual(sentences[0].split(b",")[1], b"000000")
            self.assertEqual(sentences[1].split(b",")[1], b"123456")
            self.assertIn(result.last_gga.strip(), sentences[1:])
        finally:
            caster.close()

    def test_text_response_is_not_a_mountpoint(self) -> None:
        for mime in (b"gnss/sourcetable", b"text/html; charset=utf-8"):
            caster = LocalResponseCaster(b"HTTP/1.1 200 OK\r\nContent-Type: " + mime + b"\r\n\r\n")
            try:
                with self.subTest(mime=mime), self.assertRaises(CasterRejectedError):
                    verify_account(client_config(caster.port), build_synthetic_gga(31, 121))
            finally:
                caster.close()

    def test_raw_bytes_do_not_confirm_rtcm_and_content_length_ends_probe(self) -> None:
        caster = LocalResponseCaster(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello")
        try:
            result = verify_account(client_config(caster.port), build_synthetic_gga(31, 121), continuous=True)
            self.assertTrue(result.authenticated)
            self.assertFalse(result.rtcm_confirmed)
            self.assertFalse(result.stream_error)
            self.assertEqual(result.bytes_received, 5)
            self.assertIn("服务端已结束数据流", result.message)
        finally:
            caster.close()

    def test_recovers_first_valid_frame_after_preview_limit_and_split_reads(self) -> None:
        frame = build_rtcm_frame()
        caster = LocalResponseCaster(
            b"ICY 200 OK\r\n" + b"?" * 5000 + frame[:4],
            stream_chunks=(frame[4:],), stream_interval=0.02,
        )
        try:
            result = verify_account(client_config(caster.port), build_synthetic_gga(31, 121))
            self.assertEqual(result.bytes_received, 5000 + len(frame))
            self.assertTrue(result.rtcm_confirmed)
            self.assertEqual(result.data_preview, frame)
        finally:
            caster.close()

    def test_stop_preserves_authentication_and_final_counters(self) -> None:
        frame = build_rtcm_frame()
        caster = LocalResponseCaster(b"ICY 200 OK\r\n" + frame)
        cancel = threading.Event()
        try:
            result = verify_account(
                client_config(caster.port), build_synthetic_gga(0, 0), cancel_event=cancel,
                on_progress=lambda progress: cancel.set() if progress.rtcm_confirmed else None,
                continuous=True,
            )
            self.assertTrue(result.stopped)
            self.assertFalse(result.stream_error)
            self.assertEqual(result.bytes_received, len(frame))
            self.assertTrue(result.rtcm_confirmed)
        finally:
            caster.close()

    def test_rejected_credentials_raise_caster_rejection(self) -> None:
        caster = LocalResponseCaster(
            b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n"
        )
        try:
            with self.assertRaises(CasterRejectedError):
                verify_account(
                    client_config(caster.port),
                    build_synthetic_gga("31.2304", "121.4737"),
                )
            self.assertIsNone(caster.error)
        finally:
            caster.close()


if __name__ == "__main__":
    unittest.main()
