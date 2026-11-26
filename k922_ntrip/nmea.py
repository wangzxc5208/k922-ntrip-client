"""Typed parsing helpers for NMEA sentences used by the client."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


FIX_QUALITY_NAMES = {
    0: "无效解",
    1: "单点定位",
    2: "码差分定位",
    4: "RTK 固定解",
    5: "RTK 浮点解",
    6: "组合导航解",
    7: "人工固定位置",
    8: "超宽巷解",
    9: "SBAS 解",
    15: "PPP 收敛",
    16: "PPP 未收敛",
}


@dataclass(frozen=True)
class GgaPosition:
    latitude_degrees: float | None
    longitude_degrees: float | None
    fix_quality: int
    satellites: int | None
    hdop: float | None
    altitude_meters: float | None
    utc_time: str

    @property
    def has_fix(self) -> bool:
        return (
            self.fix_quality > 0
            and self.latitude_degrees is not None
            and self.longitude_degrees is not None
        )

    @property
    def fix_quality_name(self) -> str:
        return FIX_QUALITY_NAMES.get(self.fix_quality, f"定位模式 {self.fix_quality}")


@dataclass(frozen=True)
class AttitudeSolution:
    heading_degrees: float
    pitch_degrees: float
    roll_degrees: float
    fix_quality: int
    satellites: int | None
    correction_age_seconds: float | None
    station_id: str

    @property
    def fix_quality_name(self) -> str:
        return FIX_QUALITY_NAMES.get(self.fix_quality, f"定位模式 {self.fix_quality}")


def _optional_float(value: str) -> float | None:
    if not value:
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _parse_coordinate(value: str, hemisphere: str, *, latitude: bool) -> float | None:
    degree_digits = 2 if latitude else 3
    expected_hemispheres = ("N", "S") if latitude else ("E", "W")
    if hemisphere not in expected_hemispheres:
        return None
    if not re.fullmatch(rf"\d{{{degree_digits + 2}}}(?:\.\d+)?", value):
        return None

    nmea_value = float(value)
    degrees = int(nmea_value // 100)
    minutes = nmea_value - degrees * 100
    maximum = 90 if latitude else 180
    if minutes >= 60 or degrees > maximum or (degrees == maximum and minutes > 0):
        return None

    decimal_degrees = degrees + minutes / 60.0
    return -decimal_degrees if hemisphere in ("S", "W") else decimal_degrees


def parse_gga(sentence: bytes | str) -> GgaPosition | None:
    """Parse a structurally valid GGA sentence, including a no-fix status report."""
    try:
        line = sentence.decode("ascii") if isinstance(sentence, bytes) else sentence
    except UnicodeDecodeError:
        return None
    line = line.strip()
    if not line.startswith("$") or len(line) > 128 or any(ord(char) < 0x20 for char in line):
        return None
    try:
        line.encode("ascii")
    except UnicodeEncodeError:
        return None

    sentence_body, separator, checksum = line.partition("*")
    if separator:
        if not re.fullmatch(r"[0-9A-Fa-f]{2}", checksum):
            return None
        expected = 0
        for byte in sentence_body[1:].encode("ascii"):
            expected ^= byte
        if expected != int(checksum, 16):
            return None

    fields = sentence_body[1:].split(",")
    if (
        len(fields) < 7
        or len(fields[0]) != 5
        or not fields[0][:2].isalnum()
        or fields[0][2:] != "GGA"
    ):
        return None
    try:
        fix_quality = int(fields[6])
    except ValueError:
        return None
    if fix_quality < 0:
        return None

    latitude = longitude = None
    if fix_quality > 0:
        if len(fields) < 6:
            return None
        latitude = _parse_coordinate(fields[2], fields[3], latitude=True)
        longitude = _parse_coordinate(fields[4], fields[5], latitude=False)
        if latitude is None or longitude is None:
            return None

    satellites = None
    if len(fields) > 7 and fields[7]:
        try:
            satellites = int(fields[7])
        except ValueError:
            pass
        if satellites is not None and not 0 <= satellites <= 99:
            satellites = None

    hdop = _optional_float(fields[8]) if len(fields) > 8 else None
    if hdop is not None and hdop < 0:
        hdop = None
    altitude = _optional_float(fields[9]) if len(fields) > 9 else None

    return GgaPosition(
        latitude_degrees=latitude,
        longitude_degrees=longitude,
        fix_quality=fix_quality,
        satellites=satellites,
        hdop=hdop,
        altitude_meters=altitude,
        utc_time=fields[1] if len(fields) > 1 else "",
    )


def parse_gphpr(sentence: bytes | str) -> AttitudeSolution | None:
    """Parse SinoGNSS GPHPR heading, pitch, roll and solution quality."""
    try:
        line = sentence.decode("ascii") if isinstance(sentence, bytes) else sentence
    except UnicodeDecodeError:
        return None
    line = line.strip()
    if not line.startswith("$") or len(line) > 128 or any(ord(char) < 0x20 for char in line):
        return None
    try:
        line.encode("ascii")
    except UnicodeEncodeError:
        return None

    sentence_body, separator, checksum = line.partition("*")
    if separator:
        if not re.fullmatch(r"[0-9A-Fa-f]{2}", checksum):
            return None
        expected = 0
        for byte in sentence_body[1:].encode("ascii"):
            expected ^= byte
        if expected != int(checksum, 16):
            return None

    fields = sentence_body[1:].split(",")
    if len(fields) < 6 or len(fields[0]) != 5 or fields[0][2:] != "HPR":
        return None
    heading = _optional_float(fields[2])
    pitch = _optional_float(fields[3])
    roll = _optional_float(fields[4])
    try:
        fix_quality = int(fields[5])
    except ValueError:
        return None
    if (
        heading is None
        or pitch is None
        or roll is None
        or not 0.0 <= heading <= 360.0
        or not -90.0 <= pitch <= 90.0
        or not -90.0 <= roll <= 90.0
        or fix_quality < 0
    ):
        return None

    satellites = None
    if len(fields) > 6 and fields[6]:
        try:
            satellites = int(fields[6])
        except ValueError:
            pass
        if satellites is not None and not 0 <= satellites <= 99:
            satellites = None

    correction_age = _optional_float(fields[7]) if len(fields) > 7 else None
    if correction_age is not None and correction_age < 0:
        correction_age = None

    return AttitudeSolution(
        heading_degrees=heading,
        pitch_degrees=pitch,
        roll_degrees=roll,
        fix_quality=fix_quality,
        satellites=satellites,
        correction_age_seconds=correction_age,
        station_id=fields[8] if len(fields) > 8 else "",
    )
