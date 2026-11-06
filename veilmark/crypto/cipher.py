"""VeilMark file cipher - the thesis' cascaded chaotic/S-box scheme, applied to any file.

Pipeline (mirrors EncImg2 x3 + the ``enc`` state machine from the Mathematica code):

    round 1:  XOR with 4-D hyperchaotic Chen keystream (k1)   -> S-box sb1
    round 2:  XOR with Mersenne Twister keystream (k2)        -> S-box sb2
    round 3:  XOR with 5-D hyperchaotic keystream (k3)        -> S-box sb3
    round 4:  bit-level state-machine diffusion with keyMT   (``trans`` / ``enc``)
    armour :  AES-256-GCM authenticated encryption (optional, on by default)

All keystream seeds come from the user's password through scrypt and a fresh
random salt per file, so encrypting the same file twice never reuses a keystream.
Without the AES armour an HMAC-SHA256 tag still detects wrong passwords and tampering.

Container layout (``.vmk``)::

    b"VMK1" | flags(1) | scrypt_log2n(1) | salt(16) | nonce(12) | body | [hmac(32)]
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import struct
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.exceptions import InvalidTag

from ..fileio import read_bytes, write_bytes
from .chaos import HyperChen4D, Hyper5D, MersenneStream
from .sboxes import INV_SBOXES, SBOXES

MAGIC = b"VMK1"
EXTENSION = ".vmk"
FLAG_AES = 0x01
SCRYPT_LOG2N = 15
_HEADER = struct.Struct(">4sBB16s12s")

Progress = Optional[Callable[[str, float], None]]


class DecryptionError(Exception):
    """Wrong password, corrupted file or not a VeilMark file."""


# --------------------------------------------------------------------------- #
# The ``trans`` / ``enc`` state machine from the thesis
# --------------------------------------------------------------------------- #
# state -> (next state, operation); "x" = XOR, "n" = XNOR (cXnor in Mathematica)
_TRANS = {0: (1, "x"), 1: (6, "n"), 2: (3, "x"), 3: (8, "n"), 4: (5, "x"),
          5: (2, "x"), 6: (7, "n"), 7: (4, "x")}


def state_machine_byte(n1: int, n2: int) -> int:
    """Literal bit-by-bit port of ``enc[n1, n2]`` (kept for reference & tests)."""
    bits1 = [(n1 >> (7 - i)) & 1 for i in range(8)]
    bits2 = [(n2 >> (7 - i)) & 1 for i in range(8)]
    state, out = 0, 0
    for i in range(8):
        state_next, op = _TRANS.get(state, (1, "x"))
        bit = bits1[i] ^ bits2[i]
        if op == "n":
            bit ^= 1
        out = (out << 1) | bit
        state = state_next
    return out


def _state_machine_mask() -> int:
    """The machine's transitions don't depend on the data, so its XNOR positions form a fixed mask."""
    return state_machine_byte(0, 0)


_SM_MASK = np.uint8(_state_machine_mask())  # == 0x61


def state_machine(data: np.ndarray, key: np.ndarray) -> np.ndarray:
    """Vectorised ``enc`` over whole arrays. It is its own inverse, as in the thesis."""
    return data ^ key ^ _SM_MASK


# --------------------------------------------------------------------------- #
# Key schedule
# --------------------------------------------------------------------------- #
def _derive_keys(password: str, salt: bytes, log2n: int) -> dict:
    if not password:
        raise ValueError("Password must not be empty")
    master = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**log2n, r=8, p=1,
                            maxmem=256 * 1024 * 1024, dklen=32)
    okm = HKDF(algorithm=SHA256(), length=32 * 6, salt=salt,
               info=b"VeilMark chaotic cipher v1").derive(master)
    names = ("chen", "mt", "hyper5d", "keymt", "aes", "mac")
    return {name: okm[i * 32:(i + 1) * 32] for i, name in enumerate(names)}


def _keystreams(keys: dict, n: int, progress: Progress):
    def report(msg, frac):
        if progress:
            progress(msg, frac)

    report("Generating 4-D hyperchaotic Chen key (k1)...", 0.05)
    k1 = HyperChen4D(keys["chen"]).take(n)
    report("Generating Mersenne Twister key (k2)...", 0.35)
    k2 = MersenneStream(keys["mt"]).take(n)
    report("Generating 5-D hyperchaotic key (k3)...", 0.40)
    k3 = Hyper5D(keys["hyper5d"]).take(n)
    report("Generating state-machine key (keyMT)...", 0.75)
    kmt = MersenneStream(keys["keymt"]).take(n)
    return k1, k2, k3, kmt


def chaotic_encrypt(data: bytes, keys: dict, progress: Progress = None) -> bytes:
    buf = np.frombuffer(data, dtype=np.uint8).copy()
    k1, k2, k3, kmt = _keystreams(keys, buf.size, progress)
    for key, sbox in zip((k1, k2, k3), SBOXES):
        buf = sbox[buf ^ key]           # EncImg2: XOR with key, then appSbox
    buf = state_machine(buf, kmt)       # enc[..., keyMT]
    return buf.tobytes()


def chaotic_decrypt(data: bytes, keys: dict, progress: Progress = None) -> bytes:
    buf = np.frombuffer(data, dtype=np.uint8).copy()
    k1, k2, k3, kmt = _keystreams(keys, buf.size, progress)
    buf = state_machine(buf, kmt)
    for key, inv in zip((k3, k2, k1), INV_SBOXES[::-1]):
        buf = inv[buf] ^ key            # DecImg: inverse S-box, then XOR
    return buf.tobytes()


# --------------------------------------------------------------------------- #
# Public byte / file API
# --------------------------------------------------------------------------- #
def encrypt_bytes(plaintext: bytes, password: str, *, aes_armour: bool = True,
                  metadata: Optional[dict] = None, progress: Progress = None,
                  scrypt_log2n: int = SCRYPT_LOG2N) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    if progress:
        progress("Deriving keys from password...", 0.0)
    keys = _derive_keys(password, salt, scrypt_log2n)
    meta = json.dumps(metadata or {}, separators=(",", ":")).encode()
    inner = struct.pack(">I", len(meta)) + meta + plaintext
    body = chaotic_encrypt(inner, keys, progress)
    flags = FLAG_AES if aes_armour else 0
    header = _HEADER.pack(MAGIC, flags, scrypt_log2n, salt, nonce)
    if progress:
        progress("Sealing...", 0.95)
    if aes_armour:
        out = header + AESGCM(keys["aes"]).encrypt(nonce, body, header)
    else:
        out = header + body + hmac.new(keys["mac"], header + body, hashlib.sha256).digest()
    if progress:
        progress("Done", 1.0)
    return out


def decrypt_bytes(blob: bytes, password: str, progress: Progress = None) -> tuple[bytes, dict]:
    if len(blob) < _HEADER.size or blob[:4] != MAGIC:
        raise DecryptionError("This is not a VeilMark encrypted file.")
    magic, flags, log2n, salt, nonce = _HEADER.unpack_from(blob)
    if not 10 <= log2n <= 22:
        raise DecryptionError("Unsupported or corrupted file header.")
    header, rest = blob[:_HEADER.size], blob[_HEADER.size:]
    if progress:
        progress("Deriving keys from password...", 0.0)
    keys = _derive_keys(password, salt, log2n)
    if flags & FLAG_AES:
        try:
            body = AESGCM(keys["aes"]).decrypt(nonce, rest, header)
        except InvalidTag:
            raise DecryptionError("Wrong password, or the file was modified.") from None
    else:
        body, tag = rest[:-32], rest[-32:]
        expected = hmac.new(keys["mac"], header + body, hashlib.sha256).digest()
        if len(rest) < 32 or not hmac.compare_digest(tag, expected):
            raise DecryptionError("Wrong password, or the file was modified.")
    inner = chaotic_decrypt(body, keys, progress)
    (meta_len,) = struct.unpack(">I", inner[:4])
    meta = json.loads(inner[4:4 + meta_len] or b"{}")
    if progress:
        progress("Done", 1.0)
    return inner[4 + meta_len:], meta


def is_encrypted_file(path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == MAGIC
    except OSError:
        return False


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, i = path.stem, path.suffix, 2
    while True:
        candidate = path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def encrypt_file(src, password: str, dest_dir=None, *, aes_armour: bool = True,
                 progress: Progress = None) -> Path:
    src = Path(src)
    plain = read_bytes(src)
    meta = {"name": src.name, "size": len(plain), "encrypted": int(time.time()),
            "sha256": hashlib.sha256(plain).hexdigest()}
    blob = encrypt_bytes(plain, password, aes_armour=aes_armour,
                         metadata=meta, progress=progress)
    # prove the file can be decrypted again before anything is saved
    if progress:
        progress("Verifying the encrypted file…", 0.97)
    check, _ = decrypt_bytes(blob, password)
    if check != plain:
        raise DecryptionError("Encryption self-check failed, so nothing was saved. Please try again.")
    out = _unique(Path(dest_dir or src.parent) / (src.name + EXTENSION))
    write_bytes(out, blob)
    return out


def decrypt_file(src, password: str, dest_dir=None, progress: Progress = None) -> Path:
    src = Path(src)
    data, meta = decrypt_bytes(read_bytes(src), password, progress)
    expected = meta.get("sha256")
    if expected and hashlib.sha256(data).hexdigest() != expected:
        raise DecryptionError("The decrypted file doesn't match the original, so it was not saved.")
    if meta.get("size") is not None and len(data) != meta["size"]:
        raise DecryptionError("The decrypted file has the wrong size, so it was not saved.")
    name = Path(meta.get("name") or src.stem).name  # never trust a path from the file
    if src.suffix.lower() == EXTENSION and not meta.get("name"):
        name = src.stem
    out = _unique(Path(dest_dir or src.parent) / name)
    write_bytes(out, data)
    return out
