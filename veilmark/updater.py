"""Automatic updates from GitHub Releases.

1. ``check()`` asks the GitHub API for the latest release and compares versions.
2. ``download()`` fetches ``VeilMark-Setup.exe`` in the background and verifies its
   SHA-256 checksum (published by the build workflow) before it is ever run.
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
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
INSTALLER_NAME = "VeilMark-Setup.exe"
DOWNLOAD_URL = f"https://github.com/{GITHUB_REPO}/releases/latest/download/{INSTALLER_NAME}"
CHECKSUMS_NAME = "SHA256SUMS.txt"
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
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - fixed https URLs


def _fetch_json(url: str, timeout: float) -> dict:
    with _get(url, timeout, "application/vnd.github+json") as resp:
        return json.loads(resp.read().decode("utf-8"))


def check(timeout: float = 15, fetch=_fetch_json) -> Optional[UpdateInfo]:
    """Return info about a newer release, or None when VeilMark is up to date."""
    try:
        rel = fetch(LATEST_API, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None  # no release published yet
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - offline, rate-limited, no release yet...
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc
    tag = rel.get("tag_name") or ""
    if rel.get("draft") or rel.get("prerelease") or not is_newer(tag):
        return None
    assets = rel.get("assets") or []
    installer = next((a for a in assets if a.get("name") == INSTALLER_NAME), None)
    if installer is None:
        return None  # release still building / no Windows installer attached
    sha = (installer.get("digest") or "").removeprefix("sha256:")
    if not sha:
        sums = next((a for a in assets if a.get("name") == CHECKSUMS_NAME), None)
        if sums:
            try:
                with _get(sums["browser_download_url"], timeout, "application/octet-stream") as resp:
                    for line in resp.read().decode("utf-8", "ignore").splitlines():
                        parts = line.split()
                        if len(parts) == 2 and parts[1].lstrip("*") == INSTALLER_NAME:
                            sha = parts[0].lower()
            except Exception:  # noqa: BLE001
                sha = ""
    return UpdateInfo(version=tag.lstrip("vV"), notes=rel.get("body") or "", page=rel.get("html_url") or RELEASES_PAGE,
                      url=installer["browser_download_url"], size=int(installer.get("size") or 0), sha256=sha)


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
    if target.exists() and (not info.sha256 or _sha256(target) == info.sha256):
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
    if info.sha256 and _sha256(part) != info.sha256.lower():
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
