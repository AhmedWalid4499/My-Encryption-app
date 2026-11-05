"""User settings and the team watermark key, stored in %APPDATA%\\VeilMark (Windows)."""

from __future__ import annotations

import base64
import json
import os
import sys
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


@dataclass
class Settings:
    owner_name: str = ""
    organization: str = ""
    team_key: str = field(default_factory=_new_key)
    output_folder: str = ""          # empty = next to the original file
    filename_pattern: str = "{stem} - for {recipient}{ext}"
    aes_armour: bool = True
    layers: dict = field(default_factory=lambda: {
        "properties": True, "custom_xml": True, "invisible_text": True,
        "hidden_sheet": True, "images": True, "excel_cell_text": False,
    })

    @property
    def key_bytes(self) -> bytes:
        """256-bit working key derived (HKDF-SHA256) from the shareable team key."""
        from cryptography.hazmat.primitives.hashes import SHA256
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF

        k = self.team_key
        raw = base64.b32decode(k + "=" * (-len(k) % 8))
        return HKDF(algorithm=SHA256(), length=32, salt=b"VeilMark", info=b"team watermark key v1").derive(raw)

    # -- persistence -------------------------------------------------------- #
    @staticmethod
    def path() -> Path:
        return data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        p = cls.path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                s = cls()
                for k, v in data.items():
                    if hasattr(s, k):
                        if k == "layers":
                            s.layers.update(v)
                        else:
                            setattr(s, k, v)
                return s
            except (ValueError, OSError):
                pass
        s = cls()
        s.save()
        return s

    def save(self) -> None:
        p = self.path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, p)
