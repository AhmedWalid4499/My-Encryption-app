"""The application pages."""

from __future__ import annotations

import datetime as dt
import html
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QCompleter, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import __version__
from ..crypto import DecryptionError, decrypt_file, encrypt_file, is_encrypted_file
from ..registry import Ledger
from ..service import TraceReport, protect_file, trace_file, trace_pasted_text
from ..settings import Settings, format_key, parse_key
from ..watermark.engine import SUPPORTED_PROTECT
from . import style
from .widgets import Banner, Card, DropZone, FileList, label, open_path, reveal_in_explorer, run_in_background

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
        self.setMinimumHeight(170)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        for t, n in ((icon, "TileIcon"), (title, "TileTitle"), (text, "TileText")):
            lab = QLabel(t)
            lab.setObjectName(n)
            lab.setWordWrap(True)
            lab.setAttribute(Qt.WA_TransparentForMouseEvents)
            lay.addWidget(lab)
        lay.addStretch()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class HomePage(Page):
    navigate = Signal(int)

    def __init__(self, settings: Settings):
        greeting = f"Welcome back, {settings.owner_name.split()[0]}" if settings.owner_name else "Welcome to VeilMark"
        super().__init__(greeting, "Protect your documents with invisible, traceable watermarks — "
                                   "and lock files with chaotic encryption.")
        self.setup_banner = Banner()
        self.add(self.setup_banner)
        if not settings.owner_name:
            self.setup_banner.show_message(
                "info", "One quick thing first",
                "Add your name in Settings so every protected document records you as its owner.")
        grid = QGridLayout()
        grid.setSpacing(16)
        tiles = [
            ("🛡️", "Protect a document", "Hide an invisible watermark in Word, PowerPoint or Excel files before "
                                        "you share them. Each recipient gets a uniquely marked copy.", 1),
            ("🔍", "Trace a leak", "Found your file somewhere it shouldn't be? Drop it in to see who it was "
                                  "issued to — even after it was forwarded several times.", 2),
            ("🔐", "Encrypt or decrypt", "Lock any file with the hyperchaotic cipher (Chen 4-D, 5-D system, "
                                        "S-boxes) plus AES-256 armour.", 3),
            ("🕘", "Sharing history", "See every protected copy you've handed out, search it and export it "
                                     "to Excel.", 4),
        ]
        for i, (icon, title, text, page) in enumerate(tiles):
            tile = HomeTile(icon, title, text)
            tile.clicked.connect(lambda p=page: self.navigate.emit(p))
            grid.addWidget(tile, i // 2, i % 2)
        self.add(grid)

        how = Card("How the protection works")
        how.add(label(
            "VeilMark hides the same mark in up to five places at once, so it survives being opened, edited, "
            "re-saved, forwarded and even partly cleaned:\n"
            "  •  Encrypted document properties and a hidden custom-XML part (full owner + recipient history)\n"
            "  •  Invisible zero-width characters inside the text — survive copy & paste into other files\n"
            "  •  Pixel-level (LSB) marks in pictures — the method from the original thesis\n"
            "  •  A ‘very hidden’ data sheet in Excel workbooks\n"
            "Each time a protected file is re-shared through VeilMark, a new link is added to its chain of "
            "custody, so a leaked copy points at the last person who received it.", "Muted"))
        self.add(how)
        self.finish()


# =========================================================================== #
# Protect
# =========================================================================== #
LAYER_OPTIONS = [
    ("properties", "Encrypted document properties", "Stores the full, encrypted owner & recipient history."),
    ("custom_xml", "Hidden custom XML part", "A second encrypted copy in a hidden data part of the file."),
    ("invisible_text", "Invisible text marks", "Zero-width characters in the text. Survive copy & paste, "
                                               "‘Inspect Document’ and copying slides into other decks."),
    ("hidden_sheet", "Hidden data sheet (Excel)", "A ‘very hidden’ worksheet that can't be unhidden from the "
                                                  "normal Excel menu."),
    ("images", "Picture pixels (LSB)", "Hides the mark in the least significant bits of PNG/BMP pictures, "
                                       "like the original thesis. Lost if pictures are compressed to JPEG."),
    ("excel_cell_text", "Also mark Excel cell text (advanced)", "Adds invisible marks to long text cells. "
                                                                "Can affect formulas that compare text - "
                                                                "off by default."),
]


class ProtectPage(Page):
    def __init__(self, settings: Settings, ledger: Ledger):
        super().__init__("Protect documents",
                         "Create a uniquely watermarked copy for each person you share with.")
        self.settings, self.ledger = settings, ledger

        files = Card("Choose the documents", "1")
        self.drop = DropZone("Drag & drop files or folders here", "or click to browse  •  Word, PowerPoint, Excel, "
                             "PNG/BMP pictures and text files", OFFICE_FILTER, icon="📂")
        self.drop.filesDropped.connect(self._add_files)
        files.add(self.drop)
        self.files = FileList()
        self.files.changed.connect(self._update_button)
        files.add(self.files)
        self.add(files)

        who = Card("Who is this copy for?", "2",
                   "Their name is sealed inside the file. If the copy leaks, Trace will show it was theirs.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        self.recipient = QLineEdit()
        self.recipient.setPlaceholderText("e.g.  Sara Ahmed <sara@company.com>")
        self.recipient.textChanged.connect(self._update_button)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Optional  –  e.g. ‘Q3 board pack, sent by email’")
        grid.addWidget(QLabel("Recipient"), 0, 0)
        grid.addWidget(self.recipient, 0, 1)
        grid.addWidget(QLabel("Note"), 1, 0)
        grid.addWidget(self.note, 1, 1)
        who.add(grid)
        self.add(who)

        opts = Card("Protection options", "3")
        toggle = QPushButton("Show protection layers ▾")
        toggle.setObjectName("Link")
        opts.header.addWidget(toggle)
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
                                        toggle.setText("Hide protection layers ▴" if self.layer_box.isVisible()
                                                       else "Show protection layers ▾")))
        opts.add(label("All recommended layers are on. Protected copies are saved next to the originals as "
                       "“name - for Recipient”.", "Muted"))
        out_row = QHBoxLayout()
        self.out_label = label("", "Hint")
        out_btn = QPushButton("Change save folder…")
        out_btn.clicked.connect(self._choose_out)
        out_row.addWidget(self.out_label, 1)
        out_row.addWidget(out_btn)
        opts.add(out_row)
        opts.add(self.layer_box)
        self.add(opts)
        self._show_out()

        run_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.hide()
        run_row.addWidget(self.progress, 1)
        self.go = QPushButton("Protect files")
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
        self._update_button()

    # -- helpers ------------------------------------------------------------ #
    def refresh_completer(self):
        names = sorted({i.recipient for i in self.ledger.search("")})
        comp = QCompleter(names)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.recipient.setCompleter(comp)

    def _set_layer(self, key, on):
        self.settings.layers[key] = on
        self.settings.save()

    def _show_out(self):
        folder = self.settings.output_folder
        self.out_label.setText(f"Save to: {folder}" if folder else "Save to: same folder as each original")

    def _choose_out(self):
        folder = QFileDialog.getExistingDirectory(self, "Where should protected copies be saved?")
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
                                     "files can be protected. Old .doc/.ppt/.xls files must be re-saved in the "
                                     "new format first.")

    def _update_button(self):
        n = len(self.files.paths())
        self.go.setEnabled(n > 0 and bool(self.recipient.text().strip()))
        self.go.setText(f"Protect {n} file{'s' if n != 1 else ''}" if n else "Protect files")

    def _clear_results(self):
        while self.results_lay.count():
            w = self.results_lay.takeAt(0).widget()
            if w:
                w.deleteLater()

    # -- run ---------------------------------------------------------------- #
    def _run(self):
        paths = self.files.paths()
        recipient, note = self.recipient.text().strip(), self.note.text().strip()
        if not self.settings.owner_name:
            QMessageBox.information(self, "Add your name",
                                    "Tip: add your name in Settings so documents record you as the owner.\n"
                                    "This time they will be marked as ‘Unknown owner’.")
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
                    out.append((p, protect_file(p, recipient, note, settings=settings, ledger=ledger), None))
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
        recipient = self.recipient.text().strip()
        if ok and not bad:
            self.banner.show_message("good", f"{len(ok)} protected cop{'ies' if len(ok) != 1 else 'y'} ready for "
                                             f"{recipient}",
                                     "Send these files instead of the originals. Each one is logged in your "
                                     "Sharing history.")
        elif ok:
            self.banner.show_message("warn", f"{len(ok)} protected, {len(bad)} failed",
                                     "See the details below.")
        else:
            self.banner.show_message("bad", "No files could be protected", "See the details below.")
        for src, res, err in results:
            card = QFrame()
            card.setObjectName("Card")
            row = QHBoxLayout(card)
            row.setContentsMargins(16, 12, 16, 12)
            if res:
                kind = "re-shared copy — added to its chain of custody" if res.reshared else "new protected document"
                layers = ", ".join(res.report.applied()) or "none"
                text = (f"<b>{html.escape(res.output.name)}</b><br><span style='color:{style.MUTED}'>{kind}"
                        f"<br>Layers: {html.escape(layers)}</span>")
                lab = QLabel(text)
                lab.setWordWrap(True)
                row.addWidget(QLabel("✅"))
                row.addWidget(lab, 1)
                b1 = QPushButton("Show in folder")
                b1.clicked.connect(lambda _=False, p=res.output: reveal_in_explorer(p))
                b2 = QPushButton("Open")
                b2.clicked.connect(lambda _=False, p=res.output: open_path(p))
                row.addWidget(b1)
                row.addWidget(b2)
            else:
                lab = QLabel(f"<b>{html.escape(src.name)}</b><br><span style='color:{style.BAD}'>"
                             f"{html.escape(err)}</span>")
                lab.setWordWrap(True)
                row.addWidget(QLabel("⚠️"))
                row.addWidget(lab, 1)
            self.results_lay.addWidget(card)
        if ok:
            self.files.clear()
        self.refresh_completer()
        self.scroll_to(self.banner)


# =========================================================================== #
# Trace
# =========================================================================== #
class TracePage(Page):
    def __init__(self, settings: Settings, ledger: Ledger):
        super().__init__("Trace a leak",
                         "Check any file (or pasted text) for your watermark and see who it was issued to.")
        self.settings, self.ledger = settings, ledger
        self.last: Optional[TraceReport] = None

        src = Card("What do you want to check?")
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.mode_file = QPushButton("A file")
        self.mode_text = QPushButton("Pasted text")
        group = QButtonGroup(self)
        for b in (self.mode_file, self.mode_text):
            b.setObjectName("Segment")
            b.setCheckable(True)
            group.addButton(b)
            seg.addWidget(b)
        seg.addStretch()
        self.mode_file.setChecked(True)
        src.add(seg)
        self.drop = DropZone("Drop the suspicious file here", "or click to browse  •  any Office document, "
                             "picture or text file", "All files (*.*)", multiple=False, icon="🔍")
        self.drop.filesDropped.connect(lambda ps: self._trace_file(ps[0]))
        src.add(self.drop)
        self.paste_box = QWidget()
        pb = QVBoxLayout(self.paste_box)
        pb.setContentsMargins(0, 0, 0, 0)
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText("Paste text copied from an email, website, chat or document. Invisible "
                                      "marks survive copy & paste.")
        self.paste.setMinimumHeight(130)
        pb.addWidget(self.paste)
        check = QPushButton("Check text")
        check.setObjectName("Primary")
        check.clicked.connect(self._trace_text)
        pb.addWidget(check, 0, Qt.AlignRight)
        self.paste_box.hide()
        src.add(self.paste_box)
        self.mode_file.toggled.connect(lambda on: (self.drop.setVisible(on), self.paste_box.setVisible(not on)))
        self.add(src)

        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.hide()
        self.add(self.busy)
        self.banner = Banner()
        self.add(self.banner)

        self.details = Card("Document details")
        self.detail_grid = QGridLayout()
        self.detail_grid.setHorizontalSpacing(24)
        self.details.add(self.detail_grid)
        self.details.hide()
        self.add(self.details)

        self.chain_card = Card("Chain of custody",
                               subtitle="Every person this copy was issued to, in order. The last one received "
                                        "this exact copy.")
        self.chain = QTableWidget(0, 5)
        self.chain.setHorizontalHeaderLabels(["#", "Issued to", "Date", "Note", "Copy ID"])
        self.chain.verticalHeader().hide()
        self.chain.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.chain.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.chain.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.chain_card.add(self.chain)
        self.chain_card.hide()
        self.add(self.chain_card)

        self.layers_card = Card("Where the watermark was found",
                                subtitle="Several layers are hidden in each file. Some may be lost when a file "
                                         "is cleaned or converted — one surviving layer is enough.")
        self.layers_lay = QVBoxLayout()
        self.layers_card.add(self.layers_lay)
        export = QPushButton("Save report…")
        export.clicked.connect(self._export)
        self.layers_card.add(export)
        self.layers_card.hide()
        self.add(self.layers_card)
        self.finish()

    def _start(self):
        self.busy.show()
        for w in (self.banner, self.details, self.chain_card, self.layers_card):
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

    def _show(self, rep: TraceReport):
        self.busy.hide()
        self.last = rep
        if rep.verdict == "authentic":
            sub = f"File: {rep.file}"
            if rep.likely_source:
                sub += (f"\nThis copy was issued to {rep.likely_source.recipient} on "
                        f"{_fmt_time(rep.likely_source.timestamp)}. If it leaked, it most likely leaked from them.")
            self.banner.show_message("good", rep.headline, sub)
        elif rep.verdict == "foreign":
            self.banner.show_message("warn", "Watermark from another team key", rep.headline +
                                     " Import that team's key in Settings to read it.")
        elif rep.verdict == "none":
            self.banner.show_message("bad", "No watermark found",
                                     f"{rep.file} doesn't carry a VeilMark watermark, or it was destroyed "
                                     "(for example by printing, screenshots or JPEG conversion).")
        else:
            self.banner.show_message("bad", "Could not check this file", rep.headline)

        while self.detail_grid.count():
            w = self.detail_grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        if rep.verdict == "authentic":
            rows = [("Owner", rep.owner or "—"), ("Organisation", rep.organization or "—"),
                    ("Document", rep.title or "—"), ("Document ID", rep.doc_id or "—"),
                    ("First protected", _fmt_time(rep.created))]
            for i, (k, v) in enumerate(rows):
                self.detail_grid.addWidget(label(k, "Muted"), i // 2, (i % 2) * 2)
                self.detail_grid.addWidget(label(f"<b>{html.escape(v)}</b>"), i // 2, (i % 2) * 2 + 1)
            self.details.show()

            self.chain.setRowCount(len(rep.chain))
            for r, c in enumerate(rep.chain):
                last = c is rep.likely_source
                name = c.recipient + ("   ← this copy" if last else "")
                if c.source == "ledger":
                    name += "  (from history)"
                vals = [str(c.step), name, _fmt_time(c.timestamp), c.note, c.hop_id]
                for col, v in enumerate(vals):
                    item = QTableWidgetItem(v)
                    if last:
                        f = item.font()
                        f.setBold(True)
                        item.setFont(f)
                    self.chain.setItem(r, col, item)
            self.chain.setFixedHeight(48 + 34 * max(1, len(rep.chain)))
            self.chain_card.show()

        while self.layers_lay.count():
            w = self.layers_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        if rep.layer_status:
            for name, ok, detail in rep.layer_status:
                colour = style.GOOD if ok else "#A3A7BA"
                txt = (f"<span style='color:{colour};font-weight:800'>{'✔' if ok else '—'}</span>&nbsp;&nbsp;"
                       f"<b>{html.escape(name)}</b>&nbsp;&nbsp;<span style='color:{style.MUTED}'>"
                       f"{html.escape(detail or ('found' if ok else 'not found'))}</span>")
                self.layers_lay.addWidget(label(txt))
            self.layers_card.show()
        self.scroll_to(self.banner)

    def _export(self):
        rep = self.last
        if not rep:
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Save trace report", f"Trace report - {rep.file}.html",
                                              "Web page (*.html)")
        if not dest:
            return
        rows = "".join(f"<tr><td>{c.step}</td><td>{html.escape(c.recipient)}</td><td>{_fmt_time(c.timestamp)}</td>"
                       f"<td>{html.escape(c.note)}</td><td>{c.hop_id}</td></tr>" for c in rep.chain)
        layers = "".join(f"<li>{'✔' if ok else '✖'} {html.escape(n)} — {html.escape(d)}</li>"
                         for n, ok, d in rep.layer_status)
        Path(dest).write_text(f"""<!doctype html><meta charset="utf-8"><title>VeilMark trace report</title>
<style>body{{font-family:Segoe UI,Arial;margin:40px;color:#1f2233}}td,th{{border:1px solid #ddd;padding:6px 10px}}
table{{border-collapse:collapse}}</style>
<h1>VeilMark trace report</h1><p>Generated {dt.datetime.now():%d %b %Y %H:%M} with VeilMark {__version__}</p>
<h2>{html.escape(rep.headline)}</h2><p>File: {html.escape(rep.file)}</p>
<p>Owner: {html.escape(rep.owner)} {html.escape(rep.organization)}<br>Document: {html.escape(rep.title)}<br>
Document ID: {rep.doc_id}<br>First protected: {_fmt_time(rep.created)}</p>
<h3>Chain of custody</h3><table><tr><th>#</th><th>Issued to</th><th>Date</th><th>Note</th><th>Copy ID</th></tr>
{rows}</table><h3>Layers</h3><ul>{layers}</ul>""", encoding="utf-8")
        reveal_in_explorer(Path(dest))


# =========================================================================== #
# Encrypt / decrypt
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


class EncryptPage(Page):
    def __init__(self, settings: Settings):
        super().__init__("Encrypt & decrypt",
                         "Lock files with the thesis' hyperchaotic cascade cipher. Only someone with the "
                         "password can open them.")
        self.settings = settings

        top = Card("Choose files", "1")
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.enc_btn = QPushButton("🔒  Encrypt")
        self.dec_btn = QPushButton("🔓  Decrypt")
        group = QButtonGroup(self)
        for b in (self.enc_btn, self.dec_btn):
            b.setObjectName("Segment")
            b.setCheckable(True)
            group.addButton(b)
            seg.addWidget(b)
        seg.addStretch()
        self.enc_btn.setChecked(True)
        top.add(seg)
        self.drop = DropZone("Drop files here", "or click to browse  •  any file type", "All files (*.*)",
                             icon="🔐")
        self.drop.filesDropped.connect(self._add)
        top.add(self.drop)
        self.files = FileList()
        self.files.changed.connect(self._update)
        top.add(self.files)
        self.add(top)

        pw = Card("Password", "2")
        grid = QGridLayout()
        self.pw1 = QLineEdit()
        self.pw1.setEchoMode(QLineEdit.Password)
        self.pw1.setPlaceholderText("Choose a strong password")
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
        grid.addWidget(QLabel("Password"), 0, 0)
        grid.addWidget(self.pw1, 0, 1)
        self.pw2_label = QLabel("Confirm")
        grid.addWidget(self.pw2_label, 1, 0)
        grid.addWidget(self.pw2, 1, 1)
        meter_row = QHBoxLayout()
        meter_row.addWidget(self.meter)
        meter_row.addWidget(self.meter_label)
        meter_row.addStretch()
        meter_row.addWidget(self.show_pw)
        grid.addLayout(meter_row, 2, 1)
        pw.add(grid)
        self.armour = QCheckBox("Add AES-256-GCM armour (recommended)")
        self.armour.setChecked(settings.aes_armour)
        self.armour.setToolTip("After the chaotic rounds, the result is also sealed with AES-256-GCM. This adds "
                               "modern, proven security and tamper detection.")
        self.armour.toggled.connect(self._armour)
        pw.add(self.armour)
        pw.add(label("Pipeline: 4-D hyperchaotic Chen keystream → S-box 1 → Mersenne Twister → S-box 2 → 5-D "
                     "hyperchaotic keystream → S-box 3 → bit-level state machine → AES-256-GCM. "
                     "There is no way to recover a forgotten password.", "Hint"))
        self.add(pw)
        for w in (self.pw1, self.pw2):
            w.textChanged.connect(self._update)
        self.enc_btn.toggled.connect(self._mode)

        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.hide()
        self.status = label("", "Hint")
        col = QVBoxLayout()
        col.addWidget(self.progress)
        col.addWidget(self.status)
        row.addLayout(col, 1)
        self.go = QPushButton("Encrypt")
        self.go.setObjectName("Primary")
        self.go.clicked.connect(self._run)
        row.addWidget(self.go)
        self.add(row)
        self.banner = Banner()
        self.add(self.banner)
        self.finish()
        self._mode(True)

    def _armour(self, on):
        self.settings.aes_armour = on
        self.settings.save()

    def _add(self, paths):
        self.files.add(paths)
        enc = [p for p in self.files.paths() if is_encrypted_file(p)]
        if enc and len(enc) == len(self.files.paths()):
            self.dec_btn.setChecked(True)
        elif not enc:
            self.enc_btn.setChecked(True)

    def _mode(self, encrypt: bool):
        for w in (self.pw2, self.pw2_label, self.meter, self.meter_label, self.armour):
            w.setVisible(encrypt)
        self.pw1.setPlaceholderText("Choose a strong password" if encrypt else "Password used to encrypt")
        self._update()

    def _update(self):
        encrypt = self.enc_btn.isChecked()
        score, text = password_strength(self.pw1.text())
        self.meter.setValue(score)
        self.meter_label.setText(text if self.pw1.text() else "")
        n = len(self.files.paths())
        ok = n > 0 and bool(self.pw1.text())
        if encrypt:
            ok = ok and self.pw1.text() == self.pw2.text() and len(self.pw1.text()) >= 6
            if self.pw2.text() and self.pw1.text() != self.pw2.text():
                self.meter_label.setText("Passwords don't match")
        verb = "Encrypt" if encrypt else "Decrypt"
        self.go.setText(f"{verb} {n} file{'s' if n != 1 else ''}" if n else verb)
        self.go.setEnabled(ok)

    def _run(self):
        encrypt = self.enc_btn.isChecked()
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
                except DecryptionError as exc:
                    out.append((p, None, str(exc)))
                except Exception as exc:  # noqa: BLE001
                    out.append((p, None, str(exc)))
            return out

        def prog(msg, frac):
            self.progress.setValue(int(frac * 1000))
            self.status.setText(msg)

        run_in_background(job, lambda r: self._done(r, encrypt), self._failed, prog)

    def _failed(self, msg):
        self.progress.hide()
        self.status.setText("")
        self._update()
        self.banner.show_message("bad", "Something went wrong", msg)

    def _done(self, results, encrypt):
        self.progress.hide()
        self.status.setText("")
        ok = [r for r in results if r[1]]
        bad = [r for r in results if not r[1]]
        lines = [f"✔ {r[1].name}" for r in ok] + [f"✖ {r[0].name}: {r[2]}" for r in bad]
        verb = "encrypted" if encrypt else "decrypted"
        kind = "good" if not bad else ("warn" if ok else "bad")
        title = f"{len(ok)} file(s) {verb}" if ok else f"Nothing was {verb}"
        self.banner.show_message(kind, title, "\n".join(lines[:15]))
        if ok:
            self.files.clear()
            self.pw1.clear()
            self.pw2.clear()
            reveal_in_explorer(ok[0][1])
        self._update()


# =========================================================================== #
# History
# =========================================================================== #
class HistoryPage(Page):
    def __init__(self, ledger: Ledger):
        super().__init__("Sharing history", "Every protected copy you've created on this computer.")
        self.ledger = ledger
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by recipient, file, note or ID…")
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search, 1)
        export = QPushButton("Export to Excel (CSV)…")
        export.clicked.connect(self._export)
        row.addWidget(export)
        self.add(row)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Date", "Recipient", "Original file", "Note", "Shared from",
                                              "Copy ID"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setMinimumHeight(420)
        self.table.doubleClicked.connect(self._open_row)
        self.add(self.table, 1)
        self.empty = label("Nothing here yet. Protected copies will appear here.", "Muted")
        self.add(self.empty)
        self.refresh()

    def refresh(self):
        issues = self.ledger.search(self.search.text().strip())
        by_hop = {i.hop_id: i for i in self.ledger.search("")}
        self.issues = issues
        self.table.setRowCount(len(issues))
        for r, i in enumerate(issues):
            parent = by_hop.get(i.parent_hop)
            vals = [_fmt_time(i.timestamp), i.recipient, Path(i.source_file).name, i.note,
                    parent.recipient if parent else ("—" if not i.parent_hop else "another computer"), i.hop_id]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setToolTip(i.output_file if c == 2 else v)
                self.table.setItem(r, c, item)
        self.empty.setVisible(not issues)

    def _open_row(self, index):
        issue = self.issues[index.row()]
        p = Path(issue.output_file)
        if p.exists():
            reveal_in_explorer(p)

    def _export(self):
        dest, _ = QFileDialog.getSaveFileName(self, "Export history", "VeilMark sharing history.csv", "CSV (*.csv)")
        if dest:
            n = self.ledger.export_csv(Path(dest))
            QMessageBox.information(self, "Exported", f"{n} rows saved to\n{dest}")


# =========================================================================== #
# Settings
# =========================================================================== #
class SettingsPage(Page):
    changed = Signal()

    def __init__(self, settings: Settings):
        super().__init__("Settings", "Your details and your team's watermark key.")
        self.settings = settings

        me = Card("About you", subtitle="Recorded as the owner of every document you protect.")
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

        key = Card("Team watermark key",
                   subtitle="Watermarks are sealed with this key. Give the same key to colleagues so their "
                            "VeilMark can read and trace your documents (and vice versa). Keep it private.")
        self.key_label = QLabel()
        self.key_label.setObjectName("KeyLabel")
        self.key_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        key.add(self.key_label)
        row = QHBoxLayout()
        self.reveal = QPushButton("Show key")
        self.reveal.setCheckable(True)
        self.reveal.toggled.connect(self._show_key)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(format_key(self.settings.team_key)),
                                      self.saved.setText("Team key copied to the clipboard.")))
        imp = QPushButton("Use a colleague's key…")
        imp.clicked.connect(self._import)
        new = QPushButton("Generate new key")
        new.setObjectName("Danger")
        new.clicked.connect(self._regen)
        for b in (self.reveal, copy, imp):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(new)
        key.add(row)
        self.add(key)
        self._show_key(False)

        about = Card("About VeilMark")
        about.add(label(f"Version {__version__}. Based on the master's thesis work on chaotic image encryption "
                        "and LSB watermarking (Mathematica), re-engineered for Office documents.\n"
                        f"Your settings and history are stored in: {Settings.path().parent}", "Muted"))
        self.add(about)
        self.finish()

    def _show_key(self, on):
        k = format_key(self.settings.team_key)
        self.key_label.setText(k if on else "•" * 6 + "-" + "•" * 6 + "-  … hidden …")
        self.reveal.setText("Hide key" if on else "Show key")

    def _save(self):
        self.settings.owner_name = self.name.text().strip()
        self.settings.organization = self.org.text().strip()
        self.settings.save()
        self.saved.setText("Saved ✔")
        self.changed.emit()

    def _import(self):
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, "Use a colleague's key",
                                        "Paste the team key you were given.\n\nDocuments you protected with your "
                                        "current key can only be traced with that key, so copy it somewhere "
                                        "safe first.")
        if not ok or not text.strip():
            return
        try:
            self.settings.team_key = parse_key(text)
        except Exception:  # noqa: BLE001
            QMessageBox.warning(self, "Invalid key", "That doesn't look like a VeilMark team key.")
            return
        self.settings.save()
        self._show_key(self.reveal.isChecked())
        self.saved.setText("Team key updated ✔")

    def _regen(self):
        from ..settings import _new_key

        if QMessageBox.question(self, "Generate a new key?",
                                "Documents protected with the current key can no longer be read or traced "
                                "unless you keep a copy of it.\n\nGenerate a new key anyway?") != QMessageBox.Yes:
            return
        self.settings.team_key = _new_key()
        self.settings.save()
        self._show_key(self.reveal.isChecked())
        self.saved.setText("New team key generated ✔")


__all__: List[str] = ["HomePage", "ProtectPage", "TracePage", "EncryptPage", "HistoryPage", "SettingsPage"]
