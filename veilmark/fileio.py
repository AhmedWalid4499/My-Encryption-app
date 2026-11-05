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


def write_bytes(path, data: bytes) -> None:
    """Write atomically (temp file + rename) so a failed save never leaves half a file behind."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.veilmark-tmp")
    last = None
    for attempt in range(RETRIES):
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
            return
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
        "protected (for example by Windows ‘Controlled folder access’), or a file with that name is open in "
        f"another program.{_cloud_hint(path)} You can choose a different save folder in the options.") from last
