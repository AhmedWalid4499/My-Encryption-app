"""User settings and the team watermark key, stored in %APPDATA%\\VeilMark (Windows) or
~/Library/Application Support/VeilMark (Mac)."""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import APP_NAME


def data_dir() -> Path:
    override = os.environ.get("VEILMARK_HOME")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        path = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME.lower()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _new_key() -> str:
    return base64.b32encode(os.urandom(30)).decode("ascii")  # 48 chars, no padding


def format_key(key_b32: str) -> str:
    """Human friendly 'XXXX-XXXX-...' form of the team key."""
    k = key_b32.replace("-", "").upper()
    return "-".join(k[i:i + 6] for i in range(0, len(k), 6))


def parse_key(text: str) -> str:
    k = "".join(ch for ch in text.upper() if ch.isalnum())
    raw = base64.b32decode(k + "=" * (-len(k) % 8))
    if len(raw) < 16:
        raise ValueError("Team key is too short")
    return k


# --------------------------------------------------------------------------- #
# Keyring: every team key ever used on this computer (never shrinks)
# --------------------------------------------------------------------------- #
def keyring_path() -> Path:
    return data_dir() / "keyring.json"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def keyring_load() -> list:
    """[{"key": ..., "added": iso-date, "label": ...}, ...] oldest first. Never raises."""
    try:
        data = json.loads(keyring_path().read_text(encoding="utf-8"))
        return [k for k in data.get("keys", []) if isinstance(k, dict) and k.get("key")]
    except (OSError, ValueError, AttributeError):
        return []


def keyring_add(key: str, label: str = "") -> None:
    keys = keyring_load()
    if any(k["key"] == key for k in keys):
        return
    keys.append({"key": key, "added": time.strftime("%Y-%m-%d %H:%M"), "label": label})
    try:
        _atomic_write(keyring_path(), json.dumps({"keys": keys}, indent=2))
    except OSError:
        pass


def derive_key(team_key: str) -> bytes:
    """256-bit working key derived (HKDF-SHA256) from a shareable team key."""
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    raw = base64.b32decode(team_key + "=" * (-len(team_key) % 8))
    return HKDF(algorithm=SHA256(), length=32, salt=b"VeilMark", info=b"team watermark key v1").derive(raw)


@dataclass
class Settings:
    owner_name: str = ""
    organization: str = ""
    team_key: str = ""               # legacy (VeilMark 1.0-1.3): only used to read older watermarks
    output_folder: str = ""          # empty = next to the original file
    filename_pattern: str = "{stem} - for {recipient}{ext}"
    aes_armour: bool = True
    visible_footer: bool = False
    footer_template: str = "CONFIDENTIAL – Prepared for {recipient} · {organization} · {date}"
    check_updates: bool = True
    last_update_check: float = 0.0
    last_message: str = ""           # watermark text used last time (pre-filled on the Embed page)
    layers: dict = field(default_factory=lambda: {
        "properties": True, "custom_xml": True, "invisible_text": True,
        "hidden_sheet": True, "images": True, "excel_cell_text": False,
    })

    @property
    def key_bytes(self) -> bytes:
        """Key used for NEW watermarks: the one built into the app."""
        from .appkey import APP_KEY

        return derive_key(APP_KEY)

    @property
    def all_key_bytes(self) -> list:
        """Built-in key first, then any older per-computer keys (so watermarks from 1.0-1.3 still extract)."""
        from .appkey import APP_KEY

        keys = [APP_KEY]
        for k in [self.team_key] + [k["key"] for k in reversed(keyring_load())]:
            if k and k not in keys:
                keys.append(k)
        out = []
        for k in keys:
            try:
                out.append(derive_key(k))
            except (ValueError, TypeError):
                continue
        return out

    def set_team_key(self, new_key: str, label: str = "") -> None:
        """Legacy helper: remember another key for reading older watermarks."""
        if self.team_key:
            keyring_add(self.team_key, "previous key")
        self.team_key = new_key
        keyring_add(new_key, label)
        self.save()

    # -- persistence -------------------------------------------------------- #
    @staticmethod
    def path() -> Path:
        return data_dir() / "settings.json"

    @staticmethod
    def backup_path() -> Path:
        return data_dir() / "settings.backup.json"

    @classmethod
    def _from_file(cls, path: Path) -> "Settings":
        """Read with retries (antivirus / OneDrive can hold a short lock). Raises on failure."""
        last = None
        for _ in range(5):
            try:
                text = path.read_text(encoding="utf-8")
                break
            except PermissionError as exc:
                last = exc
                time.sleep(0.3)
        else:
            raise last
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("settings file is not valid")
        s = cls()
        for k, v in data.items():
            if hasattr(s, k):
                if k == "layers" and isinstance(v, dict):
                    s.layers.update(v)
                else:
                    setattr(s, k, v)
        return s

    @classmethod
    def load(cls) -> "Settings":
        """Load settings. Never replaces an existing team key with a new random one:
        a damaged file is kept aside and restored from the backup copy or the keyring."""
        p, backup = cls.path(), cls.backup_path()
        s = None
        if p.exists():
            try:
                s = cls._from_file(p)
            except (OSError, ValueError, TypeError):
                if p.exists():
                    try:
                        os.replace(p, p.with_name(f"settings.damaged-{time.strftime('%Y%m%d-%H%M%S')}.json"))
                    except OSError:
                        pass
        if s is None and backup.exists():
            try:
                s = cls._from_file(backup)
            except (OSError, ValueError, TypeError):
                s = None
        if s is None:
            s = cls()
            ring = keyring_load()
            if ring:  # settings lost: keep the most recent legacy key for reading old watermarks
                s.team_key = ring[-1]["key"]
        if s.team_key:
            keyring_add(s.team_key, "team key")
        try:
            s.save()
        except OSError:
            pass
        return s

    def save(self) -> None:
        text = json.dumps(asdict(self), indent=2)
        _atomic_write(self.path(), text)
        try:
            _atomic_write(self.backup_path(), text)
        except OSError:
            pass
        if self.team_key:
            keyring_add(self.team_key, "team key")
