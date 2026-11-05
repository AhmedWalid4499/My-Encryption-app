import hashlib
import re
from pathlib import Path

import pytest

from veilmark import __version__, updater

ROOT = Path(__file__).resolve().parents[1]


def _release(tag, assets):
    return {"tag_name": tag, "draft": False, "prerelease": False, "body": "notes",
            "html_url": "https://example/rel", "assets": assets}


def _asset(name, size=10, digest=None):
    a = {"name": name, "size": size, "browser_download_url": f"https://example/{name}"}
    if digest:
        a["digest"] = digest
    return a


def test_version_compare():
    assert updater.is_newer("v1.10.0", "1.9.3")
    assert not updater.is_newer("v1.1.0", "1.1.0")
    assert not updater.is_newer("", "1.0.0")


def test_check_finds_newer_release():
    rel = _release("v99.0.0", [_asset("VeilMark-Setup.exe", 123, "sha256:" + "ab" * 32)])
    info = updater.check(fetch=lambda url, t: rel)
    assert info.version == "99.0.0" and info.size == 123 and info.sha256 == "ab" * 32


def test_check_up_to_date_or_no_installer():
    assert updater.check(fetch=lambda u, t: _release(f"v{__version__}", [_asset("VeilMark-Setup.exe")])) is None
    assert updater.check(fetch=lambda u, t: _release("v99.0.0", [_asset("other.zip")])) is None


def test_check_offline_raises_friendly_error():
    def boom(url, t):
        raise OSError("no network")

    with pytest.raises(updater.UpdateError, match="Could not reach GitHub"):
        updater.check(fetch=boom)


class _Resp:
    def __init__(self, data):
        self.data, self.headers = data, {"Content-Length": str(len(data))}

    def read(self, n=-1):
        out, self.data = (self.data, b"") if n < 0 else (self.data[:n], self.data[n:])
        return out

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_verifies_checksum(tmp_path, monkeypatch):
    payload = b"installer-bytes" * 1000
    monkeypatch.setattr(updater, "_get", lambda *a, **k: _Resp(payload))
    good = updater.UpdateInfo("9.9.9", "", "", "https://x/VeilMark-Setup.exe", len(payload),
                              hashlib.sha256(payload).hexdigest())
    path = updater.download(good, dest_dir=tmp_path)
    assert path.read_bytes() == payload and path.name == "VeilMark-Setup-9.9.9.exe"
    bad = updater.UpdateInfo("9.9.8", "", "", "https://x", len(payload), "00" * 32)
    with pytest.raises(updater.UpdateError, match="security check"):
        updater.download(bad, dest_dir=tmp_path)
    assert not list(tmp_path.glob("*9.9.8*"))


def test_packaging_versions_match_app():
    iss = (ROOT / "packaging" / "installer.iss").read_text()
    assert f'#define AppVersion "{__version__}"' in iss
    assert "OutputBaseFilename=VeilMark-Setup\n" in iss
    vi = (ROOT / "packaging" / "version_info.txt").read_text()
    assert f'"FileVersion", "{__version__}"' in vi
    assert re.search(r"filevers=\((\d+), (\d+), (\d+)", vi).groups() == tuple(__version__.split("."))
