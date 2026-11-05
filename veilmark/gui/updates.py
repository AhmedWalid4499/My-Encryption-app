"""Background update checking/downloading for the GUI."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import __version__, updater
from ..settings import Settings
from .widgets import run_in_background

RECHECK_MS = 6 * 60 * 60 * 1000  # every 6 hours while the app stays open


class UpdateController(QObject):
    """States: idle | checking | downloading | ready | available | uptodate | error."""

    changed = Signal(str, str)  # state, human-readable text

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.state, self.text = "idle", ""
        self.info = None
        self.installer = None
        self._busy = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self.check(manual=False))
        self._timer.start(RECHECK_MS)

    def start(self):
        if self.settings.check_updates:
            QTimer.singleShot(2500, lambda: self.check(manual=False))

    def _set(self, state, text):
        self.state, self.text = state, text
        self.changed.emit(state, text)

    # -- checking ----------------------------------------------------------- #
    def check(self, manual: bool = True):
        if self._busy or (not manual and not self.settings.check_updates):
            return
        if self.state == "ready":
            self._set("ready", self.text)
            return
        self._busy = True
        if manual:
            self._set("checking", "Checking for updates…")
        run_in_background(lambda _p: updater.check(), lambda info: self._checked(info, manual),
                          lambda err: self._failed(err, manual))

    def _checked(self, info, manual):
        self._busy = False
        self.settings.last_update_check = time.time()
        self.settings.save()
        if info is None:
            if manual:
                self._set("uptodate", f"You're up to date (version {__version__}).")
            return
        self.info = info
        if updater.can_self_install():
            self._download()
        else:
            self._set("available", f"Version {info.version} is available.")

    def _failed(self, err, manual):
        self._busy = False
        if manual:
            self._set("error", err)

    # -- downloading -------------------------------------------------------- #
    def _download(self):
        info = self.info
        self._busy = True
        self._set("downloading", f"Downloading version {info.version}… 0%")
        run_in_background(lambda p: updater.download(info, p), self._downloaded,
                          lambda err: self._failed(err, True),
                          lambda _m, f: self._set("downloading",
                                                  f"Downloading version {info.version}… {int(f * 100)}%"))

    def _downloaded(self, path):
        self._busy = False
        self.installer = path
        self._set("ready", f"Version {self.info.version} is ready to install.")

    # -- user actions -------------------------------------------------------- #
    def primary_action(self, parent=None):
        """What the sidebar / settings button does in the current state."""
        if self.state == "ready" and self.installer:
            self.install(parent)
        elif self.state == "available" and self.info:
            QDesktopServices.openUrl(QUrl(self.info.page))
        elif self.state == "error" and self.info:
            self._download()
        else:
            self.check(manual=True)

    def install(self, parent=None):
        answer = QMessageBox.question(
            parent, "Install update",
            f"VeilMark will close, install version {self.info.version} and reopen automatically.\n\n"
            "Your settings, team key and sharing history are kept.\n\nInstall now?")
        if answer != QMessageBox.Yes:
            return
        try:
            updater.launch_installer(self.installer)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(parent, "Update failed", str(exc))
            return
        QApplication.quit()
