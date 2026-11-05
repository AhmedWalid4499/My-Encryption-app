import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


def test_main_window_builds(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("VEILMARK_HOME", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    from veilmark.gui.main import MainWindow
    from veilmark.gui.pages import password_strength

    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    for i in range(w.nav.count()):
        w.nav.setCurrentRow(i)
        app.processEvents()
    assert w.stack.currentIndex() == w.nav.count() - 1
    assert password_strength("")[0] == 0 and password_strength("Sakura#Slice-2027")[0] >= 4
    w.close()
