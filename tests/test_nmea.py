from __future__ import annotations

import unittest

from k922_ntrip.nmea import parse_gga, parse_gphpr


def nmea_sentence(body: str) -> bytes:
    checksum = 0
    for byte in body.encode("ascii"):
        checksum ^= byte
    return f"${body}*{checksum:02X}".encode("ascii")


class GgaParsingTests(unittest.TestCase):
    def test_parses_position_quality_and_solution_details(self) -> None:
        position = parse_gga(
            nmea_sentence("GPGGA,123519,4807.038,N,01131.000,E,4,18,0.7,545.4,M,46.9,M,,")
        )

        self.assertIsNotNone(position)
        self.assertTrue(position.has_fix)
        self.assertAlmostEqual(position.latitude_degrees, 48.1173)
        self.assertAlmostEqual(position.longitude_degrees, 11.5166666667)
        self.assertEqual(position.fix_quality_name, "RTK 固定解")
        self.assertEqual(position.satellites, 18)
        self.assertEqual(position.hdop, 0.7)
        self.assertEqual(position.altitude_meters, 545.4)

    def test_reports_no_fix_without_reusing_old_coordinates(self) -> None:
        position = parse_gga(nmea_sentence("GNGGA,123520,,,,,0,00,,,M,,M,,"))

        self.assertIsNotNone(position)
        self.assertFalse(position.has_fix)
        self.assertEqual(position.fix_quality_name, "无效解")
        self.assertIsNone(position.latitude_degrees)
        self.assertIsNone(position.longitude_degrees)

    def test_rejects_bad_checksum_and_out_of_range_position(self) -> None:
        valid = nmea_sentence("GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,,M,,")
        self.assertIsNone(parse_gga(valid[:-2] + b"00"))
        self.assertIsNone(
            parse_gga(nmea_sentence("GPGGA,123519,9960.000,N,01131.000,E,1,08,0.9,545.4,M,,M,,"))
        )


class AttitudeParsingTests(unittest.TestCase):
    def test_parses_gphpr_attitude_and_solution_details(self) -> None:
        attitude = parse_gphpr(
            nmea_sentence("GPHPR,082602.00,77.94,51.30,0.00,4,40,0.00,0004")
        )

        self.assertIsNotNone(attitude)
        self.assertEqual(attitude.fix_quality_name, "RTK 固定解")
        self.assertAlmostEqual(attitude.heading_degrees, 77.94)
        self.assertAlmostEqual(attitude.pitch_degrees, 51.30)
        self.assertAlmostEqual(attitude.roll_degrees, 0.0)
        self.assertEqual(attitude.satellites, 40)
        self.assertEqual(attitude.station_id, "0004")

    def test_rejects_invalid_gphpr_checksum_and_angles(self) -> None:
        valid = nmea_sentence("GPHPR,082602.00,77.94,51.30,0.00,4,40,0.00,0004")
        self.assertIsNone(parse_gphpr(valid[:-2] + b"00"))
        self.assertIsNone(
            parse_gphpr(nmea_sentence("GPHPR,082602.00,361,51.30,0.00,4,40,0.00,0004"))
        )


if __name__ == "__main__":
    unittest.main()
