"""Reusable widgets: drop zone, file list, cards, banners and a background worker."""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Callable, List

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)


# --------------------------------------------------------------------------- #
# Background work
# --------------------------------------------------------------------------- #
class _Signals(QObject):
    progress = Signal(str, float)
    done = Signal(object)
    failed = Signal(str)


class Worker(QRunnable):
    """Run ``fn(progress)`` on the thread pool; ``progress(msg, fraction)`` is thread-safe."""

    def __init__(self, fn: Callable):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self):
        try:
            result = self.fn(lambda msg, frac: self.signals.progress.emit(msg, float(frac)))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            traceback.print_exc()
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.signals.done.emit(result)


# Workers that are still running. Without a reference here, Python garbage-collects the Worker (and
# the signals object it owns) as soon as the caller drops it - and the job's result is silently lost,
# leaving the screen stuck on "Checking…" / a spinning progress bar.
_ACTIVE: set = set()


def run_in_background(fn, on_done=None, on_failed=None, on_progress=None) -> Worker:
    w = Worker(fn)
    if on_done:
        w.signals.done.connect(on_done)
    if on_failed:
        w.signals.failed.connect(on_failed)
    if on_progress:
        w.signals.progress.connect(on_progress)
    # connected last, so the caller's handlers have run before the worker is released
    w.signals.done.connect(lambda _r, w=w: _ACTIVE.discard(w))
    w.signals.failed.connect(lambda _e, w=w: _ACTIVE.discard(w))
    _ACTIVE.add(w)
    QThreadPool.globalInstance().start(w)
    return w


def reveal_in_explorer(path: Path) -> None:
    path = Path(path)
    if sys.platform == "win32" and path.exists():
        subprocess.Popen(["explorer", "/select,", str(path)])  # noqa: S603,S607
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if path.is_file() else path)))


# --------------------------------------------------------------------------- #
# Layout helpers
# --------------------------------------------------------------------------- #
def label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


class Card(QFrame):
    def __init__(self, title: str = "", step: str = "", subtitle: str = ""):
        super().__init__()
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(22, 18, 22, 20)
        self.body.setSpacing(12)
        if title:
            row = QHBoxLayout()
            row.setSpacing(10)
            if step:
                badge = QLabel(step)
                badge.setObjectName("StepBadge")
                badge.setAlignment(Qt.AlignCenter)
                row.addWidget(badge)
            t = QLabel(title)
            t.setObjectName("CardTitle")
            row.addWidget(t)
            row.addStretch()
            self.header = row
            self.body.addLayout(row)
        if subtitle:
            self.body.addWidget(label(subtitle, "Muted"))

    def add(self, w):
        if isinstance(w, QWidget):
            self.body.addWidget(w)
        else:
            self.body.addLayout(w)
        return w


class Banner(QFrame):
    """Coloured message box; kind = good | warn | bad | info."""

    ICONS = {"good": "✔", "warn": "!", "bad": "✖", "info": "i"}

    def __init__(self):
        super().__init__()
        self.setObjectName("Banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(14)
        self.icon = QLabel()
        self.icon.setFixedSize(34, 34)
        self.icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.icon, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = label("", "BannerTitle")
        self.text = label("", "BannerText")
        col.addWidget(self.title)
        col.addWidget(self.text)
        lay.addLayout(col, 1)
        self.hide()

    def show_message(self, kind: str, title: str, text: str = ""):
        from . import style

        colour = {"good": style.GOOD, "warn": style.WARN, "bad": style.BAD, "info": style.ACCENT}[kind]
        self.setProperty("kind", kind)
        self.icon.setText(self.ICONS[kind])
        self.icon.setStyleSheet(f"background:{colour};color:white;border-radius:17px;font-weight:800;font-size:13pt;")
        self.title.setText(title)
        self.text.setText(text)
        self.text.setVisible(bool(text))
        self.style().unpolish(self)
        self.style().polish(self)
        self.show()


# --------------------------------------------------------------------------- #
# Drag & drop
# --------------------------------------------------------------------------- #
class DropZone(QFrame):
    filesDropped = Signal(list)

    def __init__(self, text: str, hint: str, filters: str = "All files (*.*)", multiple: bool = True,
                 icon: str = "⇪"):
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.filters = filters
        self.multiple = multiple
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(4)
        for txt, name in ((icon, "DropIcon"), (text, "DropText"), (hint, "Hint")):
            lab = QLabel(txt)
            lab.setObjectName(name)
            lab.setAlignment(Qt.AlignCenter)
            lab.setAttribute(Qt.WA_TransparentForMouseEvents)
            lay.addWidget(lab)

    def _set_hover(self, on: bool):
        self.setProperty("hover", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._set_hover(True)

    def dragLeaveEvent(self, e):
        self._set_hover(False)

    def dropEvent(self, e):
        self._set_hover(False)
        paths = []
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                paths += [c for c in p.rglob("*") if c.is_file()]
            elif p.is_file():
                paths.append(p)
        if paths:
            self.filesDropped.emit(paths if self.multiple else paths[:1])

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.browse()

    def browse(self):
        if self.multiple:
            files, _ = QFileDialog.getOpenFileNames(self, "Choose files", "", self.filters)
        else:
            f, _ = QFileDialog.getOpenFileName(self, "Choose a file", "", self.filters)
            files = [f] if f else []
        if files:
            self.filesDropped.emit([Path(f) for f in files])


class FileList(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.list = QListWidget()
        self.list.setObjectName("FileList")
        lay.addWidget(self.list)
        row = QHBoxLayout()
        self.count = label("", "Hint")
        row.addWidget(self.count)
        row.addStretch()
        rm = QPushButton("Remove selected")
        rm.setObjectName("Link")
        rm.clicked.connect(self.remove_selected)
        clear = QPushButton("Clear all")
        clear.setObjectName("Link")
        clear.clicked.connect(self.clear)
        row.addWidget(rm)
        row.addWidget(clear)
        lay.addLayout(row)
        self._paths: List[Path] = []
        self._refresh()

    def add(self, paths):
        for p in paths:
            p = Path(p)
            if p not in self._paths:
                self._paths.append(p)
        self._refresh()

    def paths(self) -> List[Path]:
        return list(self._paths)

    def remove_selected(self):
        rows = sorted((self.list.row(i) for i in self.list.selectedItems()), reverse=True)
        for r in rows:
            del self._paths[r]
        self._refresh()

    def clear(self):
        self._paths.clear()
        self._refresh()

    def _refresh(self):
        self.list.clear()
        for p in self._paths:
            item = QListWidgetItem(f"{_icon_for(p)}  {p.name}")
            item.setToolTip(str(p))
            self.list.addItem(item)
        n = len(self._paths)
        self.list.setFixedHeight(min(160, 12 + 32 * max(1, n)))
        self.count.setText(f"{n} file{'s' if n != 1 else ''} selected" if n else "No files yet")
        self.setVisible(bool(n))
        self.changed.emit()


def _icon_for(p: Path) -> str:
    ext = p.suffix.lower()
    if ext.startswith(".doc"):
        return "📄"
    if ext.startswith(".ppt"):
        return "📊"
    if ext.startswith(".xls"):
        return "📈"
    if ext in (".png", ".bmp", ".tif", ".tiff"):
        return "🖼"
    if ext == ".vmk":
        return "🔒"
    return "📃"


def open_path(path: Path):
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - user-initiated
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
