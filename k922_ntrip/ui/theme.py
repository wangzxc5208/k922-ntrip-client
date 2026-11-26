"""Visual tokens and stylesheet for the desktop client."""


_BASE_STYLESHEET = """
QMainWindow, QWidget#Root {
    background: #0b1118;
    color: #e7edf5;
    font-family: "Segoe UI";
    font-size: 13px;
}
QScrollArea#PageScrollArea { background: #0b1118; border: none; }
QWidget { color: #e7edf5; }
QFrame#Card {
    background: #121a23;
    border: 1px solid #273544;
    border-radius: 15px;
}
QTabWidget#MainPages::pane {
    background: #0b1118;
    border: 1px solid #273544;
    border-radius: 12px;
    top: -1px;
}
QTabWidget#MainPages QTabBar::tab {
    background: #121a23;
    color: #91a2b4;
    border: 1px solid #273544;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 10px 18px;
    margin-right: 5px;
    min-width: 84px;
}
QTabWidget#MainPages QTabBar::tab:selected {
    background: #1b2b33;
    color: #75e2bd;
    border-color: #32634f;
}
QTabWidget#MainPages QTabBar::tab:hover:!selected {
    background: #19242e;
    color: #dce6ef;
}
QFrame#MetricCard {
    background: #121a23;
    border: 1px solid #273544;
    border-radius: 12px;
}
QLabel#BrandMark {
    color: #101a20;
    background: #53dfb2;
    border-radius: 11px;
    font-size: 15px;
    font-weight: 800;
}
QLabel#Eyebrow {
    color: #7f91a5;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#PageTitle { font-size: 24px; font-weight: 700; color: #f2f6fb; }
QLabel#Subtitle { color: #92a2b5; font-size: 12px; }
QLabel#SectionTitle { font-size: 15px; font-weight: 650; color: #edf3fa; }
QLabel#SectionHint { color: #8293a6; font-size: 11px; }
QLabel#FieldLabel { color: #aebdcb; font-size: 11px; font-weight: 600; }
QLabel#Muted { color: #8393a5; font-size: 11px; }
QLabel#MetricTitle { color: #91a2b4; font-size: 11px; font-weight: 600; }
QLabel#MetricValue { color: #eff5fa; font-size: 22px; font-weight: 700; }
QLabel#MetricSuffix { color: #8fa0b2; font-size: 11px; }
QLabel#StatusPill {
    background: #202b37;
    color: #b9c6d2;
    border: 1px solid #344453;
    border-radius: 11px;
    padding: 7px 12px;
    font-size: 11px;
    font-weight: 700;
}
QLabel#StatusPill[tone="green"] { background: #12392f; color: #77e4bd; border-color: #22634f; }
QLabel#StatusPill[tone="amber"] { background: #3a2c19; color: #f2c17d; border-color: #69502e; }
QLabel#StatusPill[tone="red"] { background: #401f25; color: #f29aa3; border-color: #71323d; }
QLabel#StatusPill[tone="blue"] { background: #172f43; color: #8fc9f3; border-color: #2d5875; }
QLabel#StatusPill[tone="neutral"] { background: #202b37; color: #b9c6d2; border-color: #344453; }
QLabel#StepDot {
    background: #354454;
    border: none;
    border-radius: 5px;
}
QLabel#StepDot[tone="green"] { background: #55ddb0; }
QLabel#StepDot[tone="amber"] { background: #e5b36c; }
QLabel#StepDot[tone="red"] { background: #ee7784; }
QLabel#StepDot[tone="blue"] { background: #75bfee; }
QLabel#StepTitle { color: #d8e2ec; font-size: 12px; font-weight: 600; }
QLabel#StepDetail { color: #8293a5; font-size: 11px; }
QLabel#PositionValue { color: #e7f3fa; font-size: 14px; font-weight: 700; }
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {
    background: #0d141c;
    border: 1px solid #2b3a4a;
    border-radius: 8px;
    padding: 8px 10px;
    min-height: 21px;
    color: #e7edf5;
    selection-background-color: #1d9f7a;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus { border: 1px solid #3abf96; }
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled { color: #657486; background: #111820; }
QLineEdit::placeholder { color: #586a7d; }
QComboBox::drop-down { border: none; width: 25px; }
QComboBox QAbstractItemView {
    background: #121a23;
    color: #e7edf5;
    border: 1px solid #344454;
    selection-background-color: #1b3b36;
}
QCheckBox { color: #b5c2cf; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #46586a;
    border-radius: 5px;
    background: #0d141c;
}
QCheckBox::indicator:checked { background: #42c89d; border-color: #42c89d; }
QPushButton {
    background: #1a2631;
    color: #dce6ef;
    border: 1px solid #344555;
    border-radius: 8px;
    padding: 9px 14px;
    font-weight: 600;
}
QPushButton:hover { background: #233342; border-color: #52677b; }
QPushButton:pressed { background: #17212b; }
QPushButton:disabled { color: #607080; background: #151d25; border-color: #293643; }
QPushButton#PrimaryButton {
    background: #46d3a6;
    color: #071710;
    border: 1px solid #46d3a6;
    font-weight: 750;
}
QPushButton#PrimaryButton:hover { background: #62e2b8; border-color: #62e2b8; }
QPushButton#SecondaryButton { background: #172722; color: #9be4c8; border-color: #356752; }
QPushButton#SecondaryButton:hover { background: #1c342b; border-color: #4a8a6e; }
QPushButton#StopButton { background: #3a2228; color: #f2a0a7; border-color: #6b333d; }
QPushButton#StopButton:hover { background: #512931; }
QPushButton#TextButton { background: transparent; border-color: transparent; color: #96a9ba; padding: 5px 8px; }
QPushButton#TextButton:hover { color: #e7edf5; background: #1b2732; }
QPushButton#AppearanceButton { min-width: 68px; padding-left: 11px; padding-right: 11px; }
QMenu {
    background: #121a23;
    color: #e7edf5;
    border: 1px solid #344454;
    padding: 5px;
}
QMenu::item { padding: 7px 28px 7px 10px; border-radius: 5px; }
QMenu::item:selected { background: #1b3b36; }
QMenu::separator { height: 1px; background: #344454; margin: 4px 8px; }
QFrame#CommandStrip {
    background: #101b22;
    border: 1px solid #233a3a;
    border-radius: 9px;
}
QFrame#SecurityNotice {
    background: #302719;
    border: 1px solid #73582f;
    border-radius: 9px;
}
QLabel#SecurityWarning { color: #edc987; font-size: 11px; }
QCheckBox#SecurityAcknowledgement { color: #f3d5a2; font-size: 11px; font-weight: 600; }
QLabel#CommandText { color: #88dcbf; font-family: Consolas; font-size: 11px; }
QLabel#ErrorText { color: #f08d98; font-size: 11px; }
QTextEdit#LogPanel {
    background: #0d141b;
    border: 1px solid #1e2b37;
    border-radius: 9px;
    color: #bdcbd8;
    padding: 9px;
    font-family: Consolas, "Cascadia Mono";
    font-size: 11px;
}
QPlainTextEdit#LogPanel {
    background: #0d141b;
    border: 1px solid #1e2b37;
    border-radius: 8px;
    color: #8fdec1;
    padding: 8px;
    font-family: Consolas, "Cascadia Mono";
    font-size: 10px;
}
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: #344556; border-radius: 4px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QDialog#RtcmPreviewDialog {
    background-color: #0b1118;
    color: #e7edf5;
}
QDialog#RtcmPreviewDialog QLabel#SectionTitle { color: #f2f6fb; }
QDialog#RtcmPreviewDialog QLabel#Muted { color: #b4c4d2; }
QDialog#RtcmPreviewDialog QLabel#FieldLabel { color: #d3dfe9; }
QTableWidget#RtcmFrameTable {
    background: #0d141c;
    alternate-background-color: #15212c;
    color: #e7edf5;
    gridline-color: #30404f;
    border: 1px solid #344555;
    selection-background-color: #245449;
    selection-color: #f4fff9;
}
QTableWidget#RtcmFrameTable::item { padding: 6px; }
QHeaderView::section {
    background: #17242f;
    color: #d4e0e9;
    border: 1px solid #30404f;
    padding: 7px 6px;
    font-weight: 600;
}
QTableCornerButton::section { background: #17242f; border: 1px solid #30404f; }
"""


THEMES = {"dark": "深色", "light": "浅色"}
ACCENTS = {
    "mint": "薄荷绿",
    "blue": "海湾蓝",
    "violet": "暮光紫",
    "orange": "暖阳橙",
}

_ACCENT_SLOTS = {
    "#53dfb2": "brand",
    "#101a20": "on_brand",
    "#75e2bd": "tab_text",
    "#1b2b33": "selected_tab_bg",
    "#32634f": "tab_border",
    "#3abf96": "focus",
    "#1d9f7a": "selection",
    "#42c89d": "check",
    "#46d3a6": "primary",
    "#62e2b8": "primary_hover",
    "#172722": "secondary_bg",
    "#9be4c8": "secondary_text",
    "#356752": "secondary_border",
    "#1c342b": "secondary_hover",
    "#4a8a6e": "secondary_hover_border",
    "#1b3b36": "combo_selection",
    "#245449": "table_selection",
    "#88dcbf": "command_text",
    "#071710": "primary_text",
}

_ACCENT_COLORS = {
    "mint": {
        "dark": {
            "brand": "#53dfb2", "on_brand": "#101a20", "tab_text": "#75e2bd",
            "selected_tab_bg": "#1b2b33",
            "tab_border": "#32634f", "focus": "#3abf96", "selection": "#1d9f7a",
            "check": "#42c89d", "primary": "#46d3a6", "primary_hover": "#62e2b8",
            "secondary_bg": "#172722", "secondary_text": "#9be4c8", "secondary_border": "#356752",
            "secondary_hover": "#1c342b", "secondary_hover_border": "#4a8a6e",
            "combo_selection": "#1b3b36", "table_selection": "#245449",
            "command_text": "#88dcbf", "primary_text": "#071710",
        },
        "light": {
            "brand": "#35b88e", "on_brand": "#092319", "tab_text": "#087653",
            "selected_tab_bg": "#e0f4ec",
            "tab_border": "#9bcfbc", "focus": "#15966e", "selection": "#42b994",
            "check": "#27a87d", "primary": "#35b88e", "primary_hover": "#28a77e",
            "secondary_bg": "#e4f5ee", "secondary_text": "#147653", "secondary_border": "#acd9c7",
            "secondary_hover": "#d5efe5", "secondary_hover_border": "#8bcab0",
            "combo_selection": "#d7f0e6", "table_selection": "#258263",
            "command_text": "#176e57", "primary_text": "#092319",
        },
    },
    "blue": {
        "dark": {
            "brand": "#60a5fa", "on_brand": "#102238", "tab_text": "#9bc7ff",
            "selected_tab_bg": "#1c304a",
            "tab_border": "#365e8a", "focus": "#5b9bea", "selection": "#3477d1",
            "check": "#4b91e8", "primary": "#60a5fa", "primary_hover": "#82b6fb",
            "secondary_bg": "#192a40", "secondary_text": "#b4d3fb", "secondary_border": "#365d8a",
            "secondary_hover": "#203650", "secondary_hover_border": "#4d7fb6",
            "combo_selection": "#203b5c", "table_selection": "#2a5689",
            "command_text": "#9bc7ff", "primary_text": "#102238",
        },
        "light": {
            "brand": "#3c82df", "on_brand": "#ffffff", "tab_text": "#2364b2",
            "selected_tab_bg": "#e5effd",
            "tab_border": "#adc9ea", "focus": "#3c82df", "selection": "#5496e5",
            "check": "#3c82df", "primary": "#3c82df", "primary_hover": "#286fcf",
            "secondary_bg": "#eaf2fd", "secondary_text": "#285f9e", "secondary_border": "#bdd1ed",
            "secondary_hover": "#dceafd", "secondary_hover_border": "#9bbbe3",
            "combo_selection": "#dceafb", "table_selection": "#347bc8",
            "command_text": "#235f9f", "primary_text": "#ffffff",
        },
    },
    "violet": {
        "dark": {
            "brand": "#a78bfa", "on_brand": "#211936", "tab_text": "#c0adff",
            "selected_tab_bg": "#2a2440",
            "tab_border": "#59458d", "focus": "#9876f0", "selection": "#7654d5",
            "check": "#9675ed", "primary": "#a78bfa", "primary_hover": "#b8a3fb",
            "secondary_bg": "#28203c", "secondary_text": "#d2c5ff", "secondary_border": "#59458d",
            "secondary_hover": "#35294e", "secondary_hover_border": "#7963b6",
            "combo_selection": "#392c56", "table_selection": "#544083",
            "command_text": "#c0adff", "primary_text": "#211936",
        },
        "light": {
            "brand": "#8061d5", "on_brand": "#ffffff", "tab_text": "#6244b2",
            "selected_tab_bg": "#eee9fc",
            "tab_border": "#c8bce9", "focus": "#8061d5", "selection": "#9274e1",
            "check": "#8061d5", "primary": "#8061d5", "primary_hover": "#704ecb",
            "secondary_bg": "#f0ecfb", "secondary_text": "#6049a1", "secondary_border": "#cec4eb",
            "secondary_hover": "#e7e1f8", "secondary_hover_border": "#b9a9e1",
            "combo_selection": "#e8e1f8", "table_selection": "#785bc9",
            "command_text": "#6049a1", "primary_text": "#ffffff",
        },
    },
    "orange": {
        "dark": {
            "brand": "#fb923c", "on_brand": "#2b1b0d", "tab_text": "#ffb477",
            "selected_tab_bg": "#392719",
            "tab_border": "#88552d", "focus": "#e78331", "selection": "#c96a1c",
            "check": "#e78331", "primary": "#fb923c", "primary_hover": "#ffad66",
            "secondary_bg": "#342418", "secondary_text": "#ffd0a4", "secondary_border": "#80512d",
            "secondary_hover": "#432d1c", "secondary_hover_border": "#a56a3c",
            "combo_selection": "#4b301c", "table_selection": "#80502a",
            "command_text": "#ffc18a", "primary_text": "#2b1b0d",
        },
        "light": {
            "brand": "#e47b25", "on_brand": "#ffffff", "tab_text": "#a84b0b",
            "selected_tab_bg": "#fff0e3",
            "tab_border": "#efc6a4", "focus": "#d56c1c", "selection": "#e58b42",
            "check": "#d87526", "primary": "#e47b25", "primary_hover": "#ce6815",
            "secondary_bg": "#fff1e4", "secondary_text": "#995012", "secondary_border": "#edc6a6",
            "secondary_hover": "#ffe6d2", "secondary_hover_border": "#e4b18a",
            "combo_selection": "#ffead9", "table_selection": "#c96c24",
            "command_text": "#995012", "primary_text": "#ffffff",
        },
    },
}

_LIGHT_COLORS = {
    "#0b1118": "#f3f6f9", "#0d141b": "#f8fafc", "#0d141c": "#ffffff",
    "#101b22": "#eaf5f1", "#111820": "#e9eef3", "#121a23": "#ffffff",
    "#12392f": "#ddf4e9", "#151d25": "#e7edf2", "#15212c": "#f1f5f8",
    "#17212b": "#e0e7ed", "#17242f": "#e9eff4", "#172f43": "#e7f2fa",
    "#19242e": "#e9eef3", "#1a2631": "#e8edf2", "#1b2732": "#e1e8ee",
    "#1e2b37": "#d9e1e8", "#202b37": "#edf1f5", "#22634f": "#a7d8c5",
    "#233342": "#dfe7ed", "#233a3a": "#d6e6e1", "#273544": "#d7e0e8",
    "#293643": "#d1dbe3", "#2b3a4a": "#c9d4de", "#2d5875": "#a9c9dd",
    "#302719": "#fff3dc", "#30404f": "#d7e0e7", "#344453": "#cbd6df",
    "#344454": "#cbd6df", "#344555": "#c4d0da", "#344556": "#c4d0da",
    "#354454": "#aab7c2", "#3a2228": "#fde9eb", "#3a2c19": "#fff2d9",
    "#401f25": "#fee9eb", "#46586a": "#9aa9b7", "#512931": "#f8dce0",
    "#52677b": "#9aabb9", "#586a7d": "#748596", "#607080": "#788795",
    "#657486": "#84919e", "#69502e": "#e7c98d", "#6b333d": "#e3a7ae",
    "#71323d": "#e2a6ad", "#73582f": "#e8d4a8", "#7f91a5": "#6a7c8e",
    "#8293a5": "#687b8d", "#8293a6": "#687b8d", "#8393a5": "#687b8d",
    "#8fa0b2": "#66798b", "#91a2b4": "#5d7183", "#92a2b5": "#5d7183",
    "#aebdcb": "#43586a", "#b4c4d2": "#465c6e", "#b5c2cf": "#4d6071",
    "#b9c6d2": "#455869", "#bdcbd8": "#3f5364", "#d3dfe9": "#364c5e",
    "#d4e0e9": "#364c5e", "#d8e2ec": "#344a5d", "#dce6ef": "#33495b",
    "#e5b36c": "#b47a21", "#e7edf5": "#1f2d3a", "#e7f3fa": "#294154",
    "#edc987": "#8b621f", "#edf3fa": "#26394a", "#ee7784": "#c54453",
    "#eff5fa": "#203241", "#f08d98": "#b6293a", "#f29aa3": "#ad3442",
    "#f2a0a7": "#b43b49", "#f2c17d": "#905c11", "#f2f6fb": "#1c2b38",
    "#f3d5a2": "#79571e", "#f4fff9": "#ffffff", "#55ddb0": "#19875f",
    "#75bfee": "#3685b5",
    "#77e4bd": "#147653", "#8fc9f3": "#236e9e", "#8fdec1": "#176e57",
    "#f29aa3": "#ad3442",
}


def build_stylesheet(theme: str = "dark", accent: str = "mint") -> str:
    """Return the application stylesheet for a validated theme and accent."""
    theme = theme if theme in THEMES else "dark"
    accent = accent if accent in ACCENTS else "mint"

    stylesheet = _BASE_STYLESHEET
    markers: dict[str, str] = {}
    for index, (color, slot) in enumerate(_ACCENT_SLOTS.items()):
        marker = f"__K922_ACCENT_{index}__"
        stylesheet = stylesheet.replace(color, marker)
        markers[marker] = slot

    if theme == "light":
        for dark_color, light_color in _LIGHT_COLORS.items():
            stylesheet = stylesheet.replace(dark_color, light_color)

    selected_accent = _ACCENT_COLORS[accent][theme]
    for marker, slot in markers.items():
        stylesheet = stylesheet.replace(marker, selected_accent[slot])
    return stylesheet


APP_STYLESHEET = build_stylesheet()
