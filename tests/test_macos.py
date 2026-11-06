"""Mac launch housekeeping: macOS should ask about VeilMark only once."""
from pathlib import Path, PurePosixPath

from veilmark import macos


def test_detects_copies_macos_keeps_checking():
    trans = PurePosixPath("/private/var/folders/ab/xyz/T/AppTranslocation/1F2E-UUID/d/VeilMark.app")
    assert macos.location_problem(trans) == "translocated"
    assert macos.location_problem(PurePosixPath("/Volumes/VeilMark/VeilMark.app")) == "disk image"
    assert macos.location_problem(PurePosixPath("/Applications/VeilMark.app")) is None
    assert macos.location_problem(PurePosixPath("/Users/sara/Applications/VeilMark.app")) is None
    assert "Applications" in macos.move_to_applications_message("translocated")


def test_startup_check_is_silent_off_mac_or_from_source():
    assert macos.startup_check(None) is None


import subprocess  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402


@pytest.mark.skipif(sys.platform != "darwin", reason="real quarantine flags exist only on a Mac")
def test_clears_the_downloaded_from_internet_flag(tmp_path):
    app = tmp_path / "VeilMark.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "VeilMark").write_text("x")
    for target in (app, app / "Contents" / "MacOS" / "VeilMark"):
        subprocess.run(["xattr", "-w", macos.QUARANTINE, "0083;00000000;Safari;", str(target)], check=True)
    assert macos.has_quarantine(app)
    assert macos.startup_check(app) is None and not macos.has_quarantine(app)
    out = subprocess.run(["xattr", str(app / "Contents" / "MacOS" / "VeilMark")], capture_output=True, text=True)
    assert macos.QUARANTINE not in out.stdout  # cleared inside the bundle too
