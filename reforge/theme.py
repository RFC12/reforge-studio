"""Tema visual oscuro estilo dashboard de consola, con color de acento configurable."""
from PySide6.QtGui import QColor

ACCENTS = {
    "Esmeralda": "#19d3a2",
    "Neón azul": "#2f8cff",
    "Magma": "#ff5a36",
    "Violeta": "#9b6bff",
    "Ámbar": "#ffb020",
}

BG = "#0b0d10"
PANEL = "#12161c"
PANEL2 = "#171c24"
LINE = "#222934"
TEXT = "#e8ecf1"
MUTED = "#8b96a5"


def accent_color(name):
    return ACCENTS.get(name, ACCENTS["Esmeralda"])


def build_qss(accent):
    dark = QColor(accent).darker(260).name()
    soft = QColor(accent)
    soft.setAlpha(40)
    soft = f"rgba({soft.red()},{soft.green()},{soft.blue()},0.16)"
    return f"""
* {{ font-family: 'Segoe UI Variable Display','Segoe UI','Inter','Noto Sans',sans-serif; }}
QWidget {{ color: {TEXT}; font-size: 14px; }}
#Root {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {PANEL2}; color: {TEXT}; border: 1px solid {LINE}; padding: 6px; }}

/* ---------- barra lateral ---------- */
#Sidebar {{ background: #0f1217; border-right: 1px solid {LINE}; }}
#Brand {{ font-size: 19px; font-weight: 700; letter-spacing: 0.5px; }}
#BrandSub {{ color: {MUTED}; font-size: 11px; letter-spacing: 2px; }}
QPushButton#NavButton {{
    text-align: left; padding: 13px 20px; border: none; border-left: 4px solid transparent;
    background: transparent; font-size: 15px; color: {MUTED};
}}
QPushButton#NavButton:hover {{ background: #151a21; color: #ffffff; }}
QPushButton#NavButton:checked {{ border-left: 4px solid {accent}; background: {soft}; color: #ffffff; font-weight: 600; }}
#Version {{ color: #556070; font-size: 11px; }}

/* ---------- cabecera ---------- */
#PageTitle {{ font-size: 28px; font-weight: 300; }}
#Clock {{ color: {MUTED}; font-size: 16px; }}
#Section {{ color: {accent}; font-size: 12px; font-weight: 700; letter-spacing: 2px; }}
#Hint {{ color: {MUTED}; font-size: 12px; }}
#HintErr {{ color: #ff7b72; font-size: 12px; }}
#HintOk {{ color: #3fb950; font-size: 12px; }}
#BigNumber {{ font-size: 30px; font-weight: 300; }}

/* ---------- tiles ---------- */
#Tile {{ background: {PANEL2}; border: 2px solid {LINE}; border-radius: 6px; }}
#Tile:hover, #Tile:focus {{ border: 2px solid {accent}; background: #1b222c; }}
#Tile[hero="true"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {accent}, stop:1 {dark});
    border: 2px solid transparent;
}}
#Tile[hero="true"]:hover, #Tile[hero="true"]:focus {{ border: 2px solid #ffffff; }}
#TileGlyph {{ font-size: 34px; color: {accent}; }}
#Tile[hero="true"] #TileGlyph {{ color: #ffffff; font-size: 52px; }}
#TileTitle {{ font-size: 18px; font-weight: 600; }}
#Tile[hero="true"] #TileTitle {{ font-size: 26px; }}
#TileSub {{ color: {MUTED}; font-size: 12px; }}
#Tile[hero="true"] #TileSub {{ color: rgba(255,255,255,0.85); font-size: 13px; }}

/* ---------- paneles y tarjetas ---------- */
#Panel {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; }}
#Card {{ background: {PANEL2}; border: 1px solid {LINE}; border-radius: 8px; }}
#Card:hover {{ border: 1px solid {accent}; }}
#CardTitle {{ font-size: 17px; font-weight: 600; }}
#Chip {{ background: {soft}; color: {accent}; border-radius: 9px; padding: 2px 10px; font-size: 11px; font-weight: 700; }}
#Chip[kind="err"] {{ background: rgba(248,81,73,0.15); color: #ff7b72; }}
#Chip[kind="run"] {{ background: rgba(210,153,34,0.18); color: #e3b341; }}

/* ---------- controles ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit#Small {{
    background: #0d1015; border: 1px solid {LINE}; border-radius: 5px; padding: 7px 9px;
    selection-background-color: {accent}; selection-color: #000;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {accent}; }}
QComboBox QAbstractItemView {{ background: {PANEL2}; border: 1px solid {LINE}; selection-background-color: {accent}; selection-color: #000; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QPushButton {{
    background: {PANEL2}; border: 1px solid {LINE}; border-radius: 5px; padding: 8px 14px;
}}
QPushButton:hover {{ border: 1px solid {accent}; background: #1d2530; }}
QPushButton:disabled {{ color: #4b5563; border-color: #1a1f27; }}
QPushButton#Primary {{
    background: {accent}; color: #04130e; border: none; font-weight: 700; font-size: 15px; padding: 11px 20px;
}}
QPushButton#Primary:hover {{ background: {QColor(accent).lighter(115).name()}; }}
QPushButton#Primary:disabled {{ background: #1f2a28; color: #4b5563; }}
QPushButton#Danger:hover {{ border: 1px solid #f85149; color: #ff7b72; }}
QCheckBox {{ spacing: 9px; padding: 3px 0; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 4px; border: 1px solid #3a4452; background: #0d1015; }}
QCheckBox::indicator:checked {{ background: {accent}; border: 1px solid {accent}; }}
QPushButton#ProfileChip {{ background: transparent; border: none; border-top: 1px solid #1c232c; border-radius: 0; text-align: left; margin: 6px 0 8px 0; }}
QPushButton#ProfileChip:hover {{ background: #141a21; }}
QRadioButton {{ spacing: 10px; font-weight: 600; padding: 4px 0; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 9px; border: 2px solid #3a4452; background: #0d1015; }}
QRadioButton::indicator:checked {{ background: {accent}; border: 2px solid {accent}; }}
QRadioButton:checked {{ color: {accent}; }}
QRadioButton:disabled {{ color: #5b6573; }}
QProgressBar {{ background: #0d1015; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
QPlainTextEdit#Log {{
    background: #07090c; border: 1px solid {LINE}; border-radius: 6px; padding: 8px;
    font-family: 'Cascadia Mono','Consolas','JetBrains Mono','DejaVu Sans Mono',monospace; font-size: 12px;
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2a323e; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {accent}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2a323e; border-radius: 4px; min-width: 30px; }}

/* ---------- diálogos, pestañas, listas y tablas ---------- */
QDialog, QMessageBox, QFileDialog {{ background: {PANEL}; }}
QMessageBox QLabel {{ color: {TEXT}; }}
QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 8px; background: {PANEL}; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {MUTED}; padding: 10px 13px; border: none;
    border-bottom: 3px solid transparent; font-size: 14px;
}}
QTabBar::tab:hover {{ color: #ffffff; }}
QTabBar::tab:selected {{ color: #ffffff; border-bottom: 3px solid {accent}; font-weight: 600; }}
QListWidget, QTableWidget, QTreeWidget {{
    background: #0d1015; border: 1px solid {LINE}; border-radius: 6px; gridline-color: {LINE};
    selection-background-color: {soft}; selection-color: #ffffff; alternate-background-color: #10141a;
}}
QListWidget::item, QTreeWidget::item {{ padding: 5px 4px; }}
QHeaderView::section {{ background: {PANEL2}; color: {MUTED}; border: none; border-bottom: 1px solid {LINE}; padding: 6px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {PANEL2}; border: none; }}

/* ---------- seguimiento de pasos ---------- */
#StepPill {{ background: {PANEL2}; border: 1px solid {LINE}; border-radius: 6px; }}
#StepNum {{ background: #232b36; color: {MUTED}; border-radius: 13px; font-weight: 700; }}
#StepTitle {{ color: {MUTED}; font-size: 12px; }}
#StepPill[state="running"] {{ border: 1px solid {accent}; background: {soft}; }}
#StepPill[state="running"] #StepNum {{ background: {accent}; color: #04130e; }}
#StepPill[state="running"] #StepTitle {{ color: #fff; }}
#StepPill[state="done"] #StepNum {{ background: #1f6f45; color: #e6ffef; }}
#StepPill[state="done"] #StepTitle {{ color: {TEXT}; }}
#StepPill[state="error"] {{ border: 1px solid #f85149; }}
#StepPill[state="error"] #StepNum {{ background: #f85149; color: #fff; }}
#StepPill[state="skipped"] #StepTitle {{ color: #4b5563; }}
#StepPill[state="off"] {{ background: transparent; border: 1px dashed #1f2630; }}
#StepPill[state="off"] #StepTitle, #StepPill[state="off"] #StepNum {{ color: #3a4350; }}
QPushButton[toggle="true"] {{ border: 2px solid transparent; }}
QPushButton[toggle="true"]:checked {{ border: 2px solid {accent}; background: {soft}; color: #ffffff; font-weight: 700; }}
"""
