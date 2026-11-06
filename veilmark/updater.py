"""Automatic updates from GitHub Releases.

1. ``check()`` reads this platform's manifest from the GitHub repository's ``releases/`` folder
   (the build workflow writes it whenever a new version passes all tests) and compares versions.
   Every version keeps its own file there; the manifest names the newest one:

   * Windows: ``latest.json``              -> ``VeilMark-Setup-<version>.exe`` (Inno Setup installer)
   * Mac (Apple silicon): ``latest-macos-arm64.json``  -> ``VeilMark-macOS-AppleSilicon-<version>.dmg``
   * Mac (Intel):         ``latest-macos-x86_64.json`` -> ``VeilMark-macOS-Intel-<version>.dmg``
2. ``download()`` fetches the installer in the background and verifies its SHA-256
   checksum from the manifest before it is ever run.
3. ``launch_installer()`` installs it: on Windows the installer runs silently; on a Mac a small
   helper waits for VeilMark to quit, copies the new VeilMark.app out of the disk image over the old
   one and reopens it. Settings and history are kept either way.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import ssl
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
INSTALLER_NAME = "VeilMark-Setup.exe"  # fallback only; latest.json names the versioned EXE
MAC_DOWNLOADS = {  # machine -> (manifest, fallback disk image name; the manifest names the versioned .dmg)
    "arm64": ("latest-macos-arm64.json", "VeilMark-macOS-AppleSilicon.dmg"),
    "x86_64": ("latest-macos-x86_64.json", "VeilMark-macOS-Intel.dmg"),
}
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


def _mac_downloads(machine: Optional[str] = None) -> tuple:
    machine = (machine or platform.machine() or "").lower()
    return MAC_DOWNLOADS["x86_64" if machine in ("x86_64", "amd64", "i386") else "arm64"]


def manifest_url(plat: Optional[str] = None, machine: Optional[str] = None) -> str:
    """The manifest describing the newest build for this kind of computer."""
    if (plat or sys.platform) == "darwin":
        return f"{RAW_BASE}/{_mac_downloads(machine)[0]}"
    return MANIFEST_URL


def default_installer(plat: Optional[str] = None, machine: Optional[str] = None) -> str:
    if (plat or sys.platform) == "darwin":
        return _mac_downloads(machine)[1]
    return INSTALLER_NAME


def mac_app_bundle() -> Optional[Path]:
    """The running VeilMark.app (frozen Mac build only), e.g. /Applications/VeilMark.app."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def can_self_install() -> bool:
    """Only an installed build can replace itself; source checkouts just get a link."""
    if not getattr(sys, "frozen", False):
        return False
    if sys.platform == "win32":
        return True
    app = mac_app_bundle()
    # the app must sit in a folder we may write to (normally /Applications for an admin user), and must not be
    # running straight from the read-only disk image
    return bool(app and not str(app).startswith("/Volumes/") and os.access(app.parent, os.W_OK))


_SSL_CONTEXT: Optional[ssl.SSLContext] = None


def ssl_context() -> ssl.SSLContext:
    """Certificates to trust for HTTPS.

    The packaged Mac app runs a python.org Python, which does *not* read the Mac's keychain, so plain urllib fails
    with "CERTIFICATE_VERIFY_FAILED". Use the computer's own trust store instead (macOS keychain / Windows
    certificate store, which also covers company proxies), then the bundled Mozilla list as a fallback.
    """
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        try:
            import truststore

            _SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except Exception:  # noqa: BLE001 - very old OS or missing module: fall back below
            try:
                import certifi

                _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
            except Exception:  # noqa: BLE001
                _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


def _get(url: str, timeout: float = 15, accept: str = "application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept,
                                               "Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())  # noqa: S310 - fixed https URLs


def _fetch_json(url: str, timeout: float) -> dict:
    with _get(url, timeout) as resp:
        return json.loads(resp.read().decode("utf-8-sig"))


def check(timeout: float = 15, fetch=_fetch_json) -> Optional[UpdateInfo]:
    """Read releases/latest.json from the repository; return info if it is newer than this copy."""
    try:
        manifest = fetch(manifest_url(), timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None  # nothing published yet
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - offline, proxy, ...
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc
    version = str(manifest.get("version") or "")
    name = os.path.basename(str(manifest.get("installer") or default_installer()))  # never a path from the web
    sha = str(manifest.get("sha256") or "").lower()
    if not is_newer(version) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        return None  # up to date, or a manifest without a checksum (never install unverified files)
    url = f"{RAW_BASE}/{name}"
    # on a Mac, "Download" goes straight to the disk image rather than a GitHub folder listing
    page = url if sys.platform == "darwin" else RELEASES_PAGE
    return UpdateInfo(version=version.lstrip("vV"), notes=str(manifest.get("notes") or ""), page=page,
                      url=url, size=int(manifest.get("size") or 0), sha256=sha)


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
    ext = Path(info.url).suffix.lower() if Path(info.url).suffix.lower() in (".exe", ".dmg") else ".exe"
    target = folder / f"VeilMark-Setup-{info.version}{ext}"
    if target.exists() and info.sha256 and _sha256(target) == info.sha256:
        return target
    for old in folder.glob("VeilMark-Setup-*"):  # tidy older downloads
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


MAC_INSTALL_SCRIPT = """#!/bin/bash
# VeilMark Mac updater: wait for VeilMark to quit, swap in the new VeilMark.app, reopen it.
PID={pid}
DMG={dmg}
APP={app}
for _ in $(seq 1 120); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
MNT=$(mktemp -d "${{TMPDIR:-/tmp}}/veilmark-update.XXXXXX")
if hdiutil attach -nobrowse -readonly -noautoopen -quiet -mountpoint "$MNT" "$DMG"; then
  if [ -d "$MNT/VeilMark.app" ]; then
    rm -rf "$APP.old"
    if mv "$APP" "$APP.old"; then
      if ditto "$MNT/VeilMark.app" "$APP"; then
        rm -rf "$APP.old"
      else
        rm -rf "$APP"; mv "$APP.old" "$APP"   # copy failed: put the old version back
      fi
    fi
    xattr -dr com.apple.quarantine "$APP" 2>/dev/null
  fi
  hdiutil detach -quiet "$MNT" || hdiutil detach -quiet -force "$MNT"
fi
rmdir "$MNT" 2>/dev/null
open "$APP"
"""


def mac_install_script(dmg: Path, app: Path, pid: int) -> str:
    return MAC_INSTALL_SCRIPT.format(pid=int(pid), dmg=shlex.quote(str(dmg)), app=shlex.quote(str(app)))


def launch_installer(installer: Path) -> None:
    """Install a downloaded update; VeilMark must quit right after this returns, it is reopened afterwards."""
    if sys.platform == "darwin":
        app = mac_app_bundle()
        if not app or not can_self_install():
            raise UpdateError("VeilMark can't replace itself here. Open the downloaded update and drag VeilMark "
                              "into your Applications folder.")
        script = Path(installer).with_name("install-update.sh")
        script.write_text(mac_install_script(Path(installer), app, os.getpid()), encoding="utf-8")
        subprocess.Popen(["/bin/bash", str(script)], close_fds=True, start_new_session=True,  # noqa: S603
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    if sys.platform != "win32":
        raise UpdateError("Automatic installation is only available in the Windows and Mac apps.")
    # Windows: run the Inno Setup installer silently; it closes VeilMark, upgrades and relaunches it.
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     close_fds=True, creationflags=flags)  # noqa: S603
