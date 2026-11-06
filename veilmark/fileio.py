"""Reading and writing user files with friendly errors.

On Windows, "[Errno 13] Permission denied" usually means another program holds the
file: PowerPoint/Word/Excel keep a lock while the document is open, and OneDrive
locks a file for a moment while it syncs. Short locks are retried; anything else is
turned into a message a normal user can act on.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

RETRIES = 6          # ~4.5 s in total: enough for a OneDrive sync lock to clear
RETRY_DELAY = 0.75


class FileAccessError(OSError):
    """A user-facing error: ``str(exc)`` is a plain-language explanation."""


def _office_app(path: Path) -> str:
    ext = path.suffix.lower()
    if ext.startswith(".ppt"):
        return "PowerPoint"
    if ext.startswith(".doc"):
        return "Word"
    if ext.startswith(".xls"):
        return "Excel"
    return "another program"


def _cloud_hint(path: Path) -> str:
    text = str(path).lower()
    if "onedrive" in text or "sharepoint" in text:
        return " OneDrive may also be syncing it — wait a few seconds and try again."
    return ""


def read_bytes(path) -> bytes:
    path = Path(path)
    last = None
    for attempt in range(RETRIES):
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            raise FileAccessError(f"“{path.name}” was not found. It may have been moved, renamed or deleted.") \
                from None
        except PermissionError as exc:
            last = exc
            if attempt < RETRIES - 1:
                time.sleep(RETRY_DELAY)
    raise FileAccessError(
        f"VeilMark can't open “{path.name}” because it is in use. If it's open in {_office_app(path)}, "
        f"close it and try again.{_cloud_hint(path)}") from last


def _verify_on_disk(path: Path, data: bytes) -> None:
    """Read the saved file back: catches sync clients / antivirus changing or truncating it."""
    import hashlib

    try:
        with open(path, "rb") as fh:
            ok = hashlib.sha256(fh.read()).digest() == hashlib.sha256(data).digest()
    except OSError:
        ok = True  # can't re-open right now (e.g. OneDrive picked it up): the write itself succeeded
    if not ok:
        try:
            path.unlink()
        except OSError:
            pass
        raise FileAccessError(f"“{path.name}” wasn't saved correctly (the file on disk differs from what VeilMark "
                              "wrote, possibly changed by a sync or security program). Nothing was kept — "
                              "please try again or choose a different save folder.")


def write_bytes(path, data: bytes) -> None:
    """Write atomically (temp file + rename) so a failed save never leaves half a file behind."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.veilmark-tmp")
    last = None
    for attempt in range(RETRIES):
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            _verify_on_disk(path, data)
            return
        except FileAccessError:
            raise
        except PermissionError as exc:
            last = exc
            try:
                tmp.unlink()
            except OSError:
                pass
            if attempt < RETRIES - 1:
                time.sleep(RETRY_DELAY)
        except OSError as exc:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise FileAccessError(f"VeilMark couldn't save “{path.name}”: {exc.strerror or exc}.") from exc
    raise FileAccessError(
        f"VeilMark isn't allowed to save “{path.name}” in {path.parent}. The folder may be read-only or "
        "protected (for example by Windows ‘Controlled folder access’ or the Mac’s Privacy & Security settings), or a file with that name is open in "
        f"another program.{_cloud_hint(path)} You can choose a different save folder in the options.") from last
