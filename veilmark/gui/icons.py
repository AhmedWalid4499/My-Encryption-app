"""Crisp line icons drawn from inline SVG (consistent on every Windows setup, unlike emoji)."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 24x24, stroke-based paths (stroke colour is filled in at render time)
_PATHS = {
    "home": '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "embed": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13 7l4 4"/><path d="M14 20h6"/>',
    "extract": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/><path d="M8 11h6"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'
            '<path d="M12 15v2"/>',
    "unlock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.6-1.8"/>'
              '<path d="M12 15v2"/>',
    "history": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
    "settings": '<path d="M4 6h9"/><path d="M19 6h1"/><circle cx="16" cy="6" r="2.5"/>'
                '<path d="M4 12h3"/><path d="M13 12h7"/><circle cx="10" cy="12" r="2.5"/>'
                '<path d="M4 18h11"/><circle cx="18" cy="18" r="2.5"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "upload": '<path d="M12 15V4"/><path d="M7 9l5-5 5 5"/><path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.8 2.8L16.5 9"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5"/><path d="M12 16.5v.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.5v.01"/>',
    "cross": '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6"/><path d="M15 9l-6 6"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "file": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10'
            'a1 1 0 0 0 1 1h3"/>',
    "open": '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7'
            'a1 1 0 0 1 1-1h5"/>',
}


def svg(name: str, color: str, width: float = 1.8) -> bytes:
    body = _PATHS[name]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


@lru_cache(maxsize=256)
def pixmap(name: str, color: str, size: int = 20, width: float = 1.8, ratio: float = 2.0) -> QPixmap:
    px = QPixmap(int(size * ratio), int(size * ratio))
    px.fill(Qt.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg(name, color, width))).render(painter, QRectF(0, 0, px.width(), px.height()))
    painter.end()
    px.setDevicePixelRatio(ratio)
    return px


def icon(name: str, color: str, selected_color: str = "", size: int = 20) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal)
    if selected_color:
        ic.addPixmap(pixmap(name, selected_color, size), QIcon.Selected)
        ic.addPixmap(pixmap(name, selected_color, size), QIcon.Active)
    return ic


def names():
    return sorted(_PATHS)
