from __future__ import annotations

import unittest

from k922_ntrip.rtcm import crc24q, format_hex_dump, parse_rtcm3_frames
try:
    from .support import build_rtcm_frame
except ImportError:
    from support import build_rtcm_frame


class RtcmFrameTests(unittest.TestCase):
    def test_parses_message_type_station_id_and_crc(self) -> None:
        frame = build_rtcm_frame(message_type=1005, station_id=42)

        parsed = parse_rtcm3_frames(b"noise" + frame)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].offset, 5)
        self.assertEqual(parsed[0].message_type, 1005)
        self.assertEqual(parsed[0].message_name, "参考站坐标")
        self.assertEqual(parsed[0].station_id, 42)
        self.assertTrue(parsed[0].crc_valid)

    def test_reports_crc_failure_without_dropping_the_frame(self) -> None:
        frame = bytearray(build_rtcm_frame(message_type=1077, station_id=7))
        frame[-1] ^= 0x01

        parsed = parse_rtcm3_frames(bytes(frame))

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].message_name, "GPS MSM7")
        self.assertEqual(parsed[0].station_id, 7)
        self.assertFalse(parsed[0].crc_valid)

    def test_ignores_incomplete_and_bad_reserved_headers(self) -> None:
        frame = build_rtcm_frame()
        incomplete = frame[:-1]
        bad_reserved = b"\xd3\x80\x00" + frame

        self.assertEqual(parse_rtcm3_frames(incomplete), ())
        parsed = parse_rtcm3_frames(bad_reserved)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].offset, 3)

    def test_false_preamble_does_not_hide_later_valid_frame(self) -> None:
        frame = build_rtcm_frame()
        prefixed = b"\xd3\x03\xff" + frame
        parsed = parse_rtcm3_frames(prefixed)
        self.assertEqual([(f.offset, f.crc_valid) for f in parsed], [(3, True)])

    def test_crc24q_known_check_value_and_hex_dump_limit(self) -> None:
        self.assertEqual(crc24q(b"123456789"), 0xCDE703)
        preview = format_hex_dump(bytes(range(32)), max_bytes=16)

        self.assertIn("0000", preview)
        self.assertIn("0E 0F", preview)
        self.assertIn("预览截断", preview)


if __name__ == "__main__":
    unittest.main()
