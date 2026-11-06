"""Main window and application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..registry import Ledger
from ..settings import Settings
from . import icons, style
from .updates import UpdateController
from .pages import (PAGE_EXTRACT, PAGE_HISTORY, PAGE_HOME, DecryptPage, EmbedPage, EncryptPage, ExtractPage, HistoryPage, HomePage,
                    SettingsPage)

# (icon, label, section header shown above the item)
NAV = [("home", "Home", None),
       ("embed", "Embed watermark", "WATERMARK"), ("extract", "Extract watermark", None),
       ("lock", "Encrypt", "ENCRYPTION"), ("unlock", "Decrypt", None),
       ("history", "History", "MORE"), ("settings", "Settings", None)]


def resource(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "assets" / name


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.ledger = Ledger()
        self.updates = UpdateController(self.settings, self)
        self.setWindowTitle(f"{APP_NAME} — Document Watermarking & Encryption")
        self.resize(1180, 800)
        self.setMinimumSize(940, 640)

        root = QWidget()
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.setCentralWidget(root)

        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        brand = QLabel(APP_NAME)
        brand.setObjectName("Brand")
        sub = QLabel("Watermark • Trace • Encrypt")
        sub.setObjectName("BrandSub")
        sl.addWidget(brand)
        sl.addWidget(sub)
        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        self.nav.setIconSize(QSize(18, 18))
        self._nav_rows = []  # list row -> page index (section headers are not pages)
        for page, (icon, text, section) in enumerate(NAV):
            if section:
                head = QListWidgetItem(section, self.nav)
                head.setFlags(Qt.NoItemFlags)
                head.setData(Qt.UserRole, "section")
                f = head.font()
                f.setPointSizeF(8)
                f.setBold(True)
                head.setFont(f)
                self._nav_rows.append(None)
            item = QListWidgetItem(f"  {text}", self.nav)
            item.setIcon(icons.icon(icon, "#CFCDEB", "#FFFFFF", size=18))
            self._nav_rows.append(page)
        self.nav.setCursor(Qt.PointingHandCursor)
        sl.addWidget(self.nav, 1)
        self.update_pill = QPushButton()
        self.update_pill.setObjectName("UpdatePill")
        self.update_pill.setCursor(Qt.PointingHandCursor)
        self.update_pill.hide()
        self.update_pill.clicked.connect(lambda: self.updates.primary_action(self))
        pill_wrap = QHBoxLayout()
        pill_wrap.setContentsMargins(12, 0, 12, 4)
        pill_wrap.addWidget(self.update_pill)
        sl.addLayout(pill_wrap)
        self.updates.changed.connect(self._update_state)
        foot = QLabel(f"v{__version__}")
        foot.setObjectName("SidebarFoot")
        sl.addWidget(foot)
        lay.addWidget(side)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self._build_pages()
        self.nav.currentRowChanged.connect(self._go)
        self.nav.setCurrentRow(0)

    def _build_pages(self):
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.home = HomePage(self.settings, self.ledger)
        self.home.navigate.connect(self.open_page)
        self.embed = EmbedPage(self.settings, self.ledger)
        self.embed.check_file.connect(self.check_file)
        self.extract = ExtractPage(self.settings, self.ledger)
        self.encrypt = EncryptPage(self.settings)
        self.decrypt = DecryptPage(self.settings)
        self.history = HistoryPage(self.ledger)
        self.settings_page = SettingsPage(self.settings, self.updates)
        self.settings_page.changed.connect(self._settings_changed)
        for p in (self.home, self.embed, self.extract, self.encrypt, self.decrypt, self.history, self.settings_page):
            self.stack.addWidget(p)

    def _settings_changed(self):
        idx = self.stack.indexOf(self.home)
        self.stack.removeWidget(self.home)
        self.home.deleteLater()
        self.home = HomePage(self.settings, self.ledger)
        self.home.navigate.connect(self.open_page)
        self.stack.insertWidget(idx, self.home)

    def _update_state(self, state: str, text: str):
        labels = {
            "downloading": "⬇  " + text.replace("Downloading version", "Downloading"),
            "ready": f"✨  Update {self.updates.info.version if self.updates.info else ''} ready\nClick to install",
            "available": f"✨  Version {self.updates.info.version if self.updates.info else ''} available",
        }
        if state in labels:
            self.update_pill.setText(labels[state])
            self.update_pill.setEnabled(state != "downloading")
            self.update_pill.show()
        elif state != "checking":
            self.update_pill.hide()

    def check_file(self, path):
        """Embed page -> "Check it": show the new copy's watermark on the Extract page."""
        self.open_page(PAGE_EXTRACT)
        self.extract._trace_file(path)

    def open_page(self, page: int):
        self.nav.setCurrentRow(self._nav_rows.index(page))

    def _go(self, row: int):
        page = self._nav_rows[row] if 0 <= row < len(self._nav_rows) else None
        if page is None:
            return
        if page == PAGE_HISTORY:
            self.history.refresh()
        elif page == PAGE_HOME:
            self.home.refresh()
        self.stack.setCurrentIndex(page)


def main() -> int:
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VeilMark.App")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    check = resource("check.svg").as_posix()
    app.setStyleSheet(style.QSS + f'QCheckBox::indicator:checked {{ image: url("{check}"); }}')
    icon = resource("veilmark.png" if sys.platform == "darwin" else "veilmark.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    win = MainWindow()
    win.show()
    if sys.platform == "darwin":
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMessageBox

        from .. import macos, updater

        note = macos.startup_check(updater.mac_app_bundle())
        if note:
            QTimer.singleShot(600, lambda: QMessageBox.information(win, "Move VeilMark to Applications", note))
    win.updates.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
