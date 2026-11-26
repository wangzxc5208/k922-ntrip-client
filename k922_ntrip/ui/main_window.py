"""Main operational dashboard for the K922 NTRIP client."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QDoubleValidator, QIcon, QIntValidator
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - dependency warning is shown by the worker
    list_ports = None

from ..config import ClientConfig, ConfigError, ConfigStore
from ..account_test import AccountTestProgress, AccountTestResult, build_synthetic_gga
from ..nmea import AttitudeSolution, GgaPosition
from ..service import ServiceEvent, freshness_seconds
from .account_test_worker import AccountTestWorker
from .resources import asset_path
from .rtcm_preview_dialog import RtcmPreviewDialog
from .theme import ACCENTS, THEMES, build_stylesheet
from .worker import ConnectionWorker


STATE_PRESENTATION = {
    "idle": ("未启动", "neutral"),
    "starting": ("准备中", "blue"),
    "waiting_gga": ("等待定位", "amber"),
    "connecting": ("连接中", "blue"),
    "connected": ("链路运行中", "green"),
    "reconnecting": ("自动重连", "amber"),
    "stopping": ("正在停止", "amber"),
    "stopped": ("已停止", "neutral"),
    "failed": ("连接失败", "red"),
}

LOG_COLORS = {
    "DEBUG": "#8293a5",
    "INFO": "#c3d0dc",
    "WARNING": "#edc17e",
    "ERROR": "#f28f9a",
}
LIGHT_LOG_COLORS = {
    "DEBUG": "#687b8d",
    "INFO": "#405568",
    "WARNING": "#925b0b",
    "ERROR": "#b6293a",
}


def field(caption: str, control: QWidget) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    label = QLabel(caption)
    label.setObjectName("FieldLabel")
    layout.addWidget(label)
    layout.addWidget(control)
    return container


def make_card(title: str, hint: str = "", trailing: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 17, 18, 18)
    layout.setSpacing(14)
    header = QHBoxLayout()
    header.setSpacing(10)
    title_stack = QVBoxLayout()
    title_stack.setSpacing(4)
    heading = QLabel(title)
    heading.setObjectName("SectionTitle")
    title_stack.addWidget(heading)
    if hint:
        description = QLabel(hint)
        description.setObjectName("SectionHint")
        description.setWordWrap(True)
        title_stack.addWidget(description)
    header.addLayout(title_stack, 1)
    if trailing is not None:
        header.addWidget(trailing, 0, Qt.AlignmentFlag.AlignTop)
    layout.addLayout(header)
    return card, layout


class MetricCard(QFrame):
    def __init__(self, title: str, value: str, suffix: str) -> None:
        super().__init__()
        self.setObjectName("MetricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 13, 15, 13)
        layout.setSpacing(5)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("MetricTitle")
        value_row = QHBoxLayout()
        value_row.setSpacing(7)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")
        self.suffix_label = QLabel(suffix)
        self.suffix_label.setObjectName("MetricSuffix")
        value_row.addWidget(self.value_label, 0, Qt.AlignmentFlag.AlignBottom)
        value_row.addWidget(self.suffix_label, 0, Qt.AlignmentFlag.AlignBottom)
        value_row.addStretch(1)
        layout.addWidget(self.title_label)
        layout.addLayout(value_row)


class StatusStep(QWidget):
    def __init__(self, title: str, detail: str) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(11)
        self.dot = QLabel()
        self.dot.setObjectName("StepDot")
        self.dot.setFixedSize(10, 10)
        self.dot.setProperty("tone", "neutral")
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(3)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("StepTitle")
        self.detail_label = QLabel(detail)
        self.detail_label.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_label.setObjectName("StepDetail")
        self.detail_label.setWordWrap(True)
        text.addWidget(self.title_label)
        text.addWidget(self.detail_label)
        row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)

    def set_detail(self, detail: str, tone: str = "neutral") -> None:
        self.detail_label.setText(detail)
        self.dot.setProperty("tone", tone)
        self.dot.style().unpolish(self.dot)
        self.dot.style().polish(self.dot)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("K922 NTRIP Client")
        self.setWindowIcon(QIcon(str(asset_path("k922_ntrip.ico"))))
        self.setMinimumSize(640, 400)
        screen_size = self.screen().availableGeometry().size()
        self.resize(min(1440, screen_size.width() - 24), min(950, screen_size.height() - 48))
        self.store = ConfigStore()
        self._loaded_config: ClientConfig | None = None
        self.appearance_settings = QSettings("GNSS Tools", "K922 NTRIP Client")
        saved_theme = self.appearance_settings.value("appearance/theme", "dark", type=str)
        saved_accent = self.appearance_settings.value("appearance/accent", "mint", type=str)
        self.theme_id = saved_theme if saved_theme in THEMES else "dark"
        self.accent_id = saved_accent if saved_accent in ACCENTS else "mint"
        self._log_entries: list[tuple[str, str, datetime]] = []
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(self.theme_id, self.accent_id))
        self.worker: ConnectionWorker | None = None
        self.account_test_worker: AccountTestWorker | None = None
        self._last_account_test_result: AccountTestResult | None = None
        self.state = "idle"
        self._close_when_stopped = False
        self._position_timeout = QTimer(self)
        self._position_timeout.setSingleShot(True)
        self._position_timeout.timeout.connect(self._expire_position)
        self._attitude_timeout = QTimer(self)
        self._attitude_timeout.setSingleShot(True)
        self._attitude_timeout.timeout.connect(self._expire_attitude)
        self._build_ui()
        self._refresh_ports()
        self._load_saved_config()
        self._set_state("stopped", "客户端未运行")
        self._append_log("INFO", f"配置保存位置：{self.store.path}")

    def _build_ui(self) -> None:
        scroll_area = QScrollArea()
        scroll_area.setObjectName("PageScrollArea")
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidgetResizable(True)

        root = QWidget()
        root.setObjectName("Root")
        scroll_area.setWidget(root)
        self.setCentralWidget(scroll_area)
        page = QVBoxLayout(root)
        page.setContentsMargins(28, 22, 28, 22)
        page.setSpacing(15)

        page.addLayout(self._build_header())
        self.config_card, self.config_layout = make_card(
            "连接配置",
            "配置 K922 的 RS232 参数和 CORS 挂载点。启动前会自动保存当前配置。",
        )
        self.config_card.setMinimumWidth(620)
        self.config_card.setMinimumHeight(475)
        self.config_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._build_config_form()
        self.runtime_card, self.runtime_layout = make_card(
            "链路状态",
            "串口读取 GGA，CORS 下发 RTCM，数据经 RS232 回到板卡。",
        )
        self.runtime_card.setMinimumWidth(350)
        self.runtime_card.setMinimumHeight(440)
        self._build_runtime_panel()
        self.board_settings_card = self._build_board_settings_panel()

        self.pages = QTabWidget()
        self.pages.setObjectName("MainPages")

        monitor_page = QWidget()
        monitor_layout = QVBoxLayout(monitor_page)
        monitor_layout.setContentsMargins(14, 14, 14, 14)
        monitor_layout.setSpacing(14)
        monitor_layout.addLayout(self._build_metrics())
        monitor_layout.addWidget(self.runtime_card)
        monitor_layout.addStretch(1)

        connection_page = QWidget()
        connection_layout = QVBoxLayout(connection_page)
        connection_layout.setContentsMargins(14, 14, 14, 14)
        connection_layout.setSpacing(14)
        connection_layout.addWidget(self.config_card)
        connection_layout.addStretch(1)

        board_page = QWidget()
        board_layout = QVBoxLayout(board_page)
        board_layout.setContentsMargins(14, 14, 14, 14)
        board_layout.setSpacing(14)
        board_layout.addWidget(self.board_settings_card)
        board_layout.addStretch(1)

        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        log_layout.setContentsMargins(14, 14, 14, 14)
        log_layout.setSpacing(14)
        self.log_card = self._build_log_panel()
        log_layout.addWidget(self.log_card, 1)

        self.pages.addTab(connection_page, "连接配置")
        self.pages.addTab(board_page, "板卡功能")
        self.pages.addTab(monitor_page, "运行监控")
        self.pages.addTab(log_page, "运行日志")
        page.addWidget(self.pages, 1)

        self._set_controls_enabled(True)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(13)
        brand = QLabel("K")
        brand.setObjectName("BrandMark")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setFixedSize(42, 42)
        title_stack = QVBoxLayout()
        title_stack.setSpacing(3)
        eyebrow = QLabel("GNSS CORRECTION LINK  ·  K922")
        eyebrow.setObjectName("Eyebrow")
        title = QLabel("差分数据连接台")
        title.setObjectName("PageTitle")
        subtitle = QLabel("管理 CORS 接入、GGA 上行与 RTCM 回传")
        subtitle.setObjectName("Subtitle")
        title_stack.addWidget(eyebrow)
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        header.addWidget(brand, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(title_stack, 1)

        self.appearance_button = QPushButton("外观")
        self.appearance_button.setObjectName("AppearanceButton")
        self.appearance_button.setMenu(self._build_appearance_menu())
        header.addWidget(self.appearance_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self._update_appearance_tooltip()

        self.status_pill = QLabel("未启动")
        self.status_pill.setObjectName("StatusPill")
        self.status_pill.setProperty("tone", "neutral")
        self.status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.start_button = QPushButton("▶  启动链路")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.setMinimumWidth(136)
        self.start_button.clicked.connect(self._start_client)
        self.stop_button = QPushButton("■  停止")
        self.stop_button.setObjectName("StopButton")
        self.stop_button.clicked.connect(self._stop_client)
        self.stop_button.setEnabled(False)
        header.addWidget(self.start_button, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.stop_button, 0, Qt.AlignmentFlag.AlignVCenter)
        return header

    def _build_appearance_menu(self) -> QMenu:
        menu = QMenu(self)
        theme_menu = menu.addMenu("界面主题")
        theme_group = QActionGroup(theme_menu)
        theme_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}
        for theme_id, label in THEMES.items():
            action = QAction(label, theme_group)
            theme_group.addAction(action)
            action.setCheckable(True)
            action.setChecked(theme_id == self.theme_id)
            action.triggered.connect(
                lambda checked, value=theme_id: self._set_appearance(theme=value)
            )
            theme_menu.addAction(action)
            self._theme_actions[theme_id] = action

        accent_menu = menu.addMenu("强调色")
        accent_group = QActionGroup(accent_menu)
        accent_group.setExclusive(True)
        self._accent_actions: dict[str, QAction] = {}
        for accent_id, label in ACCENTS.items():
            action = QAction(label, accent_group)
            accent_group.addAction(action)
            action.setCheckable(True)
            action.setChecked(accent_id == self.accent_id)
            action.triggered.connect(
                lambda checked, value=accent_id: self._set_appearance(accent=value)
            )
            accent_menu.addAction(action)
            self._accent_actions[accent_id] = action
        return menu

    def _set_appearance(self, *, theme: str | None = None, accent: str | None = None) -> None:
        if theme in THEMES:
            self.theme_id = theme
        if accent in ACCENTS:
            self.accent_id = accent
        self.appearance_settings.setValue("appearance/theme", self.theme_id)
        self.appearance_settings.setValue("appearance/accent", self.accent_id)
        self.appearance_settings.sync()
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(self.theme_id, self.accent_id))
        for theme_id, action in self._theme_actions.items():
            action.setChecked(theme_id == self.theme_id)
        for accent_id, action in self._accent_actions.items():
            action.setChecked(accent_id == self.accent_id)
        if hasattr(self, "log_view"):
            self.log_view.clear()
            for level, message, timestamp in self._log_entries:
                self._render_log_entry(level, message, timestamp)
        self._update_appearance_tooltip()

    def _update_appearance_tooltip(self) -> None:
        self.appearance_button.setToolTip(
            f"主题：{THEMES[self.theme_id]}；强调色：{ACCENTS[self.accent_id]}。设置会自动保存。"
        )

    def _build_metrics(self) -> QHBoxLayout:
        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.rate_metric = MetricCard("RTCM 下行速率", "0.0", "KB/s")
        self.bytes_metric = MetricCard("累计写入板卡", "0", "B")
        self.runtime_metric = MetricCard("本次运行时长", "00:00", "")
        metrics.addWidget(self.rate_metric)
        metrics.addWidget(self.bytes_metric)
        metrics.addWidget(self.runtime_metric)
        return metrics

    def _build_config_form(self) -> None:
        self.serial_combo = QComboBox()
        self.serial_combo.setMinimumWidth(180)
        self.serial_combo.setMinimumHeight(38)
        self.refresh_ports_button = QPushButton("↻")
        self.refresh_ports_button.setToolTip("重新扫描可用串口")
        self.refresh_ports_button.setFixedWidth(40)
        self.refresh_ports_button.clicked.connect(self._refresh_ports)
        serial_control = QWidget()
        serial_layout = QHBoxLayout(serial_control)
        serial_layout.setContentsMargins(0, 0, 0, 0)
        serial_layout.setSpacing(6)
        serial_layout.addWidget(self.serial_combo, 1)
        serial_layout.addWidget(self.refresh_ports_button)

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.setMinimumHeight(38)
        self.baud_combo.lineEdit().setValidator(QIntValidator(1, 4_000_000, self.baud_combo))
        for baud in (9600, 19200, 38400, 57600, 115200, 230400, 460800):
            self.baud_combo.addItem(str(baud), baud)
        self.baud_combo.setCurrentText("115200")

        self.host_edit = QLineEdit()
        self.host_edit.setMinimumHeight(38)
        self.host_edit.setPlaceholderText("例如 cors.example.com")
        self.port_edit = QLineEdit("2101")
        self.port_edit.setMinimumHeight(38)
        self.port_edit.setValidator(QIntValidator(1, 65535, self))
        self.mountpoint_edit = QLineEdit()
        self.mountpoint_edit.setMinimumHeight(38)
        self.mountpoint_edit.setPlaceholderText("CORS 分配的挂载点")
        self.test_lat_edit = QLineEdit("31.2304")
        self.test_lat_edit.setMinimumHeight(34)
        latitude_validator = QDoubleValidator(-90.0, 90.0, 7, self.test_lat_edit)
        latitude_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.test_lat_edit.setValidator(latitude_validator)
        self.test_lat_edit.setToolTip("合成 GGA 测试纬度，十进制度；默认是上海示例位置。")
        self.test_lon_edit = QLineEdit("121.4737")
        self.test_lon_edit.setMinimumHeight(34)
        longitude_validator = QDoubleValidator(-180.0, 180.0, 7, self.test_lon_edit)
        longitude_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.test_lon_edit.setValidator(longitude_validator)
        self.test_lon_edit.setToolTip("合成 GGA 测试经度，十进制度；请按 CORS 覆盖区域调整。")
        self.username_edit = QLineEdit()
        self.username_edit.setMinimumHeight(38)
        self.username_edit.setPlaceholderText("服务商账号")
        self.password_edit = QLineEdit()
        self.password_edit.setMinimumHeight(38)
        self.password_edit.setPlaceholderText("服务商密码")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_toggle = QPushButton("显示")
        self.password_toggle.setObjectName("TextButton")
        self.password_toggle.setFixedWidth(50)
        self.password_toggle.clicked.connect(self._toggle_password)
        password_control = QWidget()
        password_layout = QHBoxLayout(password_control)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(3)
        password_layout.addWidget(self.password_edit, 1)
        password_layout.addWidget(self.password_toggle)

        self.version_combo = QComboBox()
        self.version_combo.setMinimumHeight(38)
        self.version_combo.addItem("NTRIP 2.0", "2.0")
        self.version_combo.addItem("NTRIP 1.0", "1.0")
        self.version_combo.setMinimumWidth(92)
        self.tls_check = QCheckBox("TLS")
        self.tls_check.setToolTip(
            "仅在服务商明确提供 TLS 的接入端口时勾选。\n"
            "若出现 WRONG_VERSION_NUMBER，通常表示此端口返回的是明文 NTRIP，请关闭 TLS。"
        )
        self.allow_insecure_check = QCheckBox("我确认账号会通过未加密 TCP 传输")
        self.allow_insecure_check.setObjectName("SecurityAcknowledgement")
        security_notice = QFrame()
        security_notice.setObjectName("SecurityNotice")
        security_layout = QHBoxLayout(security_notice)
        security_layout.setContentsMargins(11, 8, 11, 8)
        security_layout.setSpacing(10)
        security_text = QLabel("安全提示：")
        security_text.setObjectName("SecurityWarning")
        security_text.setFixedWidth(58)
        security_detail = QLabel("未启用 TLS 时，账号和密码不会加密。")
        security_detail.setObjectName("SecurityWarning")
        security_layout.addWidget(security_text)
        security_layout.addWidget(security_detail, 1)
        security_layout.addWidget(self.allow_insecure_check)
        self.security_notice = security_notice
        self.security_notice.hide()

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(11)
        form.addWidget(field("RS232 串口", serial_control), 0, 0, 1, 2)
        form.addWidget(field("波特率", self.baud_combo), 0, 2)
        form.addWidget(field("CORS 主机", self.host_edit), 1, 0, 1, 2)
        form.addWidget(field("端口", self.port_edit), 1, 2)
        options = QWidget()
        options_layout = QHBoxLayout(options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(7)
        options_layout.addWidget(self.version_combo)
        options_layout.addWidget(self.tls_check)
        form.addWidget(field("挂载点", self.mountpoint_edit), 2, 0, 1, 2)
        form.addWidget(field("协议与安全", options), 2, 2)
        form.addWidget(field("用户名", self.username_edit), 3, 0)
        form.addWidget(field("密码", password_control), 3, 1, 1, 2)
        test_position = QWidget()
        test_position_layout = QHBoxLayout(test_position)
        test_position_layout.setContentsMargins(0, 0, 0, 0)
        test_position_layout.setSpacing(8)
        latitude_label = QLabel("纬度 °")
        latitude_label.setObjectName("Muted")
        longitude_label = QLabel("经度 °")
        longitude_label.setObjectName("Muted")
        test_position_layout.addWidget(latitude_label)
        test_position_layout.addWidget(self.test_lat_edit, 1)
        test_position_layout.addWidget(longitude_label)
        test_position_layout.addWidget(self.test_lon_edit, 1)
        form.addWidget(field("账号测试合成 GGA 位置（默认上海示例）", test_position), 4, 0, 1, 3)
        self.gga_rate_spin = QDoubleSpinBox()
        self.gga_rate_spin.setRange(1.0 / 60.0, 20.0)
        self.gga_rate_spin.setDecimals(4)
        self.gga_rate_spin.setSingleStep(0.1)
        self.gga_rate_spin.setValue(0.2)
        self.gga_rate_spin.setSuffix(" Hz")
        self.gga_rate_spin.setMinimumHeight(38)
        self.gga_rate_spin.setToolTip(
            "当前 REGLISTA 状态支持最高 20 Hz，对应 log gpgga ontime 0.05。"
            "CORS 上行仍固定每 5 秒一次。"
        )
        form.setColumnStretch(0, 2)
        form.setColumnStretch(1, 2)
        form.setColumnStretch(2, 1)
        self.config_layout.addLayout(form)
        self.config_layout.addWidget(self.security_notice)

        for edit in (self.host_edit, self.port_edit, self.username_edit, self.password_edit):
            edit.textChanged.connect(self._reset_transport_acknowledgement)
        self.tls_check.toggled.connect(self._reset_transport_acknowledgement)

        self.validation_label = QLabel("")
        self.validation_label.setTextFormat(Qt.TextFormat.PlainText)
        self.validation_label.setObjectName("ErrorText")
        self.validation_label.setWordWrap(True)
        self.validation_label.hide()
        self.config_layout.addWidget(self.validation_label)

        actions = QHBoxLayout()
        self.save_button = QPushButton("保存配置")
        self.save_button.clicked.connect(self._save_config)
        self.test_account_button = QPushButton("测试账号")
        self.test_account_button.setObjectName("SecondaryButton")
        self.test_account_button.setToolTip(
            "按上方坐标生成合成 GGA，每 5 秒发送并持续接收 RTCM；"
            "再次点击可停止，不打开串口。"
        )
        self.test_account_button.clicked.connect(self._test_account)
        self.config_path_label = QLabel("")
        self.config_path_label.setObjectName("Muted")
        self.config_path_label.setWordWrap(True)
        self.config_path_label.setToolTip(str(self.store.path))
        actions.addWidget(self.save_button)
        actions.addWidget(self.test_account_button)
        actions.addWidget(self.config_path_label, 1)
        self.config_layout.addLayout(actions)

    def _build_board_settings_panel(self) -> QFrame:
        card, layout = make_card(
            "板卡定位 · 定向 · 惯导",
            "启动链路时按所选策略配置 K922；CORS 的 GGA 上行周期仍固定为 5 秒。",
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(11)

        self.ins_mode_combo = QComboBox()
        self.ins_mode_combo.setMinimumHeight(38)
        self.ins_mode_combo.addItem("保持板卡现状", "preserve")
        self.ins_mode_combo.addItem("启用并配置 GNSS/INS", "enable")
        self.ins_mode_combo.addItem("关闭 GNSS/INS", "disable")

        self.heading_mode_combo = QComboBox()
        self.heading_mode_combo.setMinimumHeight(38)
        self.heading_mode_combo.addItem("保持板卡现状", "preserve")
        self.heading_mode_combo.addItem("输出双天线定向与姿态", "enable")
        self.heading_mode_combo.addItem("停止定向与姿态输出", "disable")

        self.imu_axis_combo = QComboBox()
        self.imu_axis_combo.setMinimumHeight(38)
        axis_options = (
            "1 · 正面朝上，Y 轴朝车头",
            "2 · 正面朝上，逆时针旋转 90°",
            "3 · 正面朝上，逆时针旋转 180°",
            "4 · 正面朝上，逆时针旋转 270°",
            "5 · 正面朝下，Y 轴朝车头",
            "6 · 正面朝下，逆时针旋转 90°",
            "7 · 正面朝下，逆时针旋转 180°",
            "8 · 正面朝下，逆时针旋转 270°",
        )
        for axis_type, description in enumerate(axis_options, start=1):
            self.imu_axis_combo.addItem(description, axis_type)

        def make_meter_spinbox() -> QDoubleSpinBox:
            control = QDoubleSpinBox()
            control.setRange(-20.0, 20.0)
            control.setDecimals(3)
            control.setSingleStep(0.01)
            control.setSuffix(" m")
            control.setMinimumHeight(38)
            return control

        self.leverarm_x_spin = make_meter_spinbox()
        self.leverarm_y_spin = make_meter_spinbox()
        self.leverarm_z_spin = make_meter_spinbox()
        for control in (self.leverarm_x_spin, self.leverarm_y_spin, self.leverarm_z_spin):
            control.setToolTip(
                "从 IMU 中心指向 GNSS 天线相位中心的杆臂，单位米；"
                "X 向车头为正、Y 向车右为正、Z 向下为正。"
            )
        leverarm = QWidget()
        leverarm_layout = QHBoxLayout(leverarm)
        leverarm_layout.setContentsMargins(0, 0, 0, 0)
        leverarm_layout.setSpacing(8)
        for axis_label, control in (
            ("X · 前", self.leverarm_x_spin),
            ("Y · 右", self.leverarm_y_spin),
            ("Z · 下", self.leverarm_z_spin),
        ):
            label = QLabel(axis_label)
            label.setObjectName("Muted")
            leverarm_layout.addWidget(label)
            leverarm_layout.addWidget(control, 1)

        self.ins_init_speed_spin = QDoubleSpinBox()
        self.ins_init_speed_spin.setRange(0.1, 20.0)
        self.ins_init_speed_spin.setDecimals(1)
        self.ins_init_speed_spin.setSingleStep(0.1)
        self.ins_init_speed_spin.setValue(1.0)
        self.ins_init_speed_spin.setSuffix(" m/s")
        self.ins_init_speed_spin.setMinimumHeight(38)
        self.ins_init_speed_spin.setToolTip("达到该速度后才满足惯导动态初始化的速度门限。")

        self.ins_timeout_spin = QSpinBox()
        self.ins_timeout_spin.setRange(0, 3600)
        self.ins_timeout_spin.setValue(30)
        self.ins_timeout_spin.setSuffix(" 秒")
        self.ins_timeout_spin.setMinimumHeight(38)
        self.ins_timeout_spin.setToolTip("GNSS 失锁后允许惯导继续推算的最长时间，范围 0–3600 秒。")

        self.attitude_rate_spin = QDoubleSpinBox()
        self.attitude_rate_spin.setRange(0.1, 20.0)
        self.attitude_rate_spin.setDecimals(1)
        self.attitude_rate_spin.setSingleStep(0.5)
        self.attitude_rate_spin.setValue(1.0)
        self.attitude_rate_spin.setSuffix(" Hz")
        self.attitude_rate_spin.setMinimumHeight(38)
        self.attitude_rate_spin.setToolTip(
            "可预设 0.1–20 Hz；只有将双天线模式设为“输出双天线定向与姿态”时才会下发。"
        )

        cors_interval_hint = QLabel(
            "板卡授权上限 20 Hz；CORS 上传 GGA 仍独立固定每 5 秒一次。"
        )
        cors_interval_hint.setObjectName("Muted")
        cors_interval_hint.setWordWrap(True)

        grid.addWidget(field("启动时 GNSS/INS", self.ins_mode_combo), 0, 0, 1, 2)
        grid.addWidget(field("双天线定向与姿态", self.heading_mode_combo), 0, 2, 1, 2)
        grid.addWidget(field("IMU 轴向", self.imu_axis_combo), 1, 0, 1, 2)
        grid.addWidget(field("定向/姿态输出频率", self.attitude_rate_spin), 1, 2, 1, 2)
        grid.addWidget(field("天线杆臂（IMU 中心 → 天线相位中心）", leverarm), 2, 0, 1, 4)
        grid.addWidget(field("惯导初始化速度门限", self.ins_init_speed_spin), 3, 0, 1, 2)
        grid.addWidget(field("GNSS 失锁后 INS 推算时长", self.ins_timeout_spin), 3, 2, 1, 2)
        grid.addWidget(field("板卡 GGA 输出频率", self.gga_rate_spin), 4, 0, 1, 2)
        grid.addWidget(cors_interval_hint, 4, 2, 1, 2, Qt.AlignmentFlag.AlignVCenter)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)

        hint = QLabel(
            "参数可以先预设；只有选择“启用并配置”或“输出双天线定向与姿态”时才会下发。"
            "启用惯导前请按实际安装方向选择 IMU 轴向并实测杆臂；在开阔环境等待 RTK 固定，"
            "再按初始化速度前进约 10 米完成动态初始化。"
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        command_strip = QFrame()
        command_strip.setObjectName("CommandStrip")
        commands_layout = QHBoxLayout(command_strip)
        commands_layout.setContentsMargins(12, 9, 12, 9)
        commands_layout.setSpacing(11)
        command_mark = QLabel("板卡配置预览")
        command_mark.setObjectName("FieldLabel")
        self.board_command_text = QLabel("")
        self.board_command_text.setObjectName("CommandText")
        self.board_command_text.setWordWrap(True)
        commands_layout.addWidget(command_mark)
        commands_layout.addWidget(self.board_command_text, 1)
        layout.addWidget(command_strip)

        self._board_settings_controls = (
            self.ins_mode_combo,
            self.heading_mode_combo,
            self.imu_axis_combo,
            self.leverarm_x_spin,
            self.leverarm_y_spin,
            self.leverarm_z_spin,
            self.ins_init_speed_spin,
            self.ins_timeout_spin,
            self.attitude_rate_spin,
            self.gga_rate_spin,
        )
        self.ins_mode_combo.currentIndexChanged.connect(self._update_board_settings_controls)
        self.heading_mode_combo.currentIndexChanged.connect(self._update_board_settings_controls)
        for control in (
            self.imu_axis_combo,
            self.leverarm_x_spin,
            self.leverarm_y_spin,
            self.leverarm_z_spin,
            self.ins_init_speed_spin,
            self.ins_timeout_spin,
            self.attitude_rate_spin,
            self.gga_rate_spin,
        ):
            if isinstance(control, QComboBox):
                control.currentIndexChanged.connect(self._update_board_command_preview)
            else:
                control.valueChanged.connect(self._update_board_command_preview)
        self._update_board_settings_controls()
        return card

    def _build_runtime_panel(self) -> None:
        state_box = QFrame()
        state_box.setObjectName("CommandStrip")
        state_layout = QVBoxLayout(state_box)
        state_layout.setContentsMargins(13, 13, 13, 13)
        state_layout.setSpacing(14)
        self.serial_step = StatusStep("板卡串口", "尚未打开")
        self.gga_step = StatusStep("GGA 定位上行", "等待板卡有效定位")
        self.cors_step = StatusStep("CORS 差分链路", "尚未连接")
        state_layout.addWidget(self.serial_step)
        state_layout.addWidget(self.gga_step)
        state_layout.addWidget(self.cors_step)
        self.runtime_layout.addWidget(state_box)

        self.position_card = QFrame()
        self.position_card.setObjectName("CommandStrip")
        position_layout = QVBoxLayout(self.position_card)
        position_layout.setContentsMargins(13, 12, 13, 12)
        position_layout.setSpacing(8)
        position_header = QHBoxLayout()
        position_heading = QLabel("板卡定位")
        position_heading.setObjectName("FieldLabel")
        self.position_quality_badge = QLabel("等待定位")
        self.position_quality_badge.setObjectName("StatusPill")
        self.position_quality_badge.setProperty("tone", "neutral")
        self.position_quality_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        position_header.addWidget(position_heading)
        position_header.addStretch(1)
        position_header.addWidget(self.position_quality_badge)
        coordinate_grid = QGridLayout()
        coordinate_grid.setContentsMargins(0, 0, 0, 0)
        coordinate_grid.setHorizontalSpacing(14)
        coordinate_grid.setVerticalSpacing(3)
        latitude_heading = QLabel("纬度")
        latitude_heading.setObjectName("Muted")
        longitude_heading = QLabel("经度")
        longitude_heading.setObjectName("Muted")
        self.position_latitude_value = QLabel("—")
        self.position_latitude_value.setObjectName("PositionValue")
        self.position_longitude_value = QLabel("—")
        self.position_longitude_value.setObjectName("PositionValue")
        for coordinate in (self.position_latitude_value, self.position_longitude_value):
            coordinate.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        coordinate_grid.addWidget(latitude_heading, 0, 0)
        coordinate_grid.addWidget(longitude_heading, 0, 1)
        coordinate_grid.addWidget(self.position_latitude_value, 1, 0)
        coordinate_grid.addWidget(self.position_longitude_value, 1, 1)
        coordinate_grid.setColumnStretch(0, 1)
        coordinate_grid.setColumnStretch(1, 1)
        self.position_details_label = QLabel("等待有效定位解")
        self.position_details_label.setObjectName("StepDetail")
        self.position_updated_label = QLabel("等待板卡定位数据")
        self.position_updated_label.setObjectName("Muted")
        position_layout.addLayout(position_header)
        position_layout.addLayout(coordinate_grid)
        position_layout.addWidget(self.position_details_label)
        position_layout.addWidget(self.position_updated_label)
        self.runtime_layout.addWidget(self.position_card)

        self.attitude_card = QFrame()
        self.attitude_card.setObjectName("CommandStrip")
        attitude_layout = QVBoxLayout(self.attitude_card)
        attitude_layout.setContentsMargins(13, 12, 13, 12)
        attitude_layout.setSpacing(8)
        attitude_header = QHBoxLayout()
        attitude_title = QLabel("双天线姿态")
        attitude_title.setObjectName("FieldLabel")
        self.attitude_status_badge = QLabel("等待姿态")
        self.attitude_status_badge.setObjectName("StatusPill")
        self.attitude_status_badge.setProperty("tone", "neutral")
        self.attitude_status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        attitude_header.addWidget(attitude_title)
        attitude_header.addStretch(1)
        attitude_header.addWidget(self.attitude_status_badge)

        attitude_values = QGridLayout()
        attitude_values.setContentsMargins(0, 0, 0, 0)
        attitude_values.setHorizontalSpacing(12)
        attitude_values.setVerticalSpacing(3)
        for column, (title, attribute) in enumerate(
            (("航向 · 真北", "heading"), ("俯仰", "pitch"), ("横滚", "roll"))
        ):
            caption = QLabel(title)
            caption.setObjectName("Muted")
            value = QLabel("—")
            value.setObjectName("PositionValue")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            setattr(self, f"attitude_{attribute}_value", value)
            attitude_values.addWidget(caption, 0, column)
            attitude_values.addWidget(value, 1, column)
            attitude_values.setColumnStretch(column, 1)
        self.attitude_updated_label = QLabel("等待板卡输出 GPHPR")
        self.attitude_updated_label.setObjectName("Muted")
        attitude_layout.addLayout(attitude_header)
        attitude_layout.addLayout(attitude_values)
        attitude_layout.addWidget(self.attitude_updated_label)
        self.runtime_layout.addWidget(self.attitude_card)

        gga_card = QFrame()
        gga_card.setObjectName("CommandStrip")
        gga_layout = QVBoxLayout(gga_card)
        gga_layout.setContentsMargins(13, 12, 13, 12)
        gga_layout.setSpacing(7)
        gga_header = QHBoxLayout()
        gga_heading = QLabel("最近 GGA")
        gga_heading.setObjectName("FieldLabel")
        self.gga_sent_label = QLabel("尚未上传")
        self.gga_sent_label.setObjectName("Muted")
        gga_header.addWidget(gga_heading)
        gga_header.addStretch(1)
        gga_header.addWidget(self.gga_sent_label)
        self.gga_preview = QPlainTextEdit()
        self.gga_preview.setObjectName("LogPanel")
        self.gga_preview.setReadOnly(True)
        self.gga_preview.setFixedHeight(70)
        self.gga_preview.setPlaceholderText("收到板卡定位后显示 GPGGA 报文")
        self.gga_preview.setMaximumBlockCount(2)
        gga_layout.addLayout(gga_header)
        gga_layout.addWidget(self.gga_preview)
        self.runtime_layout.addWidget(gga_card)

        location = QLabel("差分方向：CORS  →  RS232  →  K922")
        location.setObjectName("Muted")
        self.runtime_layout.addWidget(location)
        self.runtime_layout.addStretch(1)

    def _build_log_panel(self) -> QFrame:
        clear_button = QPushButton("清空")
        clear_button.setObjectName("TextButton")
        clear_button.clicked.connect(self._clear_log)
        self.preview_data_button = QPushButton("查看差分")
        self.preview_data_button.setObjectName("SecondaryButton")
        self.preview_data_button.setToolTip("查看最近一次账号测试收到的 RTCM 样本")
        self.preview_data_button.setEnabled(False)
        self.preview_data_button.clicked.connect(self._open_rtcm_preview)
        self.log_count_label = QLabel("0 条日志 · 最多保留 500 条")
        self.log_count_label.setObjectName("Muted")
        header_actions = QWidget()
        action_layout = QHBoxLayout(header_actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(4)
        action_layout.addWidget(self.preview_data_button)
        action_layout.addWidget(self.log_count_label)
        action_layout.addWidget(clear_button)
        card, layout = make_card(
            "运行日志",
            "记录链路状态变化、串口与 CORS 事件；可查看 RTCM 样本，保留最近 500 条日志。",
            header_actions,
        )

        self.log_view = QTextEdit()
        self.log_view.setObjectName("LogPanel")
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(500)
        self.log_view.setMinimumHeight(360)
        layout.addWidget(self.log_view, 1)
        card.setMinimumHeight(420)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return card

    def _refresh_ports(self) -> None:
        current = self.serial_combo.currentData() if hasattr(self, "serial_combo") else None
        self.serial_combo.clear()
        try:
            ports = list_ports.comports() if list_ports else []
        except OSError as exc:
            self._append_log("WARNING", f"串口枚举失败：{exc}")
            ports = []
        for port in ports:
            description = port.description or "Serial device"
            self.serial_combo.addItem(f"{port.device}  ·  {description}", port.device)
        if not ports:
            self.serial_combo.addItem("未发现串口", "")
        if current and self.serial_combo.findData(current) < 0:
            self.serial_combo.addItem(f"{current}  ·  未检测到设备", current)
        if current:
            index = self.serial_combo.findData(current)
            if index >= 0:
                self.serial_combo.setCurrentIndex(index)

    def _load_saved_config(self) -> None:
        self.config_path_label.setText(f"保存到用户配置目录 · {self.store.path.parent}")
        try:
            config = self.store.load()
        except (ConfigError, OSError) as exc:
            self._append_log("WARNING", f"已有配置未加载：{exc}")
            return
        if config is None:
            if self.serial_combo.count() > 1:
                self.serial_combo.setCurrentIndex(0)
            return
        self._apply_config(config)
        self._append_log("INFO", "已加载上次保存的连接配置")

    def _apply_config(self, config: ClientConfig) -> None:
        self._loaded_config = config
        index = self.serial_combo.findData(config.serial_port)
        if index < 0:
            self.serial_combo.addItem(f"{config.serial_port}  ·  未检测到设备", config.serial_port)
            index = self.serial_combo.findData(config.serial_port)
        self.serial_combo.setCurrentIndex(index)
        self.baud_combo.setCurrentText(str(config.baudrate))
        self.gga_rate_spin.setValue(config.gga_output_rate_hz)
        self._set_combo_data(self.ins_mode_combo, config.ins_mode)
        self._set_combo_data(self.heading_mode_combo, config.heading_mode)
        self._set_combo_data(self.imu_axis_combo, config.imu_axis_type)
        self.leverarm_x_spin.setValue(config.dr_leverarm_x_m)
        self.leverarm_y_spin.setValue(config.dr_leverarm_y_m)
        self.leverarm_z_spin.setValue(config.dr_leverarm_z_m)
        self.ins_init_speed_spin.setValue(config.dr_init_speed_mps)
        self.ins_timeout_spin.setValue(config.dr_timeout_seconds)
        self.attitude_rate_spin.setValue(config.attitude_output_rate_hz)
        self.host_edit.setText(config.cors_host)
        self.port_edit.setText(str(config.cors_port))
        self.mountpoint_edit.setText(config.mountpoint)
        self.username_edit.setText(config.username)
        self.password_edit.setText(config.password)
        self.version_combo.setCurrentIndex(max(0, self.version_combo.findData(config.ntrip_version)))
        self.tls_check.setChecked(config.tls)
        self.allow_insecure_check.setChecked(config.allow_insecure_auth)
        self._update_board_settings_controls()
        self._update_security_notice()

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: Any) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _read_config(self, *, require_serial: bool = True) -> ClientConfig:
        serial_port = self.serial_combo.currentData() or ("" if require_serial else "ACCOUNT_TEST")
        baudrate = self.baud_combo.currentText().strip() if require_serial else "115200"
        return ClientConfig.from_mapping(
            {
                **(self._loaded_config.to_mapping() if self._loaded_config else {}),
                "serial_port": serial_port,
                "baudrate": baudrate,
                "gga_output_rate_hz": self.gga_rate_spin.value(),
                "ins_mode": self.ins_mode_combo.currentData(),
                "imu_axis_type": self.imu_axis_combo.currentData(),
                "dr_leverarm_x_m": self.leverarm_x_spin.value(),
                "dr_leverarm_y_m": self.leverarm_y_spin.value(),
                "dr_leverarm_z_m": self.leverarm_z_spin.value(),
                "dr_init_speed_mps": self.ins_init_speed_spin.value(),
                "dr_timeout_seconds": self.ins_timeout_spin.value(),
                "heading_mode": self.heading_mode_combo.currentData(),
                "attitude_output_rate_hz": self.attitude_rate_spin.value(),
                "cors_host": self.host_edit.text(),
                "cors_port": self.port_edit.text(),
                "mountpoint": self.mountpoint_edit.text(),
                "username": self.username_edit.text(),
                "password": self.password_edit.text(),
                "tls": self.tls_check.isChecked(),
                "allow_insecure_auth": self.allow_insecure_check.isChecked(),
                "ntrip_version": self.version_combo.currentData(),
            }
        )

    def _save_config(self) -> bool:
        try:
            config = self._read_config()
            self.store.save(config)
        except (ConfigError, OSError) as exc:
            self._show_validation_error(str(exc))
            return False
        self.validation_label.hide()
        self._append_log("INFO", "连接配置已保存")
        return True

    def _start_client(self) -> None:
        if self.worker is not None or self.account_test_worker is not None:
            return
        if not self._save_config():
            return
        try:
            config = self._read_config()
        except ConfigError as exc:
            self._show_validation_error(str(exc))
            return

        self._reset_runtime()
        self.worker = ConnectionWorker(config, self)
        self.worker.event_received.connect(self._handle_service_event)
        self.worker.finished.connect(self._on_worker_finished)
        self._set_controls_enabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self._append_log("INFO", "正在启动 NTRIP 客户端")
        self.worker.start()

    def _test_account(self) -> None:
        if self.account_test_worker is not None:
            if self.account_test_worker.isRunning():
                self.account_test_worker.request_cancel()
                self.test_account_button.setEnabled(False)
                self.statusBar().showMessage("正在停止持续测试…")
            return
        if self.worker is not None:
            return
        try:
            config = self._read_config(require_serial=False)
            synthetic_gga = build_synthetic_gga(
                self.test_lat_edit.text(),
                self.test_lon_edit.text(),
            )
        except ConfigError as exc:
            self._show_validation_error(str(exc))
            return
        except ValueError as exc:
            self._show_validation_error(str(exc))
            return

        self.validation_label.hide()
        self._reset_runtime()
        self._clear_position("测试模式", "账号测试不读取板卡定位")
        self._last_account_test_result = None
        self.preview_data_button.setEnabled(False)
        self._set_metrics_mode(testing=True)
        self._set_status_pill("账号测试中", "blue")
        self.serial_step.set_detail("测试模式 · 不打开板卡串口", "neutral")
        self.gga_step.set_detail("准备发送合成 GGA", "blue")
        self.cors_step.set_detail("正在连接并验证 CORS", "blue")
        self.gga_preview.setPlainText(synthetic_gga.decode("ascii").strip())
        self.gga_sent_label.setText("合成测试报文")
        self.account_test_worker = AccountTestWorker(config, synthetic_gga, self)
        self.account_test_worker.progress_changed.connect(self._on_account_test_progress)
        self.account_test_worker.finished.connect(self._on_account_test_finished)
        self._set_controls_enabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.test_account_button.setText("停止测试")
        self.test_account_button.setEnabled(True)
        self._append_log(
            "INFO",
            f"持续测试开始：{config.cors_host}:{config.cors_port}/{config.mountpoint}"
            "（合成 GGA 每 5 秒发送，持续接收 RTCM，不打开串口；再次点击停止）",
        )
        self.statusBar().showMessage("持续测试连接中…收到数据后会实时累计字节数")
        self.account_test_worker.start()

    def _on_account_test_progress(self, progress: AccountTestProgress) -> None:
        self._set_status_pill("账号测试中", "blue")
        self.serial_step.set_detail("测试模式 · 不打开板卡串口", "neutral")
        gga_tone = "green" if progress.gga_sent_count else "amber"
        self.gga_step.set_detail(
            f"合成 GGA 已发送 · {progress.gga_sent_count} 条",
            gga_tone,
        )
        self.gga_sent_label.setText(f"测试上传 · {progress.gga_sent_count} 条")
        if progress.last_gga:
            self.gga_preview.setPlainText(progress.last_gga.decode("ascii").strip())
        if progress.rtcm_confirmed:
            self.cors_step.set_detail(
                f"已认证 · 接收 {progress.bytes_received:,} B，已校验 RTCM",
                "green",
            )
        elif progress.bytes_received:
            self.cors_step.set_detail(f"已接收 {progress.bytes_received:,} B，等待有效 RTCM 帧", "amber")
        else:
            self.cors_step.set_detail("已认证 · 等待 RTCM 数据", "amber")
        self._update_test_metrics(progress.bytes_received, progress.duration_seconds)
        self.statusBar().showMessage(
            f"持续测试中 · 已运行 {progress.duration_seconds:.1f} 秒 · "
            f"GGA {progress.gga_sent_count} 条 · 收到 {progress.bytes_received:,} 字节"
        )
        if progress.authenticated and progress.data_preview:
            self._last_account_test_result = AccountTestResult(
                authenticated=True,
                bytes_received=progress.bytes_received,
                message="持续测试进行中",
                data_preview=progress.data_preview,
                rtcm_frames=progress.rtcm_frames,
                gga_sent_count=progress.gga_sent_count,
                duration_seconds=progress.duration_seconds,
                rtcm_confirmed=progress.rtcm_confirmed,
                last_gga=progress.last_gga,
            )
            self.preview_data_button.setEnabled(True)

    def _on_account_test_finished(self) -> None:
        worker = self.account_test_worker
        result = worker.result if worker else None
        self.account_test_worker = None
        self._set_controls_enabled(True)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.test_account_button.setText("测试账号")
        if worker:
            worker.deleteLater()

        if result:
            if result.stream_error or (not result.authenticated and not result.stopped):
                level = "ERROR"
            elif result.authenticated and not result.rtcm_confirmed:
                level = "WARNING"
            else:
                level = "INFO"
            self._append_log(level, result.message)
            self.statusBar().showMessage(result.message, 15000)
            if result.authenticated and result.data_preview:
                self._last_account_test_result = result
                self.preview_data_button.setEnabled(True)
            self._show_account_test_state(result)
        else:
            self._set_status_pill("测试已结束", "neutral")
            self.serial_step.set_detail("测试模式 · 未使用板卡串口", "neutral")
            self.gga_step.set_detail("测试已结束", "neutral")
            self.cors_step.set_detail("测试已结束", "neutral")
        if self._close_when_stopped:
            QTimer.singleShot(0, self.close)

    def _show_account_test_state(self, result: AccountTestResult) -> None:
        stopped = result.stopped
        if result.stream_error:
            label, tone = "测试链路中断", "red"
            cors_detail, cors_tone = result.message, tone
        elif result.rtcm_confirmed:
            label = "测试已停止 · 收到 RTCM" if stopped else "测试收到 RTCM"
            tone = "green"
            cors_detail = f"测试结束 · 共收到 {result.bytes_received:,} B，已校验 RTCM"
            cors_tone = "green"
        elif result.bytes_received:
            label, tone = "已认证 · 未确认 RTCM", "amber"
            cors_detail = f"测试结束 · 共收到 {result.bytes_received:,} B，未检测到校验通过的 RTCM 帧"
            cors_tone = "amber"
        elif result.authenticated:
            label = "测试已停止 · 无 RTCM" if stopped else "已认证 · 无 RTCM"
            tone = "neutral" if stopped else "amber"
            cors_detail = "认证成功 · 测试期间未收到 RTCM"
            cors_tone = "amber"
        elif stopped:
            label = "测试已取消"
            tone = "neutral"
            cors_detail = "测试已取消 · 未完成 CORS 认证"
            cors_tone = "neutral"
        else:
            label = "测试失败"
            tone = "red"
            cors_detail = result.message
            cors_tone = "red"

        self._set_status_pill(label, tone)
        self.serial_step.set_detail("测试模式 · 未使用板卡串口", "neutral")
        gga_tone = "green" if result.gga_sent_count else ("neutral" if stopped else "amber")
        self.gga_step.set_detail(f"合成 GGA 已发送 · {result.gga_sent_count} 条", gga_tone)
        self.gga_sent_label.setText(f"测试上传 · {result.gga_sent_count} 条")
        if result.last_gga:
            self.gga_preview.setPlainText(result.last_gga.decode("ascii").strip())
        self.cors_step.set_detail(cors_detail, cors_tone)
        self._update_test_metrics(result.bytes_received, result.duration_seconds)

    def _open_rtcm_preview(self) -> None:
        if not self._last_account_test_result:
            return
        dialog = RtcmPreviewDialog(self._last_account_test_result, self, theme=self.theme_id)
        dialog.exec()
        dialog.deleteLater()

    def _stop_client(self) -> None:
        if not self.worker or not self.worker.isRunning():
            return
        self._set_state("stopping", "正在停止客户端并关闭链路")
        self.stop_button.setEnabled(False)
        self.worker.request_stop()

    def _on_worker_finished(self) -> None:
        self._set_controls_enabled(True)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if self.state not in ("failed", "stopped"):
            self._set_state("stopped", "客户端已停止")
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        if self._close_when_stopped:
            QTimer.singleShot(0, self.close)

    def _handle_service_event(self, event: ServiceEvent) -> None:
        if event.kind == "state":
            self._set_state(event.data["state"], event.data.get("message", ""))
        elif event.kind == "log":
            self._append_log(event.data.get("level", "INFO"), event.data.get("message", ""), event.data.get("at"))
        elif event.kind == "gga":
            self.gga_preview.setPlainText(event.data.get("sentence", ""))
            position = event.data.get("position")
            if isinstance(position, GgaPosition):
                self._update_position(position, event.data.get("at"))
            else:
                self.gga_step.set_detail("板卡正在输出有效定位", "green")
        elif event.kind == "attitude":
            attitude = event.data.get("attitude")
            if isinstance(attitude, AttitudeSolution):
                self._update_attitude(attitude, event.data.get("at"))
        elif event.kind == "gga_upload":
            sent_at = event.data.get("at") or datetime.now()
            self.gga_sent_label.setText(f"已上传 {sent_at:%H:%M:%S}")
            self.gga_step.set_detail(f"每 5 秒更新 · 最近 {sent_at:%H:%M:%S}", "green")
        elif event.kind == "stats":
            self._update_metrics(event.data)

    def _set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        label, tone = STATE_PRESENTATION.get(state, (state, "neutral"))
        self._set_status_pill(label, tone)
        if detail:
            self.statusBar().showMessage(detail, 8000)

        if state == "starting":
            self.serial_step.set_detail("正在打开串口", "blue")
            self.gga_step.set_detail("待检测", "neutral")
            self.cors_step.set_detail("等待串口初始化", "neutral")
        elif state == "waiting_gga":
            self.serial_step.set_detail(
                f"已打开 · 已请求 GPGGA {self.gga_rate_spin.value():g} Hz 输出",
                "green",
            )
            self.gga_step.set_detail("等待有效定位数据", "amber")
            self.cors_step.set_detail("收到 GGA 后开始连接", "neutral")
        elif state == "connecting":
            self.serial_step.set_detail("已打开", "green")
            self.gga_step.set_detail("定位已就绪", "green")
            self.cors_step.set_detail("正在握手", "blue")
        elif state == "connected":
            self.serial_step.set_detail("已打开 · RTCM 写入中", "green")
            self.gga_step.set_detail("GGA 正常上行", "green")
            self.cors_step.set_detail("已建立数据流", "green")
        elif state == "reconnecting":
            self.serial_step.set_detail("串口保持连接", "green")
            self.gga_step.set_detail("等待链路恢复", "amber")
            self.cors_step.set_detail("正在重连", "amber")
        elif state in ("stopped", "failed"):
            tone = "red" if state == "failed" else "neutral"
            self.rate_metric.value_label.setText("0.0")
            if self._position_timeout.isActive() or self._attitude_timeout.isActive():
                self._clear_position("链路已关闭", "重新连接后更新板卡定位与姿态")
                self._clear_attitude()
            self.serial_step.set_detail("未运行" if state == "stopped" else "已停止", tone)
            self.gga_step.set_detail("等待启动" if state == "stopped" else "链路已关闭", tone)
            self.cors_step.set_detail("未连接" if state == "stopped" else "请检查运行日志", tone)

    def _update_metrics(self, data: dict[str, Any]) -> None:
        rate = float(data.get("rate_bytes_per_second", 0.0)) / 1024.0
        self.rate_metric.value_label.setText(f"{rate:.1f}")
        total = int(data.get("bytes_received", 0))
        if total < 1024:
            self.bytes_metric.value_label.setText(str(total))
            self.bytes_metric.suffix_label.setText("B")
        elif total < 1024 * 1024:
            self.bytes_metric.value_label.setText(f"{total / 1024:.1f}")
            self.bytes_metric.suffix_label.setText("KB")
        else:
            self.bytes_metric.value_label.setText(f"{total / (1024 * 1024):.2f}")
            self.bytes_metric.suffix_label.setText("MB")
        seconds = int(data.get("runtime_seconds", 0))
        self.runtime_metric.value_label.setText(self._format_duration(seconds))

    def _update_position(self, position: GgaPosition, received_at: datetime | None) -> None:
        self._position_timeout.start(round(1000 * freshness_seconds(self.gga_rate_spin.value())))
        self.position_quality_badge.setText(position.fix_quality_name)
        tone = {
            1: "blue",
            2: "blue",
            3: "blue",
            4: "green",
            5: "amber",
            6: "amber",
            15: "blue",
            16: "amber",
        }.get(position.fix_quality, "neutral")
        self.position_quality_badge.setProperty("tone", tone)
        self.position_quality_badge.style().unpolish(self.position_quality_badge)
        self.position_quality_badge.style().polish(self.position_quality_badge)

        if not position.has_fix:
            self.position_latitude_value.setText("—")
            self.position_longitude_value.setText("—")
            self.gga_step.set_detail("未获得有效定位", "amber")
        else:
            latitude = position.latitude_degrees or 0.0
            longitude = position.longitude_degrees or 0.0
            north_south = "N" if latitude >= 0 else "S"
            east_west = "E" if longitude >= 0 else "W"
            self.position_latitude_value.setText(f"{abs(latitude):.7f}° {north_south}")
            self.position_longitude_value.setText(f"{abs(longitude):.7f}° {east_west}")
            satellite_count = f"{position.satellites} 颗卫星" if position.satellites is not None else "卫星数 —"
            self.gga_step.set_detail(f"{position.fix_quality_name} · {satellite_count}", tone)

        details = []
        if position.satellites is not None:
            details.append(f"卫星 {position.satellites} 颗")
        else:
            details.append("卫星 —")
        details.append(f"HDOP {position.hdop:.1f}" if position.hdop is not None else "HDOP —")
        details.append(
            f"海拔 {position.altitude_meters:.2f} m"
            if position.altitude_meters is not None
            else "海拔 —"
        )
        self.position_details_label.setText("  ·  ".join(details))
        updated_at = received_at or datetime.now()
        self.position_updated_label.setText(f"最近更新 {updated_at:%H:%M:%S}")

    def _update_attitude(
        self,
        attitude: AttitudeSolution,
        received_at: datetime | None,
    ) -> None:
        # Preserve mode leaves the board's actual rate unknown. Allow the slowest supported rate.
        rate = self.attitude_rate_spin.value() if self.heading_mode_combo.currentData() == "enable" else 0.1
        self._attitude_timeout.start(round(1000 * freshness_seconds(rate)))
        status = {
            0: ("姿态无效", "neutral"),
            1: ("单点解", "blue"),
            2: ("码差分", "blue"),
            4: ("RTK 固定", "green"),
            5: ("RTK 浮点", "amber"),
            6: ("正在估算", "amber"),
            7: ("人工固定", "neutral"),
            8: ("超宽巷解", "blue"),
            9: ("SBAS", "blue"),
            15: ("PPP 收敛", "green"),
            16: ("PPP 未收敛", "amber"),
        }.get(attitude.fix_quality, (attitude.fix_quality_name, "neutral"))
        self.attitude_status_badge.setText(status[0])
        self.attitude_status_badge.setProperty("tone", status[1])
        self.attitude_status_badge.style().unpolish(self.attitude_status_badge)
        self.attitude_status_badge.style().polish(self.attitude_status_badge)
        self.attitude_heading_value.setText(f"{attitude.heading_degrees:.2f}°" if attitude.fix_quality else "—")
        self.attitude_pitch_value.setText(f"{attitude.pitch_degrees:.2f}°" if attitude.fix_quality else "—")
        self.attitude_roll_value.setText(f"{attitude.roll_degrees:.2f}°" if attitude.fix_quality else "—")

        details = []
        if attitude.satellites is not None:
            details.append(f"参与卫星 {attitude.satellites} 颗")
        if attitude.correction_age_seconds is not None:
            details.append(f"差分龄期 {attitude.correction_age_seconds:.1f} s")
        if attitude.station_id:
            details.append(f"基站 {attitude.station_id}")
        updated_at = received_at or datetime.now()
        details.append(f"最近更新 {updated_at:%H:%M:%S}")
        self.attitude_updated_label.setText("  ·  ".join(details))

    def _clear_position(self, status: str = "等待定位", detail: str = "等待板卡定位数据") -> None:
        self._position_timeout.stop()
        self.position_quality_badge.setText(status)
        self.position_quality_badge.setProperty("tone", "neutral")
        self.position_quality_badge.style().unpolish(self.position_quality_badge)
        self.position_quality_badge.style().polish(self.position_quality_badge)
        self.position_latitude_value.setText("—")
        self.position_longitude_value.setText("—")
        self.position_details_label.setText("等待有效定位解")
        self.position_updated_label.setText(detail)

    def _expire_position(self) -> None:
        self._clear_position("定位已过期", "等待新的板卡 GGA 报文")
        self.gga_step.set_detail("板卡 GGA 已超时", "amber")

    def _expire_attitude(self) -> None:
        self._clear_attitude("姿态已过期")

    def _clear_attitude(self, status: str = "等待姿态") -> None:
        self._attitude_timeout.stop()
        self.attitude_status_badge.setText(status)
        self.attitude_status_badge.setProperty("tone", "neutral")
        self.attitude_status_badge.style().unpolish(self.attitude_status_badge)
        self.attitude_status_badge.style().polish(self.attitude_status_badge)
        self.attitude_heading_value.setText("—")
        self.attitude_pitch_value.setText("—")
        self.attitude_roll_value.setText("—")
        self.attitude_updated_label.setText("等待板卡输出 GPHPR")

    def _set_status_pill(self, label: str, tone: str) -> None:
        self.status_pill.setText(label)
        self.status_pill.setProperty("tone", tone)
        self.status_pill.style().unpolish(self.status_pill)
        self.status_pill.style().polish(self.status_pill)

    def _set_metrics_mode(self, *, testing: bool) -> None:
        if testing:
            self.rate_metric.title_label.setText("测试平均接收速率")
            self.bytes_metric.title_label.setText("测试接收总量")
            self.runtime_metric.title_label.setText("测试持续时间")
        else:
            self.rate_metric.title_label.setText("RTCM 下行速率")
            self.bytes_metric.title_label.setText("累计写入板卡")
            self.runtime_metric.title_label.setText("本次运行时长")

    def _update_test_metrics(self, bytes_received: int, duration_seconds: float) -> None:
        average_rate = bytes_received / max(duration_seconds, 0.001) / 1024.0
        self.rate_metric.value_label.setText(f"{average_rate:.1f}")
        if bytes_received < 1024:
            self.bytes_metric.value_label.setText(str(bytes_received))
            self.bytes_metric.suffix_label.setText("B")
        elif bytes_received < 1024 * 1024:
            self.bytes_metric.value_label.setText(f"{bytes_received / 1024:.1f}")
            self.bytes_metric.suffix_label.setText("KB")
        else:
            self.bytes_metric.value_label.setText(f"{bytes_received / (1024 * 1024):.2f}")
            self.bytes_metric.suffix_label.setText("MB")
        self.runtime_metric.value_label.setText(self._format_duration(int(duration_seconds)))

    @staticmethod
    def _format_duration(seconds: int) -> str:
        hours, remainder = divmod(max(0, seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _append_log(self, level: str, message: str, at: datetime | None = None) -> None:
        if not hasattr(self, "log_view"):
            return
        entry = (level.upper(), message, at or datetime.now())
        self._log_entries.append(entry)
        del self._log_entries[:-500]
        self._render_log_entry(*entry)
        self.log_count_label.setText(f"{len(self._log_entries)} 条日志 · 最多保留 500 条")

    def _render_log_entry(self, level: str, message: str, at: datetime) -> None:
        timestamp = at.strftime("%H:%M:%S")
        colors = LIGHT_LOG_COLORS if self.theme_id == "light" else LOG_COLORS
        color = colors.get(level.upper(), colors["INFO"])
        timestamp_color = "#748596" if self.theme_id == "light" else "#718397"
        message_color = "#374b5d" if self.theme_id == "light" else "#c4d0dc"
        safe_message = html.escape(message)
        self.log_view.append(
            f'<span style="color:{timestamp_color}">{timestamp}</span>  '
            f'<span style="color:{color}">{level.upper():7s}</span>  '
            f'<span style="color:{message_color}">{safe_message}</span>'
        )

    def _clear_log(self) -> None:
        self._log_entries.clear()
        self.log_view.clear()
        self.log_count_label.setText("0 条日志 · 最多保留 500 条")

    def _toggle_password(self) -> None:
        showing = self.password_edit.echoMode() == QLineEdit.EchoMode.Password
        self.password_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if showing else QLineEdit.EchoMode.Password
        )
        self.password_toggle.setText("隐藏" if showing else "显示")

    def _show_validation_error(self, message: str) -> None:
        self.validation_label.setText(message)
        self.validation_label.show()
        self.pages.setCurrentIndex(0)
        self.statusBar().showMessage(message, 10000)
        self._append_log("WARNING", message)

    def _set_controls_enabled(self, enabled: bool) -> None:
        controls = (
            self.serial_combo,
            self.refresh_ports_button,
            self.baud_combo,
            *self._board_settings_controls,
            self.host_edit,
            self.port_edit,
            self.mountpoint_edit,
            self.test_lat_edit,
            self.test_lon_edit,
            self.username_edit,
            self.password_edit,
            self.password_toggle,
            self.version_combo,
            self.tls_check,
            self.allow_insecure_check,
            self.save_button,
            self.test_account_button,
        )
        self._configuration_controls_enabled = enabled
        for control in controls:
            control.setEnabled(enabled)
        self._update_board_settings_controls()

    def _update_board_command_preview(self, *_args: object) -> None:
        period_text = format(1.0 / self.gga_rate_spin.value(), ".8g")
        commands = []
        if self.ins_mode_combo.currentData() == "enable":
            commands.extend(
                (
                    f"set imuaxestype {self.imu_axis_combo.currentData()}",
                    "set drleverarm "
                    f"{self.leverarm_x_spin.value():.6g} "
                    f"{self.leverarm_y_spin.value():.6g} "
                    f"{self.leverarm_z_spin.value():.6g}",
                    f"set drconfig {self.ins_init_speed_spin.value():.6g}",
                    f"set drtimeout {self.ins_timeout_spin.value()}",
                    "inscontrol enable",
                )
            )
        elif self.ins_mode_combo.currentData() == "disable":
            commands.append("inscontrol disable")

        if self.heading_mode_combo.currentData() == "enable":
            attitude_period = format(1.0 / self.attitude_rate_spin.value(), ".8g")
            commands.extend(
                (
                    f"log headinga ontime {attitude_period}",
                    f"log gphpr ontime {attitude_period}",
                )
            )
        elif self.heading_mode_combo.currentData() == "disable":
            commands.extend(("unlog heading", "unlog gphpr"))

        commands.extend((f"log gpgga ontime {period_text}", "saveconfig"))
        self.board_command_text.setText("   →   ".join(commands))

    def _update_board_settings_controls(self, *_args: object) -> None:
        controls_enabled = getattr(self, "_configuration_controls_enabled", True)
        for control in self._board_settings_controls:
            control.setEnabled(controls_enabled)
        self._update_board_command_preview()

    def _reset_transport_acknowledgement(self, *_args: object) -> None:
        self.allow_insecure_check.setChecked(False)
        self._update_security_notice()

    def _update_security_notice(self, *_args: object) -> None:
        has_credentials = bool(self.username_edit.text().strip() and self.password_edit.text())
        self.security_notice.setVisible(has_credentials and not self.tls_check.isChecked())

    def _reset_runtime(self) -> None:
        self._set_metrics_mode(testing=False)
        self.rate_metric.value_label.setText("0.0")
        self.bytes_metric.value_label.setText("0")
        self.bytes_metric.suffix_label.setText("B")
        self.runtime_metric.value_label.setText("00:00")
        self.gga_preview.clear()
        self.gga_sent_label.setText("尚未上传")
        self._clear_position()
        self._clear_attitude()
        self.serial_step.set_detail("正在打开串口", "blue")
        self.gga_step.set_detail("等待定位", "neutral")
        self.cors_step.set_detail("尚未连接", "neutral")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual method naming
        if self.worker and self.worker.isRunning():
            self._close_when_stopped = True
            self._stop_client()
            event.ignore()
            return
        if self.account_test_worker and self.account_test_worker.isRunning():
            self._close_when_stopped = True
            self.account_test_worker.request_cancel()
            event.ignore()
            return
        event.accept()
