"""Dialog for inspecting the bounded sample returned by an account test."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..account_test import AccountTestResult
from ..rtcm import format_hex_dump


class RtcmPreviewDialog(QDialog):
    def __init__(self, result: AccountTestResult, parent=None, *, theme: str = "dark") -> None:
        super().__init__(parent)
        self.result = result
        self.hex_dump = format_hex_dump(result.data_preview)
        self.setObjectName("RtcmPreviewDialog")
        self.setWindowTitle("差分数据预览")
        self.resize(900, 620)
        self.setMinimumSize(720, 480)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("本次接收的数据样本")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        preview_size = len(result.data_preview)
        summary = QLabel(
            f"收到 {result.bytes_received:,} 字节；当前保留 {preview_size:,} 字节样本用于查看。"
        )
        summary.setObjectName("Muted")
        layout.addWidget(summary)

        valid_frames = sum(frame.crc_valid for frame in result.rtcm_frames)
        if result.rtcm_frames:
            frame_summary = QLabel(
                f"识别到 {len(result.rtcm_frames)} 个完整 RTCM 3 帧，"
                f"其中 {valid_frames} 个 CRC-24Q 校验通过。"
            )
        else:
            frame_summary = QLabel(
                "样本中暂未找到完整 RTCM 3 帧；仍可在下方查看原始字节。"
            )
        frame_summary.setObjectName("Muted")
        layout.addWidget(frame_summary)

        self.frame_table = QTableWidget(len(result.rtcm_frames), 6)
        self.frame_table.setObjectName("RtcmFrameTable")
        self.frame_table.setHorizontalHeaderLabels(
            ["偏移", "消息类型", "负载", "帧长度", "站点 ID", "CRC-24Q"]
        )
        self.frame_table.verticalHeader().hide()
        self.frame_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.frame_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.frame_table.setAlternatingRowColors(True)
        self.frame_table.setMinimumHeight(130)
        self.frame_table.setMaximumHeight(230)
        header = self.frame_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for row, frame in enumerate(result.rtcm_frames):
            values = (
                f"0x{frame.offset:04X}",
                (
                    f"{frame.message_type} · {frame.message_name}"
                    if frame.message_type is not None
                    else frame.message_name
                ),
                f"{frame.payload_length} B",
                f"{frame.frame_length} B",
                str(frame.station_id) if frame.station_id is not None else "—",
                "通过" if frame.crc_valid else "错误",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 5:
                    good, bad = ("#147653", "#ad3442") if theme == "light" else ("#72dfb8", "#f28f9a")
                    item.setForeground(QColor(good if frame.crc_valid else bad))
                self.frame_table.setItem(row, column, item)
        self.frame_table.clearSelection()
        self.frame_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.frame_table)

        raw_label = QLabel("原始 HEX 样本")
        raw_label.setObjectName("FieldLabel")
        layout.addWidget(raw_label)
        self.hex_editor = QPlainTextEdit()
        self.hex_editor.setObjectName("LogPanel")
        self.hex_editor.setReadOnly(True)
        self.hex_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.hex_editor.setFont(QFont("Consolas", 10))
        self.hex_editor.setPlainText(self.hex_dump)
        layout.addWidget(self.hex_editor, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.copy_button = QPushButton("复制 HEX")
        self.copy_button.clicked.connect(self._copy_hex)
        self.save_button = QPushButton("保存样本…")
        self.save_button.clicked.connect(self._save_sample)
        close_button = QPushButton("关闭")
        close_button.setObjectName("PrimaryButton")
        close_button.clicked.connect(self.accept)
        actions.addWidget(self.copy_button)
        actions.addWidget(self.save_button)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    def _copy_hex(self) -> None:
        QApplication.clipboard().setText(self.hex_dump)
        self.copy_button.setText("已复制")

    def _save_sample(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存收到的差分样本",
            "cors-sample.rtcm",
            "RTCM / 二进制样本 (*.rtcm *.bin);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            Path(path).write_bytes(self.result.data_preview)
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", f"无法保存样本：{exc}")
            return
        self.save_button.setText("已保存")
