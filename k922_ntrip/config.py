"""Configuration model, validation, and persistence for the K922 NTRIP client."""

from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .secrets import delete_password, protect_password, reveal_password


class ConfigError(ValueError):
    """Raised when connection settings are missing or invalid."""


MIN_GGA_OUTPUT_RATE_HZ = 1.0 / 60.0
MAX_GGA_OUTPUT_RATE_HZ = 20.0
MIN_ATTITUDE_OUTPUT_RATE_HZ = 0.1
MAX_ATTITUDE_OUTPUT_RATE_HZ = 20.0
INS_MODES = {"preserve", "enable", "disable"}
HEADING_MODES = {"preserve", "enable", "disable"}


def _strict_bool(raw: dict[str, Any], key: str, default: bool = False) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} 必须是 true 或 false")
    return value


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


@dataclass(frozen=True)
class ClientConfig:
    serial_port: str
    baudrate: int
    cors_host: str
    cors_port: int
    mountpoint: str
    gga_output_rate_hz: float = 0.2
    ins_mode: str = "preserve"
    imu_axis_type: int = 1
    dr_leverarm_x_m: float = 0.0
    dr_leverarm_y_m: float = 0.0
    dr_leverarm_z_m: float = 0.0
    dr_init_speed_mps: float = 1.0
    dr_timeout_seconds: int = 30
    heading_mode: str = "preserve"
    attitude_output_rate_hz: float = 1.0
    username: str = ""
    password: str = field(default="", repr=False)
    tls: bool = False
    allow_insecure_auth: bool = False
    ntrip_version: str = "2.0"
    serial_timeout: float = 0.2
    connect_timeout: float = 10.0
    reconnect_delay: float = 3.0
    command_delay: float = 0.3

    @classmethod
    def from_mapping(
        cls,
        raw: dict[str, Any],
        *,
        enforce_transport_security: bool = True,
    ) -> "ClientConfig":
        required = ("serial_port", "baudrate", "cors_host", "cors_port", "mountpoint")
        labels = {
            "serial_port": "RS232 串口",
            "baudrate": "波特率",
            "cors_host": "CORS 主机",
            "cors_port": "CORS 端口",
            "mountpoint": "挂载点",
        }
        missing = [labels[key] for key in required if key not in raw or raw[key] in (None, "")]
        if missing:
            raise ConfigError("请填写：" + "、".join(missing))

        tls = _strict_bool(raw, "tls")
        allow_insecure_auth = _strict_bool(raw, "allow_insecure_auth")
        try:
            if "gga_output_rate_hz" in raw:
                gga_output_rate_hz = float(raw["gga_output_rate_hz"])
            else:
                legacy_interval = float(raw.get("gga_output_interval", 5))
                if not math.isfinite(legacy_interval) or legacy_interval <= 0:
                    raise ConfigError("旧配置中的板卡 GGA 输出间隔无效")
                gga_output_rate_hz = 1.0 / legacy_interval
            config = cls(
                serial_port=str(raw["serial_port"]).strip(),
                baudrate=int(raw["baudrate"]),
                cors_host=str(raw["cors_host"]).strip(),
                cors_port=int(raw["cors_port"]),
                mountpoint=str(raw["mountpoint"]).strip().lstrip("/"),
                gga_output_rate_hz=gga_output_rate_hz,
                ins_mode=str(raw.get("ins_mode", "preserve")),
                imu_axis_type=int(raw.get("imu_axis_type", 1)),
                dr_leverarm_x_m=float(raw.get("dr_leverarm_x_m", 0.0)),
                dr_leverarm_y_m=float(raw.get("dr_leverarm_y_m", 0.0)),
                dr_leverarm_z_m=float(raw.get("dr_leverarm_z_m", 0.0)),
                dr_init_speed_mps=float(raw.get("dr_init_speed_mps", 1.0)),
                dr_timeout_seconds=int(raw.get("dr_timeout_seconds", 30)),
                heading_mode=str(raw.get("heading_mode", "preserve")),
                attitude_output_rate_hz=float(raw.get("attitude_output_rate_hz", 1.0)),
                username=str(raw.get("username", "")).strip(),
                password=str(raw.get("password", "")),
                tls=tls,
                allow_insecure_auth=allow_insecure_auth,
                ntrip_version=str(raw.get("ntrip_version", "2.0")),
                serial_timeout=float(raw.get("serial_timeout", 0.2)),
                connect_timeout=float(raw.get("connect_timeout", 10.0)),
                reconnect_delay=float(raw.get("reconnect_delay", 3.0)),
                command_delay=float(raw.get("command_delay", 0.3)),
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ConfigError(f"配置格式不正确：{exc}") from exc

        if not config.serial_port or _has_control_characters(config.serial_port):
            raise ConfigError("RS232 串口名称无效")
        if not 1 <= config.baudrate <= 4_000_000:
            raise ConfigError("串口波特率范围为 1–4000000")
        if (
            not math.isfinite(config.gga_output_rate_hz)
            or not MIN_GGA_OUTPUT_RATE_HZ <= config.gga_output_rate_hz <= MAX_GGA_OUTPUT_RATE_HZ
        ):
            raise ConfigError("当前板卡 GGA 输出频率范围为 0.0167–20 Hz")
        if config.ins_mode not in INS_MODES:
            raise ConfigError("惯导启动方式无效")
        if config.heading_mode not in HEADING_MODES:
            raise ConfigError("定向输出方式无效")
        if not 1 <= config.imu_axis_type <= 8:
            raise ConfigError("IMU 轴向类型必须为 1–8")
        leverarms = (config.dr_leverarm_x_m, config.dr_leverarm_y_m, config.dr_leverarm_z_m)
        if any(not math.isfinite(value) or not -20.0 <= value <= 20.0 for value in leverarms):
            raise ConfigError("惯导杆臂范围为 -20–20 米，且必须是有限数值")
        if not math.isfinite(config.dr_init_speed_mps) or not 0.1 <= config.dr_init_speed_mps <= 20.0:
            raise ConfigError("惯导初始化速度门限范围为 0.1–20 米/秒")
        if not 0 <= config.dr_timeout_seconds <= 3600:
            raise ConfigError("GNSS 失锁后的惯导推算时长范围为 0–3600 秒")
        if (
            not math.isfinite(config.attitude_output_rate_hz)
            or not MIN_ATTITUDE_OUTPUT_RATE_HZ
            <= config.attitude_output_rate_hz
            <= MAX_ATTITUDE_OUTPUT_RATE_HZ
        ):
            raise ConfigError("定向/姿态输出频率范围为 0.1–20 Hz")
        if not config.cors_host or _has_control_characters(config.cors_host):
            raise ConfigError("请填写有效的 CORS 主机地址")
        if ":" in config.cors_host:
            try:
                ipaddress.IPv6Address(config.cors_host)
            except ipaddress.AddressValueError as exc:
                raise ConfigError("IPv6 主机请填写不带方括号的有效地址") from exc
        elif not re.fullmatch(r"[A-Za-z0-9.-]+", config.cors_host) or ".." in config.cors_host:
            raise ConfigError("CORS 主机只能包含字母、数字、点和连字符")
        if not 1 <= config.cors_port <= 65535:
            raise ConfigError("CORS 端口范围为 1–65535")
        if (
            not config.mountpoint
            or not re.fullmatch(r"[A-Za-z0-9._~-]+", config.mountpoint)
            or config.mountpoint in (".", "..")
        ):
            raise ConfigError("挂载点只能包含字母、数字、点、下划线、连字符和波浪号")
        if _has_control_characters(config.username) or ":" in config.username:
            raise ConfigError("用户名不能包含控制字符或冒号")
        if config.ntrip_version not in ("1.0", "2.0"):
            raise ConfigError("NTRIP 版本仅支持 1.0 或 2.0")
        if bool(config.username) != bool(config.password):
            raise ConfigError("用户名和密码需要同时填写，或同时留空")
        if enforce_transport_security and config.username and not config.tls and not config.allow_insecure_auth:
            raise ConfigError("当前未启用 TLS。请启用 TLS，或勾选明文传输风险确认")

        timeouts = {
            "串口超时": config.serial_timeout,
            "连接超时": config.connect_timeout,
            "重连间隔": config.reconnect_delay,
            "串口命令间隔": config.command_delay,
        }
        if any(not math.isfinite(value) for value in timeouts.values()):
            raise ConfigError("超时和间隔必须是有限数值")
        if config.connect_timeout <= 0 or config.serial_timeout <= 0:
            raise ConfigError("超时时间配置无效")
        if config.reconnect_delay < 0 or config.command_delay < 0:
            raise ConfigError("重连间隔和串口命令间隔不能小于 0")
        return config

    @classmethod
    def from_file(cls, path: Path) -> "ClientConfig":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"找不到配置文件：{path}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ConfigError(f"JSON 配置格式错误：{exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError("配置文件顶层必须是 JSON 对象")

        raw = dict(raw)
        context = str(path.resolve())
        if "password_protected" in raw:
            if "password_env" in raw:
                raise ConfigError("配置文件不能同时指定受保护密码和 password_env")
            if raw.get("password"):
                raise ConfigError("配置文件不能同时包含明文密码和受保护密码")
            try:
                raw["password"] = reveal_password(str(raw.pop("password_protected")), context)
            except RuntimeError as exc:
                raise ConfigError(str(exc)) from exc
        elif "password_env" in raw:
            if raw.get("password"):
                raise ConfigError("配置文件不能同时包含 password 和 password_env")
            env_name = raw.pop("password_env")
            if not isinstance(env_name, str) or not env_name:
                raise ConfigError("password_env 必须是环境变量名称")
            if env_name not in os.environ:
                raise ConfigError(f"未设置 CORS 密码环境变量：{env_name}")
            raw["password"] = os.environ[env_name]
        elif raw.get("password"):
            raise ConfigError("配置文件禁止保存明文密码，请使用 password_env")
        return cls.from_mapping(raw)

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


def default_config_path() -> Path:
    """Use the current user's app-data directory instead of the install folder."""
    app_data = os.environ.get("APPDATA")
    if app_data:
        return Path(app_data) / "K922 NTRIP Client" / "config.json"
    return Path.home() / ".config" / "k922-ntrip-client" / "config.json"


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()

    def load(self) -> ClientConfig | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ConfigError(f"JSON 配置格式错误：{exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError("配置文件顶层必须是 JSON 对象")

        raw = dict(raw)
        context = str(self.path.resolve())
        has_protected_password = "password_protected" in raw
        if "password_env" in raw:
            raise ConfigError("桌面配置不能引用 password_env，请在界面中重新输入密码")
        has_legacy_password = bool(raw.get("password")) and not has_protected_password
        capped_gga_rate = False
        if "gga_output_rate_hz" in raw:
            try:
                saved_gga_rate = float(raw["gga_output_rate_hz"])
            except (TypeError, ValueError, OverflowError):
                saved_gga_rate = 0.0
            if math.isfinite(saved_gga_rate) and saved_gga_rate > MAX_GGA_OUTPUT_RATE_HZ:
                raw["gga_output_rate_hz"] = MAX_GGA_OUTPUT_RATE_HZ
                capped_gga_rate = True
        if has_protected_password:
            if raw.get("password"):
                raise ConfigError("配置文件同时包含明文密码和受保护密码")
            try:
                raw["password"] = reveal_password(str(raw.pop("password_protected")), context)
            except RuntimeError as exc:
                raise ConfigError(str(exc)) from exc

        config = ClientConfig.from_mapping(raw, enforce_transport_security=False)
        if has_legacy_password or capped_gga_rate:
            # Migrate the previous desktop format immediately; the user still has
            # to acknowledge cleartext network transport before starting a link.
            # Also cap settings created before this board's registration limit was
            # known so that the remaining connection settings stay available.
            self.save(config)
        return config

    def save(self, config: ClientConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        context = str(self.path.resolve())
        mapping = config.to_mapping()
        password = mapping.pop("password", "")

        old_reference = None
        if self.path.exists():
            try:
                old_mapping = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(old_mapping, dict):
                    old_reference = old_mapping.get("password_protected")
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                pass

        new_reference = None
        if password:
            try:
                new_reference = protect_password(password, context)
                mapping["password_protected"] = new_reference
            except RuntimeError as exc:
                raise ConfigError(f"无法安全保存密码：{exc}") from exc

        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=self.path.name + ".", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(mapping, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            temporary.replace(self.path)
        except Exception:
            if new_reference:
                try:
                    delete_password(context, new_reference)
                except RuntimeError:
                    pass
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

        if old_reference and old_reference != new_reference:
            try:
                delete_password(context, str(old_reference))
            except RuntimeError:
                # The new config is already committed; a stale keyring entry is
                # harmless and can be removed manually if the backend is locked.
                pass
