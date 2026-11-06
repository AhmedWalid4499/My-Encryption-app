"""Mac-only housekeeping so macOS asks "Are you sure you want to open VeilMark?" only once.

VeilMark isn't notarised by Apple (that needs a paid Apple Developer account), so macOS checks every copy that
carries the "downloaded from the internet" flag (the ``com.apple.quarantine`` attribute):

* After the person has approved VeilMark once, the app removes that flag from itself, so later launches and later
  versions (the updater installs them without the flag) open without asking again.
* A flagged app started from Downloads or straight from the disk image is run by macOS from a random temporary
  copy ("App Translocation"). That copy is checked again on every launch and can't be fixed from inside, so VeilMark
  asks the person to move it into Applications instead.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

QUARANTINE = "com.apple.quarantine"


def location_problem(app: Path) -> Optional[str]:
    """Why macOS will keep asking about this copy of VeilMark.app: "translocated", "disk image" or None."""
    path = str(app)
    if "/AppTranslocation/" in path:
        return "translocated"
    if path.startswith("/Volumes/"):
        return "disk image"
    return None


def has_quarantine(app: Path) -> bool:
    try:
        return QUARANTINE in os.listxattr(app)  # type: ignore[attr-defined]  # macOS/Linux only
    except (AttributeError, OSError):
        try:
            out = subprocess.run(["xattr", str(app)], capture_output=True, text=True, timeout=10)  # noqa: S603,S607
            return QUARANTINE in out.stdout
        except Exception:  # noqa: BLE001
            return False


def clear_quarantine(app: Path) -> bool:
    """Remove the "downloaded from the internet" flag from the whole app (it isn't part of the code signature)."""
    if not os.access(app, os.W_OK):
        return False
    try:
        subprocess.run(["xattr", "-dr", QUARANTINE, str(app)], capture_output=True, timeout=60,  # noqa: S603,S607
                       check=False)
    except Exception:  # noqa: BLE001
        return False
    return not has_quarantine(app)


def move_to_applications_message(problem: str) -> str:
    where = "straight from the disk image" if problem == "disk image" else "from your Downloads folder"
    return (f"VeilMark is running {where}, so macOS will ask you to confirm it every time you open it.\n\n"
            "To fix this once and for all: quit VeilMark, drag VeilMark into your Applications folder (or run the "
            "VeilMark installer), and open it from Applications. Your settings are kept.")


def startup_check(app: Optional[Path]) -> Optional[str]:
    """Run at launch. Returns a message to show the person, or None when everything is fine."""
    if sys.platform != "darwin" or app is None:
        return None
    problem = location_problem(app)
    if problem:
        return move_to_applications_message(problem)
    if has_quarantine(app):
        clear_quarantine(app)  # approved once already (otherwise we wouldn't be running): don't ask again
    return None
