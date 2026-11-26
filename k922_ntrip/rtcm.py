"""Small RTCM 3.x stream inspection helpers."""

from __future__ import annotations

from dataclasses import dataclass


RTCM3_PREAMBLE = 0xD3
RTCM3_CRC_POLYNOMIAL = 0x1864CFB
MAX_RTCM3_FRAME_BYTES = 1023 + 6
MAX_DISPLAYED_FRAMES = 128

_MESSAGE_NAMES = {
    1001: "GPS L1 观测值",
    1002: "GPS L1 扩展观测值",
    1003: "GPS L1/L2 观测值",
    1004: "GPS L1/L2 扩展观测值",
    1005: "参考站坐标",
    1006: "参考站坐标（含天线高度）",
    1007: "天线描述",
    1008: "天线描述与序列号",
    1009: "GLONASS L1 观测值",
    1010: "GLONASS L1 扩展观测值",
    1011: "GLONASS L1/L2 观测值",
    1012: "GLONASS L1/L2 扩展观测值",
    1013: "系统参数",
    1019: "GPS 星历",
    1020: "GLONASS 星历",
    1033: "接收机与天线描述",
    1042: "北斗星历",
    1045: "Galileo F/NAV 星历",
    1046: "Galileo I/NAV 星历",
    1230: "GLONASS L1/L2 码相位偏差",
}
_MSM_CONSTELLATIONS = {
    107: "GPS",
    108: "GLONASS",
    109: "Galileo",
    110: "SBAS",
    111: "QZSS",
    112: "北斗",
    113: "NavIC",
}


@dataclass(frozen=True, slots=True)
class RtcmFrameInfo:
    offset: int
    message_type: int | None
    message_name: str
    payload_length: int
    crc_valid: bool
    station_id: int | None

    @property
    def frame_length(self) -> int:
        return self.payload_length + 6


def crc24q(data: bytes) -> int:
    """Compute the CRC-24Q used by RTCM 3.x frames."""
    remainder = 0
    for byte in data:
        remainder ^= byte << 16
        for _ in range(8):
            remainder <<= 1
            if remainder & 0x1000000:
                remainder ^= RTCM3_CRC_POLYNOMIAL
    return remainder & 0xFFFFFF


def _message_name(message_type: int | None) -> str:
    if message_type is None:
        return "消息类型不完整"
    if message_type in _MESSAGE_NAMES:
        return _MESSAGE_NAMES[message_type]
    constellation = _MSM_CONSTELLATIONS.get(message_type // 10)
    msm_level = message_type % 10
    if constellation and 1 <= msm_level <= 7:
        return f"{constellation} MSM{msm_level}"
    return f"RTCM {message_type}"


def _station_id(message_type: int | None, payload: bytes) -> int | None:
    has_station_id = (
        message_type is not None
        and (
            1001 <= message_type <= 1013
            or message_type == 1033
            or (message_type // 10 in _MSM_CONSTELLATIONS and 1 <= message_type % 10 <= 7)
            or message_type == 1230
        )
    )
    if not has_station_id or len(payload) < 3:
        return None
    return ((payload[1] & 0x0F) << 8) | payload[2]


def parse_rtcm3_frames(data: bytes, *, max_frames: int = MAX_DISPLAYED_FRAMES) -> tuple[RtcmFrameInfo, ...]:
    """Find complete RTCM3 frames in a byte sample and report their CRC status."""
    frames: list[RtcmFrameInfo] = []
    cursor = 0
    while len(frames) < max_frames:
        start = data.find(bytes((RTCM3_PREAMBLE,)), cursor)
        if start < 0 or len(data) - start < 3:
            break
        if data[start + 1] & 0xFC:
            cursor = start + 1
            continue

        payload_length = ((data[start + 1] & 0x03) << 8) | data[start + 2]
        frame_end = start + payload_length + 6
        if frame_end > len(data):
            cursor = start + 1
            continue

        frame = data[start:frame_end]
        payload = frame[3:-3]
        message_type = (
            ((payload[0] << 4) | (payload[1] >> 4))
            if len(payload) >= 2
            else None
        )
        expected_crc = int.from_bytes(frame[-3:], "big")
        frames.append(
            RtcmFrameInfo(
                offset=start,
                message_type=message_type,
                message_name=_message_name(message_type),
                payload_length=payload_length,
                crc_valid=crc24q(frame[:-3]) == expected_crc,
                station_id=_station_id(message_type, payload),
            )
        )
        cursor = frame_end if frames[-1].crc_valid else start + 1
    return tuple(frames)


def format_hex_dump(data: bytes, *, max_bytes: int = 4096) -> str:
    """Render a bounded binary sample as an offset-based hex dump."""
    sample = data[:max_bytes]
    lines: list[str] = []
    for offset in range(0, len(sample), 16):
        row = sample[offset : offset + 16]
        hex_part = " ".join(f"{byte:02X}" for byte in row)
        text_part = "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in row)
        lines.append(f"{offset:04X}  {hex_part:<47}  |{text_part}|")
    if len(data) > len(sample):
        lines.append(f"… 预览截断；样本共 {len(data)} 字节，仅显示前 {len(sample)} 字节")
    return "\n".join(lines) or "（没有可显示的数据）"
