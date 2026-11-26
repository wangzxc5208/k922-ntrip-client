from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QScrollArea

from k922_ntrip.account_test import AccountTestResult, build_synthetic_gga
from k922_ntrip.config import ClientConfig
from k922_ntrip.nmea import AttitudeSolution, parse_gga
from k922_ntrip.service import ServiceEvent
from k922_ntrip.ui.main_window import MainWindow
from k922_ntrip.ui.rtcm_preview_dialog import RtcmPreviewDialog
from k922_ntrip.ui.theme import APP_STYLESHEET
try:
    from .support import LocalResponseCaster, build_rtcm_frame
except ImportError:
    from support import LocalResponseCaster, build_rtcm_frame


class MainWindowLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setStyle("Fusion")
        cls.application.setStyleSheet(APP_STYLESHEET)

    def test_security_notice_expands_config_without_clipping_or_overlap(self) -> None:
        previous_appdata = os.environ.get("APPDATA")
        with tempfile.TemporaryDirectory() as directory:
            os.environ["APPDATA"] = directory
            window = MainWindow()
            try:
                window.resize(1440, 950)
                window.username_edit.setText("demo-user")
                window.password_edit.setText("demo-password")
                window.pages.setCurrentIndex(0)
                self.assertFalse(window.windowIcon().isNull())
                self.assertEqual(window.test_account_button.text(), "测试账号")
                self.assertIn("再次点击可停止", window.test_account_button.toolTip())
                window.show()
                self.application.processEvents()

                self.assertTrue(window.security_notice.isVisible())
                self.assertEqual(
                    [window.pages.tabText(i) for i in range(window.pages.count())],
                    ["连接配置", "板卡功能", "运行监控", "运行日志"],
                )
                self.assertTrue(window.attitude_rate_spin.isEnabled())
                window.attitude_rate_spin.setValue(10.0)
                self.assertNotIn("log headinga", window.board_command_text.text())
                window.heading_mode_combo.setCurrentIndex(
                    window.heading_mode_combo.findData("enable")
                )
                self.assertIn("log headinga ontime 0.1", window.board_command_text.text())
                card_rect = window.config_card.rect()
                children = (
                    window.host_edit,
                    window.mountpoint_edit,
                    window.test_lat_edit,
                    window.test_lon_edit,
                    window.password_edit,
                    window.security_notice,
                    window.test_account_button,
                    window.config_path_label,
                )
                child_rects: dict[str, QRect] = {}
                for child in children:
                    position = child.mapTo(window.config_card, QPoint(0, 0))
                    rect = QRect(position, child.size())
                    child_rects[child.objectName() or child.__class__.__name__] = rect
                    self.assertTrue(card_rect.contains(rect), f"{child} extends outside the config card")

                notice_rect = child_rects["SecurityNotice"]
                test_button_rect = child_rects["SecondaryButton"]
                self.assertLess(notice_rect.bottom(), test_button_rect.top())
                self.assertGreaterEqual(window.baud_combo.height(), 38)
                scroll_area = window.centralWidget()
                self.assertIsInstance(scroll_area, QScrollArea)
                page = scroll_area.widget()
                for i, card in enumerate((
                    window.config_card, window.board_settings_card, window.runtime_card, window.log_card,
                )):
                    window.pages.setCurrentIndex(i)
                    self.application.processEvents()
                    position = card.mapTo(page, QPoint(0, 0))
                    bounds = QRect(position, card.size())
                    self.assertTrue(page.rect().contains(bounds), f"{card} extends outside the scrollable page")
                window.pages.setCurrentIndex(1)
                self.application.processEvents()
                gga_rate_bounds = QRect(
                    window.gga_rate_spin.mapTo(window.board_settings_card, QPoint(0, 0)),
                    window.gga_rate_spin.size(),
                )
                self.assertTrue(window.board_settings_card.rect().contains(gga_rate_bounds))
                window.pages.setCurrentIndex(2)
                self.application.processEvents()
                position_bounds = QRect(
                    window.position_card.mapTo(window.runtime_card, QPoint(0, 0)),
                    window.position_card.size(),
                )
                self.assertTrue(window.runtime_card.rect().contains(position_bounds))
                attitude_bounds = QRect(
                    window.attitude_card.mapTo(window.runtime_card, QPoint(0, 0)),
                    window.attitude_card.size(),
                )
                self.assertTrue(window.runtime_card.rect().contains(attitude_bounds))
            finally:
                window.close()
                self.application.processEvents()
                if previous_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = previous_appdata

    def test_live_gga_updates_board_position_and_no_fix_state(self) -> None:
        previous_appdata = os.environ.get("APPDATA")
        with tempfile.TemporaryDirectory() as directory:
            os.environ["APPDATA"] = directory
            window = MainWindow()
            try:
                gga = build_synthetic_gga("31.2304", "121.4737").strip()
                position = parse_gga(gga)
                self.assertIsNotNone(position)
                window._handle_service_event(
                    ServiceEvent(
                        "gga",
                        {
                            "sentence": gga.decode("ascii"),
                            "position": position,
                        },
                    )
                )

                self.assertEqual(window.position_latitude_value.text(), "31.2304000° N")
                self.assertEqual(window.position_longitude_value.text(), "121.4737000° E")
                self.assertEqual(window.position_quality_badge.text(), "单点定位")
                self.assertIn("12 颗", window.position_details_label.text())
                window._update_attitude(AttitudeSolution(48.0, 0.0, 0.0, 4, 12, 1.0, "1"), None)
                self.assertTrue(window._position_timeout.isActive())
                window._position_timeout.timeout.emit()
                self.assertEqual(window.position_quality_badge.text(), "定位已过期")
                self.assertEqual(window.attitude_heading_value.text(), "48.00°")
                window._attitude_timeout.timeout.emit()
                self.assertEqual(window.attitude_heading_value.text(), "—")
                window._update_position(position, None)
                window._set_state("stopped")
                self.assertEqual(window.position_latitude_value.text(), "—")
                self.assertEqual(window.position_quality_badge.text(), "链路已关闭")

                no_fix = parse_gga(b"$GPGGA,123520,,,,,0,00,,,M,,M,,")
                self.assertIsNotNone(no_fix)
                window._handle_service_event(
                    ServiceEvent("gga", {"sentence": "$GPGGA,123520,,,,,0,00,,,M,,M,,", "position": no_fix})
                )
                self.assertEqual(window.position_quality_badge.text(), "无效解")
                self.assertEqual(window.position_latitude_value.text(), "—")
                self.assertEqual(window.gga_step.detail_label.text(), "未获得有效定位")
            finally:
                window.close()
                self.application.processEvents()
                if previous_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = previous_appdata

    def test_account_button_verifies_caster_without_serial_or_saving_config(self) -> None:
        correction_frames = (
            build_rtcm_frame(1005, 42),
            build_rtcm_frame(1074, 42),
            build_rtcm_frame(1084, 42),
        )
        corrections = b"".join(correction_frames)
        caster = LocalResponseCaster(
            b"ICY 200 OK\r\n" + correction_frames[0],
            stream_chunks=correction_frames[1:],
            stream_interval=0.05,
        )
        previous_appdata = os.environ.get("APPDATA")
        with tempfile.TemporaryDirectory() as directory:
            os.environ["APPDATA"] = directory
            window = MainWindow()
            try:
                window.host_edit.setText("127.0.0.1")
                window.port_edit.setText(str(caster.port))
                window.mountpoint_edit.setText("TEST")
                window.username_edit.setText("demo-user")
                window.password_edit.setText("demo-password")
                window.allow_insecure_check.setChecked(True)
                window.gga_rate_spin.setValue(20)
                self.assertIn("log gpgga ontime 0.05", window.board_command_text.text())
                window.gga_rate_spin.setValue(9)
                self.assertIn("log gpgga ontime 0.11111111", window.board_command_text.text())
                with patch("k922_ntrip.account_test.GGA_UPLOAD_INTERVAL_SECONDS", 0.05):
                    window.test_account_button.click()
                    worker = window.account_test_worker
                    self.assertEqual(worker.config.gga_output_rate_hz, 9)
                    deadline = time.monotonic() + 3
                    while (
                        worker
                        and (
                            worker.progress.gga_sent_count < 3
                            or worker.progress.bytes_received < len(corrections)
                        )
                        and time.monotonic() < deadline
                    ):
                        self.application.processEvents()
                        time.sleep(0.01)
                    self.application.processEvents()

                    self.assertIsNotNone(worker)
                    self.assertTrue(worker.isRunning())
                    self.assertGreaterEqual(worker.progress.gga_sent_count, 3)
                    self.assertEqual(worker.progress.bytes_received, len(corrections))
                    self.assertEqual(window.test_account_button.text(), "停止测试")
                    self.assertTrue(window.preview_data_button.isEnabled())
                    self.assertEqual(window.status_pill.text(), "账号测试中")
                    self.assertIn("不打开板卡串口", window.serial_step.detail_label.text())
                    self.assertIn("合成 GGA 已发送", window.gga_step.detail_label.text())
                    self.assertIn(f"{len(corrections):,} B，已校验 RTCM", window.cors_step.detail_label.text())
                    self.assertEqual(window.bytes_metric.title_label.text(), "测试接收总量")
                    self.assertEqual(window.bytes_metric.value_label.text(), str(len(corrections)))
                    window.test_account_button.click()

                    deadline = time.monotonic() + 3
                    while window.account_test_worker is worker and time.monotonic() < deadline:
                        self.application.processEvents()
                        time.sleep(0.01)
                    self.application.processEvents()

                self.assertIsNone(window.account_test_worker)
                self.assertEqual(window.test_account_button.text(), "测试账号")
                self.assertIn(f"共收到 {len(corrections)} 字节", window.statusBar().currentMessage())
                self.assertEqual(window.status_pill.text(), "测试已停止 · 收到 RTCM")
                self.assertIn("测试结束", window.cors_step.detail_label.text())
                self.assertEqual(window.bytes_metric.title_label.text(), "测试接收总量")
                self.assertEqual(window._last_account_test_result.data_preview, corrections)
                dialog = RtcmPreviewDialog(window._last_account_test_result, window)
                self.assertEqual(dialog.frame_table.rowCount(), 3)
                self.assertEqual(dialog.frame_table.item(0, 1).text(), "1005 · 参考站坐标")
                self.assertEqual(dialog.frame_table.item(0, 5).text(), "通过")
                dialog.close()
                self.assertIn(b"Authorization: Basic ", caster.request)
                self.assertIn(b"Ntrip-GGA: $GPGGA,", caster.request)
                self.assertIn(b"Connection: keep-alive", caster.request)
                self.assertGreaterEqual(caster.extra_data.count(b"\r\n"), 2)
                self.assertFalse((Path(directory) / "K922 NTRIP Client" / "config.json").exists())
                self.assertIsNone(caster.error)
            finally:
                if window.account_test_worker and window.account_test_worker.isRunning():
                    window.account_test_worker.request_cancel()
                    window.account_test_worker.wait(1000)
                window.close()
                self.application.processEvents()
                caster.close()
                if previous_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = previous_appdata

    def test_config_round_trip_and_transport_consent(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, APPDATA=directory):
            window = MainWindow()
            self.addCleanup(window.close)
            config = ClientConfig(
                "COM99", 115200, "caster.example", 2101, "TEST",
                username="test", password="test", allow_insecure_auth=True,
                serial_timeout=1.4, connect_timeout=14.0, reconnect_delay=6.5, command_delay=0.55,
            )
            window._apply_config(config)
            self.assertEqual(window._read_config(), config)
            window.host_edit.setText("another.example")
            self.assertFalse(window.allow_insecure_check.isChecked())

    def test_new_test_clears_old_sample_and_unverified_bytes_have_no_success_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, APPDATA=directory):
            window = MainWindow()
            self.addCleanup(window.close)
            previous = AccountTestResult(True, 20, "", data_preview=b"old", rtcm_confirmed=True)
            window._last_account_test_result = previous
            window.preview_data_button.setEnabled(True)
            window.host_edit.setText("caster.example")
            window.mountpoint_edit.setText("TEST")
            with patch("k922_ntrip.ui.account_test_worker.AccountTestWorker.start"):
                window._test_account()
            self.assertIsNone(window._last_account_test_result)
            self.assertFalse(window.preview_data_button.isEnabled())
            window._show_account_test_state(AccountTestResult(True, 18, ""))
            self.assertEqual(window.status_pill.text(), "已认证 · 未确认 RTCM")
            self.assertEqual(window.status_pill.property("tone"), "amber")
            window._show_account_test_state(AccountTestResult(True, 18, "读连接失败", stream_error=True))
            self.assertEqual(window.status_pill.property("tone"), "red")


if __name__ == "__main__":
    unittest.main()
