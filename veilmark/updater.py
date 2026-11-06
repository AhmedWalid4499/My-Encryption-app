"""Automatic updates from GitHub Releases.

1. ``check()`` reads ``releases/latest.json`` from the GitHub repository (the build workflow
   writes it, together with ``releases/VeilMark-Setup.exe``, whenever a new version passes
   all tests) and compares versions.
2. ``download()`` fetches the installer in the background and verifies its SHA-256
   checksum from the manifest before it is ever run.
3. ``launch_installer()`` starts the installer silently; it closes VeilMark,
   upgrades it in place (settings and history are kept) and reopens it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import __version__
from .settings import data_dir

GITHUB_REPO = "AhmedWalid4499/My-Encryption-app"
# "HEAD" = the repository's default branch, so this keeps working if the branch is renamed (e.g. to main)
RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/HEAD/releases"
MANIFEST_URL = f"{RAW_BASE}/latest.json"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/tree/HEAD/releases"
INSTALLER_NAME = "VeilMark-Setup.exe"
DOWNLOAD_URL = f"{RAW_BASE}/{INSTALLER_NAME}"
USER_AGENT = f"VeilMark-Updater/{__version__}"


class UpdateError(Exception):
    pass


@dataclass
class UpdateInfo:
    version: str
    notes: str
    page: str
    url: str
    size: int
    sha256: str = ""


def parse_version(text: str) -> tuple:
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def can_self_install() -> bool:
    """Only the installed Windows build can replace itself; source checkouts just get a link."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def _get(url: str, timeout: float = 15, accept: str = "application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept,
                                               "Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - fixed https URLs


def _fetch_json(url: str, timeout: float) -> dict:
    with _get(url, timeout) as resp:
        return json.loads(resp.read().decode("utf-8-sig"))


def check(timeout: float = 15, fetch=_fetch_json) -> Optional[UpdateInfo]:
    """Read releases/latest.json from the repository; return info if it is newer than this copy."""
    try:
        manifest = fetch(MANIFEST_URL, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None  # nothing published yet
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - offline, proxy, ...
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc
    version = str(manifest.get("version") or "")
    name = os.path.basename(str(manifest.get("installer") or INSTALLER_NAME))  # never a path from the web
    sha = str(manifest.get("sha256") or "").lower()
    if not is_newer(version) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        return None  # up to date, or a manifest without a checksum (never install unverified files)
    return UpdateInfo(version=version.lstrip("vV"), notes=str(manifest.get("notes") or ""), page=RELEASES_PAGE,
                      url=f"{RAW_BASE}/{name}", size=int(manifest.get("size") or 0), sha256=sha)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(info: UpdateInfo, progress: Optional[Callable[[str, float], None]] = None,
             dest_dir: Optional[Path] = None) -> Path:
    folder = Path(dest_dir or data_dir() / "updates")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"VeilMark-Setup-{info.version}.exe"
    if target.exists() and info.sha256 and _sha256(target) == info.sha256:
        return target
    for old in folder.glob("VeilMark-Setup-*.exe"):  # tidy older downloads
        if old != target:
            old.unlink(missing_ok=True)
    part = target.with_suffix(".part")
    done = 0
    try:
        with _get(info.url, 60, "application/octet-stream") as resp, open(part, "wb") as out:
            total = int(resp.headers.get("Content-Length") or info.size or 0)
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress("Downloading update…", done / total)
    except Exception as exc:  # noqa: BLE001
        part.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc}") from exc
    if info.size and done != info.size:
        part.unlink(missing_ok=True)
        raise UpdateError("Download was incomplete. Please try again.")
    if not info.sha256 or _sha256(part) != info.sha256.lower():
        part.unlink(missing_ok=True)
        raise UpdateError("The downloaded update failed its security check and was deleted.")
    os.replace(part, target)
    return target


def launch_installer(installer: Path) -> None:
    """Run the Inno Setup installer silently; it closes VeilMark, upgrades and relaunches it."""
    if sys.platform != "win32":
        raise UpdateError("Automatic installation is only available on Windows.")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     close_fds=True, creationflags=flags)  # noqa: S603
