"""Colours and the Qt style sheet - a calm, light, rounded look."""

import re
import sys

ACCENT = "#5B4FE0"
ACCENT_DARK = "#4A3FC4"
ACCENT_SOFT = "#EEECFD"
BG = "#F6F7FB"
CARD = "#FFFFFF"
BORDER = "#E3E5EE"
TEXT = "#1F2233"
MUTED = "#6B7086"
GOOD = "#1E9E63"
GOOD_SOFT = "#E6F6EE"
WARN = "#C98A06"
WARN_SOFT = "#FDF4DF"
BAD = "#D2445A"
BAD_SOFT = "#FCEBEE"
SIDEBAR = "#1E1B3A"

QSS = f"""
* {{ font-family: "Segoe UI", "Helvetica Neue", "Inter", Arial, sans-serif; font-size: 10.5pt; color: {TEXT}; }}
QMainWindow, #Page {{ background: {BG}; }}
QToolTip {{ background: {TEXT}; color: white; border: none; padding: 6px 8px; border-radius: 6px; }}

#Sidebar {{ background: {SIDEBAR}; border: none; }}
#Brand {{ color: white; font-size: 17pt; font-weight: 700; padding: 22px 20px 2px 22px; }}
#BrandSub {{ color: #A9A5D6; font-size: 9pt; padding: 0 20px 18px 22px; }}
#NavList {{ background: transparent; border: none; outline: none; }}
#NavList::item {{ color: #CFCDEB; padding: 11px 14px; margin: 2px 12px; border-radius: 10px; }}
#NavList::item:hover {{ background: #2C2852; color: white; }}
#NavList::item:selected {{ background: {ACCENT}; color: white; }}
#NavList::item:disabled {{ color: #7F7BAE; padding: 14px 18px 2px 18px; background: transparent; }}
#UpdatePill {{ background: #2E2A5C; color: white; border: 1px solid #5B4FE0; border-radius: 10px;
    padding: 10px 12px; text-align: left; font-weight: 600; }}
#UpdatePill:hover {{ background: {ACCENT}; color: white; }}
#UpdatePill:disabled {{ color: #CFCDEB; background: #26224A; }}
#SidebarFoot {{ color: #7F7BAE; font-size: 8.5pt; padding: 14px 22px; }}

#PageTitle {{ font-size: 20pt; font-weight: 700; }}
#PageSubtitle {{ color: {MUTED}; font-size: 10.5pt; }}
#Card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; }}
#CardTitle {{ font-size: 12pt; font-weight: 600; }}
#StepBadge {{ background: {ACCENT_SOFT}; color: {ACCENT}; border-radius: 12px; font-weight: 700;
              min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; }}
#Muted {{ color: {MUTED}; }}
#Hint {{ color: {MUTED}; font-size: 9pt; }}

#DropZone {{ background: #FAFAFF; border: 2px dashed #C9C5F3; border-radius: 14px; }}
#DropZone[hover="true"] {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
#DropIcon {{ font-size: 28pt; color: {ACCENT}; }}
#DropText {{ font-size: 11.5pt; font-weight: 600; }}

QLineEdit, QPlainTextEdit, QComboBox {{ background: white; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 8px 10px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 1.5px solid {ACCENT}; }}

QPushButton {{ background: white; border: 1px solid {BORDER}; border-radius: 9px; padding: 8px 16px; }}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:disabled {{ color: #B5B8C8; border-color: #ECEDF3; }}
QPushButton#Primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600; padding: 11px 26px;
    font-size: 11pt; }}
QPushButton#Primary:hover {{ background: {ACCENT_DARK}; color: white; }}
QPushButton#Primary:disabled {{ background: #C4C0EE; color: white; }}
QPushButton#Link {{ border: none; background: transparent; color: {ACCENT}; padding: 4px; }}
QPushButton#Link:hover {{ text-decoration: underline; }}
QPushButton#Danger {{ color: {BAD}; }}
QPushButton#Danger:hover {{ border-color: {BAD}; }}
QPushButton#Segment {{ border-radius: 0; padding: 9px 22px; }}
QPushButton#Segment:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1.5px solid #B9BCCD; background: white; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QListWidget#FileList {{ background: white; border: 1px solid {BORDER}; border-radius: 10px; padding: 4px; }}
QListWidget#FileList::item {{ padding: 6px 8px; border-radius: 6px; }}
QListWidget#FileList::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}

QTableWidget {{ background: white; border: 1px solid {BORDER}; border-radius: 10px; gridline-color: #F0F1F6;
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; }}
QHeaderView::section {{ background: #F3F3FA; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
    padding: 8px; font-weight: 600; }}

QProgressBar {{ background: #ECEBFA; border: none; border-radius: 6px; height: 10px; text-align: center;
    color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #CDCFDD; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

#Banner {{ border-radius: 12px; padding: 14px 16px; }}
#Banner[kind="good"] {{ background: {GOOD_SOFT}; border: 1px solid #BFE8D3; }}
#Banner[kind="warn"] {{ background: {WARN_SOFT}; border: 1px solid #F3DFA9; }}
#Banner[kind="bad"]  {{ background: {BAD_SOFT};  border: 1px solid #F5C6CF; }}
#Banner[kind="info"] {{ background: {ACCENT_SOFT}; border: 1px solid #D6D2FA; }}
#BannerTitle {{ font-size: 12.5pt; font-weight: 700; background: transparent; }}
#BannerText {{ background: transparent; }}

#HomeTile {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 16px; }}
#HomeTile:hover {{ border: 1.5px solid {ACCENT}; }}
#TileBadge {{ background: {ACCENT_SOFT}; border-radius: 12px; }}
#RecentRow {{ border-radius: 8px; }}
#RecentRow:hover {{ background: #F6F6FC; }}
#TileIcon {{ font-size: 26pt; background: transparent; }}
#TileTitle {{ font-size: 13pt; font-weight: 700; background: transparent; }}
#TileText {{ color: {MUTED}; background: transparent; }}
#WatermarkEdit {{ font-size: 12pt; }}
#WatermarkResult {{ font-size: 16pt; font-weight: 700; color: {ACCENT_DARK}; background: {ACCENT_SOFT};
    border-radius: 10px; padding: 14px 16px; }}
#KeyLabel {{ font-family: "Cascadia Mono", Consolas, Menlo, "DejaVu Sans Mono", monospace; font-size: 10.5pt;
    background: #F3F3FA; border-radius: 8px; padding: 10px; }}
"""


def _scale_points(qss: str, factor: float) -> str:
    return re.sub(r"(\d+(?:\.\d+)?)pt\b", lambda m: f"{float(m.group(1)) * factor:.1f}pt", qss)


# macOS draws 1pt = 1 pixel (72 dpi), Windows 1pt = 1.33 pixels (96 dpi). Scale the sizes up on a Mac so text is
# exactly as large as on Windows instead of looking tiny.
if sys.platform == "darwin":
    QSS = _scale_points(QSS, 96 / 72)
