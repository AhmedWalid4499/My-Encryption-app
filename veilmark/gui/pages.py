"""The application pages."""

from __future__ import annotations

import datetime as dt
import html
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QCompleter, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import __version__
from ..crypto import decrypt_file, encrypt_file, is_encrypted_file
from ..registry import Ledger
from ..service import TraceReport, protect_file, trace_file, trace_pasted_text
from ..settings import Settings
from ..watermark.engine import SUPPORTED_PROTECT
from . import icons, style
from .widgets import (REVEAL_LABEL, Banner, Card, DropZone, FileList, label, open_path, reveal_in_explorer,
                      run_in_background)

OFFICE_FILTER = ("Documents (*.docx *.pptx *.xlsx *.docm *.pptm *.xlsm *.png *.bmp *.tif *.tiff *.txt *.csv *.md "
                 "*.html *.htm);;Word (*.docx *.docm);;PowerPoint (*.pptx *.pptm);;Excel (*.xlsx *.xlsm);;"
                 "Pictures (*.png *.bmp *.tif *.tiff);;All files (*.*)")


def _fmt_time(iso: str) -> str:
    if not iso:
        return "—"
    try:
        t = dt.datetime.fromisoformat(iso).astimezone()
        return t.strftime("%d %b %Y, %H:%M")
    except ValueError:
        return iso


class Page(QScrollArea):
    """Scrollable page with a title and subtitle."""

    def __init__(self, title: str, subtitle: str):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("Page")
        self.setWidget(inner)
        self.layout_ = QVBoxLayout(inner)
        self.layout_.setContentsMargins(36, 30, 36, 30)
        self.layout_.setSpacing(18)
        self.layout_.addWidget(label(title, "PageTitle"))
        self.layout_.addWidget(label(subtitle, "PageSubtitle"))

    def add(self, w, stretch: int = 0):
        if isinstance(w, QWidget):
            self.layout_.addWidget(w, stretch)
        else:
            self.layout_.addLayout(w, stretch)
        return w

    def finish(self):
        self.layout_.addStretch(1)

    def scroll_to(self, w):
        from PySide6.QtCore import QTimer

        QTimer.singleShot(60, lambda: self.ensureWidgetVisible(w, 0, 40))


# =========================================================================== #
# Home
# =========================================================================== #
class HomeTile(QFrame):
    clicked = Signal()

    def __init__(self, icon: str, title: str, text: str):
        super().__init__()
        self.setObjectName("HomeTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(150)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        badge = QLabel()
        badge.setObjectName("TileBadge")
        badge.setFixedSize(46, 46)
        badge.setAlignment(Qt.AlignCenter)
        badge.setPixmap(icons.pixmap(icon, style.ACCENT, 24, 1.8))
        badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(badge)
        lay.addSpacing(6)
        for t, n in ((title, "TileTitle"), (text, "TileText")):
            lab = QLabel(t)
            lab.setObjectName(n)
            lab.setWordWrap(True)
            lab.setAttribute(Qt.WA_TransparentForMouseEvents)
            lay.addWidget(lab)
        lay.addStretch()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


# sidebar / stack order (also used by the Home tiles)
PAGE_HOME, PAGE_EMBED, PAGE_EXTRACT, PAGE_ENCRYPT, PAGE_DECRYPT, PAGE_HISTORY, PAGE_SETTINGS = range(7)


class HomePage(Page):
    navigate = Signal(int)

    def __init__(self, settings: Settings, ledger: Optional[Ledger] = None):
        greeting = f"Welcome back, {settings.owner_name.split()[0]}" if settings.owner_name else "Welcome to VeilMark"
        super().__init__(greeting, "What would you like to do?")
        self.ledger = ledger
        self.setup_banner = Banner()
        self.add(self.setup_banner)
        if not settings.owner_name:
            self.setup_banner.show_message(
                "info", "One quick thing first",
                "Add your name in Settings so every watermark records you as the owner.")

        def section(title, tiles):
            self.add(label(title, "CardTitle"))
            grid = QGridLayout()
            grid.setSpacing(16)
            for i, (icon, name, text, page) in enumerate(tiles):
                tile = HomeTile(icon, name, text)
                tile.clicked.connect(lambda p=page: self.navigate.emit(p))
                grid.addWidget(tile, 0, i)
            self.add(grid)

        section("Watermark", [
            ("embed", "Embed a watermark", "Type your watermark text and hide it invisibly inside Word, PowerPoint, "
                                         "Excel or picture files.", PAGE_EMBED),
            ("extract", "Extract a watermark", "Open any file to reveal the hidden watermark text and who the copy "
                                               "was given to.", PAGE_EXTRACT),
        ])
        section("Encryption", [
            ("lock", "Encrypt files", "Lock any file with a password using the hyperchaotic thesis cipher.",
             PAGE_ENCRYPT),
            ("unlock", "Decrypt files", "Unlock .vmk files with the password they were encrypted with.",
             PAGE_DECRYPT),
        ])
        self.recent_card = Card("Recent watermarks")
        self.recent_lay = QVBoxLayout()
        self.recent_lay.setSpacing(2)
        self.recent_card.add(self.recent_lay)
        self.add(self.recent_card)
        self.finish()
        self.refresh()

    def refresh(self):
        while self.recent_lay.count():
            w = self.recent_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        items = self.ledger.search("", limit=5) if self.ledger else []
        self.recent_card.setVisible(bool(items))
        for it in items:
            row = QFrame()
            row.setObjectName("RecentRow")
            h = QHBoxLayout(row)
            h.setContentsMargins(8, 6, 8, 6)
            ic = QLabel()
            ic.setPixmap(icons.pixmap("file", style.MUTED, 18))
            h.addWidget(ic)
            text = it.message or it.recipient or "—"
            lab = QLabel(f"<b>{html.escape(Path(it.output_file).name)}</b>"
                         f"<br><span style='color:{style.MUTED}'>“{html.escape(text)}” · {_fmt_time(it.timestamp)}"
                         "</span>")
            h.addWidget(lab, 1)
            if Path(it.output_file).exists():
                b = QPushButton(REVEAL_LABEL)
                b.clicked.connect(lambda _=False, p=Path(it.output_file): reveal_in_explorer(p))
                h.addWidget(b)
            self.recent_lay.addWidget(row)


# =========================================================================== #
# Embed watermark
# =========================================================================== #
LAYER_OPTIONS = [
    ("properties", "Encrypted document properties", "Stores the full, encrypted watermark & history."),
    ("custom_xml", "Hidden custom XML part", "A second encrypted copy in a hidden data part of the file."),
    ("invisible_text", "Invisible text marks", "Zero-width characters in the text. Survive copy & paste, "
                                               "‘Inspect Document’ and copying slides into other decks."),
    ("hidden_sheet", "Hidden data sheet (Excel)", "A ‘very hidden’ worksheet that can't be unhidden from the "
                                                  "normal Excel menu."),
    ("images", "Picture pixels (LSB)", "Hides the watermark in the least significant bits of PNG/BMP pictures, "
                                       "like the original thesis. Lost if pictures are compressed to JPEG."),
    ("excel_cell_text", "Also mark Excel cell text (advanced)", "Adds invisible marks to long text cells. "
                                                                "Can affect formulas that compare text - "
                                                                "off by default."),
]


class EmbedPage(Page):
    check_file = Signal(object)  # ask the window to open Extract on a freshly watermarked copy

    def __init__(self, settings: Settings, ledger: Ledger):
        super().__init__("Embed a watermark",
                         "Write your watermark, choose the files, and VeilMark hides it inside them.")
        self.settings, self.ledger = settings, ledger

        # 1. watermark text -------------------------------------------------
        text_card = Card("Write your watermark", "1",
                         "This text is hidden invisibly inside the file. Use Extract to read it back later.")
        self.message = QPlainTextEdit()
        self.message.setObjectName("WatermarkEdit")
        default = f"© {dt.date.today().year} {settings.organization or settings.owner_name}".strip()
        self.message.setPlaceholderText(f"e.g.  {default if len(default) > 7 else '© 2026 BookBeans'}"
                                        " – Confidential, do not distribute")
        self.message.setFixedHeight(84)
        if settings.last_message:
            self.message.setPlainText(settings.last_message)  # remembered from last time
        self.message.textChanged.connect(self._changed)
        text_card.add(self.message)
        self.count = label("", "Hint")
        text_card.add(self.count)
        self.footer_cb = QCheckBox("Also show this text visibly as a footer on every page / slide")
        self.footer_cb.setChecked(settings.visible_footer)
        self.footer_cb.setToolTip("Word: page footer · PowerPoint: small grey line at the bottom of each slide · "
                                  "Excel: printed page footer. The invisible watermark is always added too.")
        self.footer_cb.toggled.connect(self._footer_toggled)
        text_card.add(self.footer_cb)
        self.add(text_card)

        # 2. files ----------------------------------------------------------
        files = Card("Choose the files", "2")
        self.drop = DropZone("Drag & drop files or folders here", "or click to browse  •  Word, PowerPoint, Excel, "
                             "PNG/BMP pictures and text files", OFFICE_FILTER, icon="upload")
        self.drop.filesDropped.connect(self._add_files)
        files.add(self.drop)
        self.files = FileList()
        self.files.changed.connect(self._update_button)
        files.add(self.files)
        self.add(files)

        # 3. optional recipient + options -----------------------------------
        opts = Card("Options", "3")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        self.recipient = QLineEdit()
        self.recipient.setPlaceholderText("Optional – e.g. Sara Ahmed. Lets you trace a leaked copy back to them.")
        grid.addWidget(QLabel("Copy for"), 0, 0)
        grid.addWidget(self.recipient, 0, 1)
        opts.add(grid)
        out_row = QHBoxLayout()
        self.out_label = label("", "Hint")
        out_btn = QPushButton("Change save folder…")
        out_btn.clicked.connect(self._choose_out)
        out_row.addWidget(self.out_label, 1)
        out_row.addWidget(out_btn)
        opts.add(out_row)
        toggle = QPushButton("Advanced: hiding layers ▾")
        toggle.setObjectName("Link")
        opts.add(toggle)
        self.layer_box = QWidget()
        lb = QVBoxLayout(self.layer_box)
        lb.setContentsMargins(0, 0, 0, 0)
        self.layer_checks = {}
        for key, title, tip in LAYER_OPTIONS:
            cb = QCheckBox(title)
            cb.setChecked(bool(settings.layers.get(key, True)))
            cb.setToolTip(tip)
            cb.toggled.connect(lambda on, k=key: self._set_layer(k, on))
            lb.addWidget(cb)
            lb.addWidget(label(tip, "Hint"))
            self.layer_checks[key] = cb
        self.layer_box.hide()
        toggle.clicked.connect(lambda: (self.layer_box.setVisible(not self.layer_box.isVisible()),
                                        toggle.setText("Advanced: hiding layers ▴" if self.layer_box.isVisible()
                                                       else "Advanced: hiding layers ▾")))
        opts.add(self.layer_box)
        self.add(opts)
        self._show_out()

        run_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.hide()
        run_row.addWidget(self.progress, 1)
        self.go = QPushButton("Embed watermark")
        self.go.setObjectName("Primary")
        self.go.setCursor(Qt.PointingHandCursor)
        self.go.clicked.connect(self._run)
        run_row.addWidget(self.go)
        self.add(run_row)

        self.banner = Banner()
        self.add(self.banner)
        self.results = QWidget()
        self.results_lay = QVBoxLayout(self.results)
        self.results_lay.setContentsMargins(0, 0, 0, 0)
        self.add(self.results)
        self.finish()
        self.refresh_completer()
        self._changed()

    # -- helpers ------------------------------------------------------------ #
    def text(self) -> str:
        return self.message.toPlainText().strip()

    def refresh_completer(self):
        names = sorted({i.recipient for i in self.ledger.search("") if i.recipient})
        comp = QCompleter(names)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.recipient.setCompleter(comp)

    def _changed(self):
        n = len(self.text())
        self.count.setText(f"{n} characters" if n else "Required")
        self._update_button()

    def _set_layer(self, key, on):
        self.settings.layers[key] = on
        self.settings.save()

    def _footer_toggled(self, on):
        self.settings.visible_footer = on
        self.settings.save()

    def _show_out(self):
        folder = self.settings.output_folder
        where = folder if folder else "the same folder as each original"
        self.out_label.setText(f"Watermarked copies are saved to {where} as “name - watermarked”. "
                               "Originals are never changed.")

    def _choose_out(self):
        folder = QFileDialog.getExistingDirectory(self, "Where should watermarked copies be saved?")
        self.settings.output_folder = folder or ""
        self.settings.save()
        self._show_out()

    def _add_files(self, paths):
        ok = [p for p in paths if p.suffix.lower() in SUPPORTED_PROTECT]
        skipped = len(paths) - len(ok)
        self.files.add(ok)
        if skipped:
            self.banner.show_message("warn", f"{skipped} file(s) skipped",
                                     "Only Word, PowerPoint, Excel (2007+), PNG/BMP/TIFF pictures and text "
                                     "files can be watermarked. Old .doc/.ppt/.xls files must be re-saved in the "
                                     "new format first.")
        else:
            self.banner.hide()

    def _update_button(self):
        n = len(self.files.paths())
        self.go.setEnabled(n > 0 and bool(self.text()))
        self.go.setText(f"Embed watermark in {n} file{'s' if n != 1 else ''}" if n else "Embed watermark")

    def _clear_results(self):
        while self.results_lay.count():
            w = self.results_lay.takeAt(0).widget()
            if w:
                w.deleteLater()

    # -- run ---------------------------------------------------------------- #
    def _run(self):
        paths = self.files.paths()
        message, recipient = self.text(), self.recipient.text().strip()
        self.go.setEnabled(False)
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self.progress.show()
        self.banner.hide()
        self._clear_results()
        settings = self.settings

        def job(progress):
            ledger = Ledger(self.ledger.path)  # sqlite connections per thread
            out = []
            for i, p in enumerate(paths):
                progress(p.name, i)
                try:
                    out.append((p, protect_file(p, recipient, message=message, settings=settings,
                                                ledger=ledger), None))
                except Exception as exc:  # noqa: BLE001
                    out.append((p, None, str(exc)))
                progress(p.name, i + 1)
            return out

        run_in_background(job, self._done, self._failed, lambda m, v: self.progress.setValue(int(v)))

    def _failed(self, msg):
        self.progress.hide()
        self._update_button()
        self.banner.show_message("bad", "Something went wrong", msg)

    def _done(self, results):
        self.progress.hide()
        self._update_button()
        ok = [r for r in results if r[1]]
        bad = [r for r in results if not r[1]]
        if ok and not bad:
            self.banner.show_message("good", f"Watermark embedded in {len(ok)} file{'s' if len(ok) != 1 else ''}",
                                     f"Hidden text: “{self.text()}”\nShare the new “- watermarked” copies, "
                                     "not the originals.")
        elif ok:
            self.banner.show_message("warn", f"{len(ok)} watermarked, {len(bad)} failed", "See the details below.")
        else:
            self.banner.show_message("bad", "No files could be watermarked", "See the details below.")
        for src, res, err in results:
            card = QFrame()
            card.setObjectName("Card")
            row = QHBoxLayout(card)
            row.setContentsMargins(16, 12, 16, 12)
            if res:
                kind = "already watermarked – new watermark added to its history" if res.reshared else "new watermark"
                text = (f"<b>{html.escape(res.output.name)}</b><br><span style='color:{style.MUTED}'>{kind}</span>")
                lab = QLabel(text)
                lab.setWordWrap(True)
                tick = QLabel()
                tick.setPixmap(icons.pixmap("check", style.GOOD, 26, 2.0))
                row.addWidget(tick)
                row.addWidget(lab, 1)
                b1 = QPushButton(REVEAL_LABEL)
                b1.clicked.connect(lambda _=False, p=res.output: reveal_in_explorer(p))
                b2 = QPushButton("Open")
                b2.clicked.connect(lambda _=False, p=res.output: open_path(p))
                b3 = QPushButton("Check it")
                b3.setToolTip("Open this copy in Extract to see the hidden watermark")
                b3.clicked.connect(lambda _=False, p=res.output: self.check_file.emit(p))
                row.addWidget(b1)
                row.addWidget(b2)
                row.addWidget(b3)
            else:
                lab = QLabel(f"<b>{html.escape(src.name)}</b><br><span style='color:{style.BAD}'>"
                             f"{html.escape(err)}</span>")
                lab.setWordWrap(True)
                warn = QLabel()
                warn.setPixmap(icons.pixmap("alert", style.BAD, 26, 2.0))
                row.addWidget(warn)
                row.addWidget(lab, 1)
            self.results_lay.addWidget(card)
        if ok:
            self.files.clear()
        self.refresh_completer()
        self.scroll_to(self.banner)


# =========================================================================== #
# Extract watermark
# =========================================================================== #
PLAIN_LAYER_NAMES = {
    "Document properties": "In the file's properties (encrypted)",
    "Custom XML part": "In a hidden data section of the file",
    "Invisible text marks": "As invisible marks inside the text",
    "Hidden data sheet": "In a hidden Excel sheet",
    "Image pixels (LSB)": "Inside the pictures' pixels",
}


class ExtractPage(Page):
    def __init__(self, settings: Settings, ledger: Ledger):
        super().__init__("Extract a watermark",
                         "Open a file to reveal its hidden watermark text and who the copy was given to.")
        self.settings, self.ledger = settings, ledger
        self.last: Optional[TraceReport] = None

        src = Card("Choose a file")
        self.drop = DropZone("Drop a file here", "or click to browse  •  Word, PowerPoint, Excel, pictures or "
                             "text files", "All files (*.*)", multiple=False, icon="extract")
        self.drop.filesDropped.connect(lambda ps: self._trace_file(ps[0]))
        src.add(self.drop)
        paste_toggle = QPushButton("…or check text copied from an email, chat or website ▾")
        paste_toggle.setObjectName("Link")
        src.add(paste_toggle)
        self.paste_box = QWidget()
        pb = QVBoxLayout(self.paste_box)
        pb.setContentsMargins(0, 0, 0, 0)
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText("Paste text here. Invisible watermarks survive copy & paste.")
        self.paste.setMinimumHeight(110)
        pb.addWidget(self.paste)
        check = QPushButton("Extract from text")
        check.setObjectName("Primary")
        check.clicked.connect(self._trace_text)
        pb.addWidget(check, 0, Qt.AlignRight)
        self.paste_box.hide()
        paste_toggle.clicked.connect(lambda: self.paste_box.setVisible(not self.paste_box.isVisible()))
        src.add(self.paste_box)
        self.add(src)

        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.hide()
        self.add(self.busy)
        self.banner = Banner()
        self.add(self.banner)

        # the extracted watermark, big and clear
        self.result_card = Card("Watermark text")
        self.result_text = QLabel()
        self.result_text.setObjectName("WatermarkResult")
        self.result_text.setWordWrap(True)
        self.result_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.result_card.add(self.result_text)
        self.legacy_hint = label("This file was watermarked with an older VeilMark (1.1 or earlier), which had no "
                                 "watermark-text box — this is the text that was typed in its “Recipient” field.",
                                 "Hint")
        self.legacy_hint.hide()
        self.result_card.add(self.legacy_hint)
        copy_row = QHBoxLayout()
        copy = QPushButton("Copy text")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.last.message if self.last else ""))
        copy_row.addWidget(copy)
        copy_row.addStretch()
        self.result_card.add(copy_row)
        self.detail_grid = QGridLayout()
        self.detail_grid.setHorizontalSpacing(24)
        self.result_card.add(self.detail_grid)
        self.result_card.hide()
        self.add(self.result_card)

        self.chain_card = Card("Watermark history",
                               subtitle="Every time this document was watermarked, oldest first. The last row is "
                                        "the copy you opened.")
        self.chain = QTableWidget(0, 4)
        self.chain.setHorizontalHeaderLabels(["#", "Watermark text", "Copy for", "Date"])
        self.chain.verticalHeader().hide()
        self.chain.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.chain.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.chain.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.chain_card.add(self.chain)
        self.chain_card.hide()
        self.add(self.chain_card)

        self.layers_card = Card("Technical details")
        self.layers_toggle = QPushButton("Show where the watermark was found ▾")
        self.layers_toggle.setObjectName("Link")
        self.layers_card.header.addWidget(self.layers_toggle)
        self.layers_body = QWidget()
        body = QVBoxLayout(self.layers_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(label("The watermark is hidden in several places at once. Some can be lost when a file "
                             "is cleaned or converted — one is enough to read it.", "Muted"))
        self.layers_lay = QVBoxLayout()
        body.addLayout(self.layers_lay)
        export = QPushButton("Save report…")
        export.clicked.connect(self._export)
        body.addWidget(export, 0, Qt.AlignLeft)
        self.layers_body.hide()
        self.layers_card.add(self.layers_body)
        self.layers_toggle.clicked.connect(self._toggle_layers)
        self.layers_card.hide()
        self.add(self.layers_card)
        self.finish()

    def _toggle_layers(self):
        on = not self.layers_body.isVisible()
        self.layers_body.setVisible(on)
        self.layers_toggle.setText("Hide details ▴" if on else "Show where the watermark was found ▾")

    def _start(self):
        self.busy.show()
        for w in (self.banner, self.result_card, self.chain_card, self.layers_card):
            w.hide()

    def _trace_file(self, path: Path):
        self._start()
        settings = self.settings
        run_in_background(lambda _p: trace_file(path, settings=settings, ledger=Ledger(self.ledger.path)),
                          self._show, self._failed)

    def _trace_text(self):
        text = self.paste.toPlainText()
        if not text.strip():
            return
        self._start()
        settings = self.settings
        run_in_background(lambda _p: trace_pasted_text(text, settings=settings, ledger=Ledger(self.ledger.path)),
                          self._show, self._failed)

    def _failed(self, msg):
        self.busy.hide()
        self.banner.show_message("bad", "Could not read this file", msg)

    @staticmethod
    def _clear(layout):
        while layout.count():
            w = layout.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _show(self, rep: TraceReport):
        self.busy.hide()
        self.last = rep
        self._clear(self.detail_grid)
        self._clear(self.layers_lay)
        if rep.verdict == "authentic":
            self.banner.show_message("good", "Watermark found", f"File: {rep.file}")
            self.result_text.setText(html.escape(rep.message) if rep.message else
                                     "<span style='color:#6B7086'>(this copy was watermarked without text — "
                                     "see the details below)</span>")
            self.legacy_hint.setVisible(rep.legacy_text)
            src_ = rep.likely_source
            rows = [("Copy for", (src_.recipient if src_ and src_.recipient and not rep.legacy_text else "—")),
                    ("Embedded on", _fmt_time(src_.timestamp) if src_ else "—"),
                    ("Owner", " · ".join(x for x in (rep.owner, rep.organization) if x) or "—"),
                    ("Document", rep.title or "—")]
            for i, (k, v) in enumerate(rows):
                self.detail_grid.addWidget(label(k, "Muted"), i // 2, (i % 2) * 2)
                self.detail_grid.addWidget(label(f"<b>{html.escape(v)}</b>"), i // 2, (i % 2) * 2 + 1)
            self.result_card.show()
            if len(rep.chain) > 1:
                self.chain.setRowCount(len(rep.chain))
                for r, c in enumerate(rep.chain):
                    last = c is rep.likely_source
                    who = c.recipient or "—"
                    if c.source == "ledger":
                        who += "  (from history)"
                    text = c.message or (c.recipient if rep.legacy_text else "") or "—"
                    vals = [str(c.step), text, who, _fmt_time(c.timestamp)]
                    for col, v in enumerate(vals):
                        item = QTableWidgetItem(v)
                        if last:
                            f = item.font()
                            f.setBold(True)
                            item.setFont(f)
                        self.chain.setItem(r, col, item)
                self.chain.setFixedHeight(48 + 34 * len(rep.chain))
                self.chain_card.show()
        elif rep.verdict == "foreign":
            self.banner.show_message("warn", "Watermark from another team key", rep.headline +
                                     " Import that team's key in Settings to read it.")
        elif rep.verdict == "none":
            self.banner.show_message("bad", "No watermark found",
                                     f"{rep.file} doesn't contain a VeilMark watermark, or it was destroyed "
                                     "(for example by printing, screenshots or JPEG conversion).")
        else:
            self.banner.show_message("bad", "Could not check this file", rep.headline)

        if rep.layer_status and rep.verdict != "error":
            found = sum(1 for _n, ok, _d in rep.layer_status if ok)
            self.layers_toggle.setText(f"Found in {found} of {len(rep.layer_status)} hiding places ▾"
                                       if not self.layers_body.isVisible() else "Hide details ▴")
            for name, ok, _detail in rep.layer_status:
                colour = style.GOOD if ok else "#A3A7BA"
                friendly = PLAIN_LAYER_NAMES.get(name, name)
                txt = (f"<span style='color:{colour};font-weight:800'>{'✔' if ok else '—'}</span>&nbsp;&nbsp;"
                       f"<b>{html.escape(friendly)}</b>&nbsp;&nbsp;<span style='color:{style.MUTED}'>"
                       f"{'found' if ok else 'not found'}</span>")
                self.layers_lay.addWidget(label(txt))
            self.layers_card.show()
        self.scroll_to(self.banner)

    def _export(self):
        rep = self.last
        if not rep:
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Save report", f"Watermark report - {rep.file}.html",
                                              "Web page (*.html)")
        if not dest:
            return
        rows = "".join(f"<tr><td>{c.step}</td><td>{html.escape(c.message)}</td><td>{html.escape(c.recipient)}</td>"
                       f"<td>{_fmt_time(c.timestamp)}</td><td>{c.hop_id}</td></tr>" for c in rep.chain)
        layers = "".join(f"<li>{'✔' if ok else '✖'} {html.escape(n)} — {html.escape(d)}</li>"
                         for n, ok, d in rep.layer_status)
        Path(dest).write_text(f"""<!doctype html><meta charset="utf-8"><title>VeilMark watermark report</title>
<style>body{{font-family:-apple-system,Segoe UI,Helvetica Neue,Arial;margin:40px;color:#1f2233}}td,th{{border:1px solid #ddd;padding:6px 10px}}
table{{border-collapse:collapse}}</style>
<h1>VeilMark watermark report</h1><p>Generated {dt.datetime.now():%d %b %Y %H:%M} with VeilMark {__version__}</p>
<p>File: {html.escape(rep.file)}</p><h2>Watermark: {html.escape(rep.message or '(none)')}</h2>
<p>Owner: {html.escape(rep.owner)} {html.escape(rep.organization)}<br>Document: {html.escape(rep.title)}<br>
Document ID: {rep.doc_id}<br>First watermarked: {_fmt_time(rep.created)}</p>
<h3>History</h3><table><tr><th>#</th><th>Watermark text</th><th>Copy for</th><th>Date</th><th>Copy ID</th></tr>
{rows}</table><h3>Where it was found</h3><ul>{layers}</ul>""", encoding="utf-8")
        reveal_in_explorer(Path(dest))


# =========================================================================== #
# Encrypt / Decrypt (two separate pages)
# =========================================================================== #
def password_strength(pw: str) -> tuple[int, str]:
    score = 0
    if len(pw) >= 8:
        score += 1
    if len(pw) >= 12:
        score += 1
    if len(pw) >= 16:
        score += 1
    classes = sum(any(f(c) for c in pw) for f in (str.islower, str.isupper, str.isdigit,
                                                     lambda c: not c.isalnum()))
    score += max(0, classes - 1)
    score = min(score, 5)
    return score, ["Too short", "Weak", "Fair", "Good", "Strong", "Excellent"][score]


class _CryptoPage(Page):
    ENCRYPT = True

    def __init__(self, settings: Settings):
        enc = self.ENCRYPT
        super().__init__("Encrypt files" if enc else "Decrypt files",
                         "Lock files with a password using the hyperchaotic thesis cipher. Only someone with the "
                         "password can open them." if enc else
                         "Unlock .vmk files with the password that was used to encrypt them.")
        self.settings = settings

        top = Card("Choose the files to encrypt" if enc else "Choose the .vmk files to decrypt", "1")
        self.drop = DropZone("Drop files here" if enc else "Drop encrypted .vmk files here",
                             "or click to browse  •  any file type" if enc else "or click to browse",
                             "All files (*.*)" if enc else "Encrypted files (*.vmk);;All files (*.*)",
                             icon="lock" if enc else "unlock")
        self.drop.filesDropped.connect(self._add)
        top.add(self.drop)
        self.files = FileList()
        self.files.changed.connect(self._update)
        top.add(self.files)
        self.add(top)

        pw = Card("Choose a password" if enc else "Enter the password", "2")
        grid = QGridLayout()
        self.pw1 = QLineEdit()
        self.pw1.setEchoMode(QLineEdit.Password)
        self.pw1.setPlaceholderText("Choose a strong password" if enc else "Password used to encrypt")
        grid.addWidget(QLabel("Password"), 0, 0)
        grid.addWidget(self.pw1, 0, 1)
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.Password)
        self.pw2.setPlaceholderText("Type it again")
        self.show_pw = QCheckBox("Show password")
        self.show_pw.toggled.connect(lambda on: [w.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
                                                 for w in (self.pw1, self.pw2)])
        self.meter = QProgressBar()
        self.meter.setRange(0, 5)
        self.meter.setFixedWidth(160)
        self.meter_label = label("", "Hint")
        meter_row = QHBoxLayout()
        if enc:
            grid.addWidget(QLabel("Confirm"), 1, 0)
            grid.addWidget(self.pw2, 1, 1)
            meter_row.addWidget(self.meter)
            meter_row.addWidget(self.meter_label)
        else:
            self.pw2.hide()
            self.meter.hide()
        meter_row.addStretch()
        meter_row.addWidget(self.show_pw)
        grid.addLayout(meter_row, 2, 1)
        pw.add(grid)
        self.armour = QCheckBox("Add AES-256-GCM armour (recommended)")
        self.armour.setChecked(settings.aes_armour)
        self.armour.setToolTip("After the chaotic rounds, the result is also sealed with AES-256-GCM: modern, "
                               "proven security and tamper detection.")
        self.armour.toggled.connect(self._armour)
        if enc:
            pw.add(self.armour)
            pw.add(label("Pipeline: 4-D hyperchaotic Chen keystream → S-box 1 → Mersenne Twister → S-box 2 → 5-D "
                         "hyperchaotic keystream → S-box 3 → bit-level state machine → AES-256-GCM. "
                         "Encrypted copies are saved as “name.ext.vmk”. There is no way to recover a forgotten "
                         "password.", "Hint"))
        else:
            self.armour.hide()
            pw.add(label("The original file name is restored automatically.", "Hint"))
        self.add(pw)
        for w in (self.pw1, self.pw2):
            w.textChanged.connect(self._update)
            w.returnPressed.connect(lambda: self.go.isEnabled() and self._run())

        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.hide()
        self.status = label("", "Hint")
        col = QVBoxLayout()
        col.addWidget(self.progress)
        col.addWidget(self.status)
        row.addLayout(col, 1)
        self.go = QPushButton("Encrypt" if enc else "Decrypt")
        self.go.setObjectName("Primary")
        self.go.setCursor(Qt.PointingHandCursor)
        self.go.clicked.connect(self._run)
        row.addWidget(self.go)
        self.add(row)
        self.banner = Banner()
        self.add(self.banner)
        self.results = QWidget()
        self.results_lay = QVBoxLayout(self.results)
        self.results_lay.setContentsMargins(0, 0, 0, 0)
        self.add(self.results)
        self.finish()
        self._update()

    def _armour(self, on):
        self.settings.aes_armour = on
        self.settings.save()

    def _add(self, paths):
        if self.ENCRYPT:
            locked = [p for p in paths if is_encrypted_file(p)]
            self.files.add([p for p in paths if p not in locked])
            if locked:
                self.banner.show_message("info", f"{len(locked)} file(s) are already encrypted",
                                         "Use the Decrypt page to unlock .vmk files.")
        else:
            ok = [p for p in paths if is_encrypted_file(p)]
            self.files.add(ok)
            if len(ok) < len(paths):
                self.banner.show_message("warn", f"{len(paths) - len(ok)} file(s) skipped",
                                         "Only files encrypted by VeilMark (.vmk) can be decrypted here.")

    def _update(self):
        enc = self.ENCRYPT
        score, text = password_strength(self.pw1.text())
        self.meter.setValue(score)
        self.meter_label.setText(text if self.pw1.text() else "")
        n = len(self.files.paths())
        ok = n > 0 and bool(self.pw1.text())
        if enc:
            ok = ok and self.pw1.text() == self.pw2.text() and len(self.pw1.text()) >= 6
            if self.pw2.text() and self.pw1.text() != self.pw2.text():
                self.meter_label.setText("Passwords don't match")
            elif self.pw1.text() and len(self.pw1.text()) < 6:
                self.meter_label.setText("Use at least 6 characters")
        verb = "Encrypt" if enc else "Decrypt"
        self.go.setText(f"{verb} {n} file{'s' if n != 1 else ''}" if n else verb)
        self.go.setEnabled(ok)

    def _run(self):
        encrypt = self.ENCRYPT
        paths, pw, armour = self.files.paths(), self.pw1.text(), self.armour.isChecked()
        self.go.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.banner.hide()
        total = len(paths)

        def job(progress):
            out = []
            for i, p in enumerate(paths):
                def sub(msg, frac, i=i, name=p.name):
                    progress(f"{name}: {msg}", (i + frac) / total)
                try:
                    if encrypt:
                        out.append((p, encrypt_file(p, pw, aes_armour=armour, progress=sub), None))
                    else:
                        out.append((p, decrypt_file(p, pw, progress=sub), None))
                except Exception as exc:  # noqa: BLE001 - DecryptionError has a friendly message
                    out.append((p, None, str(exc)))
            return out

        def prog(msg, frac):
            self.progress.setValue(int(frac * 1000))
            self.status.setText(msg)

        run_in_background(job, self._done, self._failed, prog)

    def _failed(self, msg):
        self.progress.hide()
        self.status.setText("")
        self._update()
        self.banner.show_message("bad", "Something went wrong", msg)

    def _done(self, results):
        self.progress.hide()
        self.status.setText("")
        ok = [r for r in results if r[1]]
        bad = [r for r in results if not r[1]]
        verb = "encrypted" if self.ENCRYPT else "decrypted"
        if ok and not bad:
            self.banner.show_message("good", f"{len(ok)} file{'s' if len(ok) != 1 else ''} {verb} and verified",
                                     "Each file was checked after saving." +
                                     (" Keep the password safe — it can't be recovered." if self.ENCRYPT else ""))
        elif ok:
            self.banner.show_message("warn", f"{len(ok)} {verb}, {len(bad)} failed", "See the details below.")
        else:
            self.banner.show_message("bad", f"Nothing was {verb}", "See the details below.")
        while self.results_lay.count():
            w = self.results_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        for src, out, err in results:
            card = QFrame()
            card.setObjectName("Card")
            row = QHBoxLayout(card)
            row.setContentsMargins(16, 12, 16, 12)
            mark = QLabel()
            mark.setPixmap(icons.pixmap("check" if out else "alert", style.GOOD if out else style.BAD, 26, 2.0))
            row.addWidget(mark)
            if out:
                lab = QLabel(f"<b>{html.escape(out.name)}</b><br><span style='color:{style.MUTED}'>"
                             f"from {html.escape(src.name)}</span>")
                lab.setWordWrap(True)
                row.addWidget(lab, 1)
                b1 = QPushButton(REVEAL_LABEL)
                b1.clicked.connect(lambda _=False, p=out: reveal_in_explorer(p))
                row.addWidget(b1)
                if not self.ENCRYPT:
                    b2 = QPushButton("Open")
                    b2.clicked.connect(lambda _=False, p=out: open_path(p))
                    row.addWidget(b2)
            else:
                lab = QLabel(f"<b>{html.escape(src.name)}</b><br><span style='color:{style.BAD}'>"
                             f"{html.escape(err)}</span>")
                lab.setWordWrap(True)
                row.addWidget(lab, 1)
            self.results_lay.addWidget(card)
        if ok:
            self.files.clear()
            self.pw1.clear()
            self.pw2.clear()
        self._update()
        self.scroll_to(self.banner)


class EncryptPage(_CryptoPage):
    ENCRYPT = True


class DecryptPage(_CryptoPage):
    ENCRYPT = False


# =========================================================================== #
# History
# =========================================================================== #
class HistoryPage(Page):
    def __init__(self, ledger: Ledger):
        super().__init__("History", "Every watermark you've embedded on this computer.")
        self.ledger = ledger
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by watermark text, person, file or ID…")
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search, 1)
        export = QPushButton("Export to Excel (CSV)…")
        export.clicked.connect(self._export)
        row.addWidget(export)
        self.add(row)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Date", "Watermark text", "Copy for", "Original file", "Copy ID"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setMinimumHeight(420)
        self.table.doubleClicked.connect(self._open_row)
        self.add(self.table, 1)
        self.empty = label("Nothing here yet. Watermarked files will appear here.", "Muted")
        self.add(self.empty)
        self.refresh()

    def refresh(self):
        issues = self.ledger.search(self.search.text().strip())
        self.issues = issues
        self.table.setRowCount(len(issues))
        for r, i in enumerate(issues):
            vals = [_fmt_time(i.timestamp), i.message or "—", i.recipient or "—", Path(i.source_file).name,
                    i.hop_id]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setToolTip(i.output_file if c == 3 else v)
                self.table.setItem(r, c, item)
        self.empty.setVisible(not issues)

    def _open_row(self, index):
        issue = self.issues[index.row()]
        p = Path(issue.output_file)
        if p.exists():
            reveal_in_explorer(p)

    def _export(self):
        dest, _ = QFileDialog.getSaveFileName(self, "Export history", "VeilMark history.csv", "CSV (*.csv)")
        if dest:
            n = self.ledger.export_csv(Path(dest))
            QMessageBox.information(self, "Exported", f"{n} rows saved to\n{dest}")


# =========================================================================== #
# Settings
# =========================================================================== #
class SettingsPage(Page):
    changed = Signal()

    def __init__(self, settings: Settings, updates=None):
        super().__init__("Settings", "Your details and app updates.")
        self.settings = settings

        me = Card("About you", subtitle="Recorded as the owner of every watermark you embed.")
        grid = QGridLayout()
        self.name = QLineEdit(settings.owner_name)
        self.name.setPlaceholderText("Your full name")
        self.org = QLineEdit(settings.organization)
        self.org.setPlaceholderText("Company or organisation (optional)")
        grid.addWidget(QLabel("Name"), 0, 0)
        grid.addWidget(self.name, 0, 1)
        grid.addWidget(QLabel("Organisation"), 1, 0)
        grid.addWidget(self.org, 1, 1)
        me.add(grid)
        save = QPushButton("Save")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        me.add(save)
        self.saved = label("", "Hint")
        me.add(self.saved)
        self.add(me)

        if updates is not None:
            from ..updater import RELEASES_PAGE

            up = Card("Updates", subtitle=f"You have version {__version__}. New versions are downloaded in the "
                                          "background and installed with one click.")
            self.auto_update = QCheckBox("Check for updates automatically and download them in the background")
            self.auto_update.setChecked(settings.check_updates)
            self.auto_update.toggled.connect(self._auto_update)
            up.add(self.auto_update)
            row = QHBoxLayout()
            self.update_btn = QPushButton("Check for updates now")
            self.update_btn.clicked.connect(lambda: updates.primary_action(self))
            row.addWidget(self.update_btn)
            self.update_status = label("", "Muted")
            row.addWidget(self.update_status, 1)
            up.add(row)
            link = label(f'Download page to share with others: <a href="{RELEASES_PAGE}">{RELEASES_PAGE}</a>',
                         "Hint")
            link.setTextInteractionFlags(Qt.TextBrowserInteraction)
            link.setOpenExternalLinks(True)
            up.add(link)
            self.add(up)
            updates.changed.connect(self._update_state)
            self._update_state(updates.state, updates.text)

        about = Card("About VeilMark")
        about.add(label(f"Version {__version__}. Based on the master's thesis work on chaotic image encryption "
                        "and LSB watermarking (Mathematica), re-engineered for Office documents.\n"
                        f"Your settings and history are stored in: {Settings.path().parent}", "Muted"))
        self.add(about)
        self.finish()

    def _auto_update(self, on):
        self.settings.check_updates = on
        self.settings.save()

    def _update_state(self, state, text):
        self.update_status.setText(text)
        self.update_btn.setEnabled(state not in ("checking", "downloading"))
        self.update_btn.setText({"ready": "Install update && restart", "available": "Open download page",
                                 "error": "Try again"}.get(state, "Check for updates now"))

    def _save(self):
        self.settings.owner_name = self.name.text().strip()
        self.settings.organization = self.org.text().strip()
        self.settings.save()
        self.saved.setText("Saved ✔")
        self.changed.emit()



__all__: List[str] = ["HomePage", "EmbedPage", "ExtractPage", "EncryptPage", "DecryptPage", "HistoryPage",
                      "SettingsPage"]
