"""Build the main window headless in a child process.

Runs in a subprocess that ends with ``os._exit`` after its checks: Qt can crash
(SIGBUS/SIGSEGV) while Python tears widgets down at interpreter exit, which would
otherwise kill the whole pytest run even though every check passed.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = textwrap.dedent("""
    import os, sys
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication
    from veilmark.gui.main import MainWindow
    from veilmark.gui.pages import password_strength

    app = QApplication([])
    w = MainWindow()
    seen = []
    for page in range(w.stack.count()):
        w.open_page(page)
        app.processEvents()
        seen.append(w.stack.currentIndex())
    # section headers in the sidebar must not change the page
    w.open_page(1)
    w.nav.setCurrentRow(1 if w._nav_rows[1] is None else 0)
    ok = (seen == list(range(w.stack.count())) and w.stack.count() == 7
          and w.encrypt.ENCRYPT and not w.decrypt.ENCRYPT
          and password_strength("")[0] == 0 and password_strength("Sakura#Slice-2027")[0] >= 4
          and w.embed.footer_cb is not None and w.updates.state == "idle")
    QThreadPool.globalInstance().waitForDone(5000)
    sys.stdout.write("GUI-OK\\n" if ok else "GUI-FAIL\\n")
    sys.stdout.flush()
    os._exit(0 if ok else 1)
""")


def test_main_window_builds(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", VEILMARK_HOME=str(tmp_path),
               PYTHONPATH=str(ROOT))
    proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True,
                          text=True, timeout=120)
    assert "GUI-OK" in proc.stdout, proc.stdout + proc.stderr
    assert proc.returncode == 0
