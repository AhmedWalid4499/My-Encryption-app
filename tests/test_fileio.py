import builtins

import pytest

from veilmark import fileio


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(fileio, "RETRY_DELAY", 0)


def _locked_open(times):
    """open() that raises PermissionError (Windows sharing violation) the first ``times`` calls."""
    real = builtins.open
    state = {"n": 0}

    def fake(path, mode="r", *a, **k):
        state["n"] += 1
        if state["n"] <= times:
            raise PermissionError(13, "Permission denied", str(path))
        return real(path, mode, *a, **k)
    return fake


def test_short_lock_is_retried(tmp_path, monkeypatch):
    f = tmp_path / "deck.pptx"
    f.write_bytes(b"data")
    monkeypatch.setattr(builtins, "open", _locked_open(2))  # e.g. OneDrive syncing
    assert fileio.read_bytes(f) == b"data"


def test_file_open_in_powerpoint_gives_friendly_message(tmp_path, monkeypatch):
    f = tmp_path / "OneDrive - orange.com" / "SKF Weekly.pptx"
    f.parent.mkdir()
    f.write_bytes(b"data")
    monkeypatch.setattr(builtins, "open", _locked_open(99))
    with pytest.raises(fileio.FileAccessError) as e:
        fileio.read_bytes(f)
    msg = str(e.value)
    assert "SKF Weekly.pptx" in msg and "PowerPoint" in msg and "OneDrive" in msg and "Errno" not in msg


def test_missing_file(tmp_path):
    with pytest.raises(fileio.FileAccessError, match="not found"):
        fileio.read_bytes(tmp_path / "gone.docx")


def test_write_is_atomic_and_friendly(tmp_path, monkeypatch):
    out = tmp_path / "copy.docx"
    fileio.write_bytes(out, b"one")
    assert out.read_bytes() == b"one" and not list(tmp_path.glob(".*veilmark-tmp"))
    monkeypatch.setattr(builtins, "open", _locked_open(99))
    with pytest.raises(fileio.FileAccessError, match="save folder"):
        fileio.write_bytes(out, b"two")
    monkeypatch.undo()
    assert out.read_bytes() == b"one"  # old content untouched
    assert not list(tmp_path.glob(".*veilmark-tmp"))


def test_protect_and_encrypt_report_locked_file(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILMARK_HOME", str(tmp_path / "home"))
    from samples import make_pptx
    from veilmark.crypto import encrypt_file
    from veilmark.service import protect_file
    from veilmark.settings import Settings

    src = tmp_path / "deck.pptx"
    make_pptx(src)
    s = Settings.load()
    real = builtins.open

    def fake(path, mode="r", *a, **k):
        if str(path) == str(src):
            raise PermissionError(13, "Permission denied", str(path))
        return real(path, mode, *a, **k)
    monkeypatch.setattr(builtins, "open", fake)
    with pytest.raises(fileio.FileAccessError, match="close it and try again"):
        protect_file(src, message="x", settings=s)
    with pytest.raises(fileio.FileAccessError, match="close it and try again"):
        encrypt_file(src, "password1")
