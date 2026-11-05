"""Image layer: least-significant-bit steganography.

Port of ``InsertSecretMessage`` / ``ExtractSecretMessage`` from the thesis:
``BitAnd[data, 2^^11111110] + secretBits`` and ``BitAnd[data, 1]`` - one secret
bit replaces the LSB of every colour channel.

Improvements over the original:
* the payload is framed (magic + length + CRC) so it can be found reliably,
* the frame is repeated across the whole picture, so a cropped or partially
  edited image still yields a copy,
* only lossless images are used (PNG/BMP/TIFF/GIF): JPEG re-compression would
  wipe the LSBs, exactly as noted in the thesis.
"""

from __future__ import annotations

import io
import struct
import zlib
from typing import List, Optional

import numpy as np
from PIL import Image

FRAME_MAGIC = b"VMI1"
_HDR = struct.Struct(">4sH")  # magic, payload length
MIN_PIXELS = 48 * 48
LOSSLESS_FORMATS = {"PNG", "BMP", "TIFF", "GIF"}


def _frame(payload: bytes) -> bytes:
    if len(payload) > 0xFFFF:
        raise ValueError("payload too large")
    return _HDR.pack(FRAME_MAGIC, len(payload)) + payload + struct.pack(">I", zlib.crc32(payload))


def capacity_bytes(img: Image.Image) -> int:
    w, h = img.size
    channels = 3
    return (w * h * channels) // 8


def embed(image_bytes: bytes, payload: bytes) -> Optional[bytes]:
    """Return a new image file (same format) carrying ``payload``, or None if unsuitable."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        fmt = (img.format or "").upper()
        img.load()
    except Exception:
        return None
    if fmt not in LOSSLESS_FORMATS or img.size[0] * img.size[1] < MIN_PIXELS:
        return None
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if ("A" in img.mode or "transparency" in img.info) else "RGB")
        if fmt == "GIF":
            fmt = "PNG"  # GIF palettes cannot carry LSB data; Office happily reads PNG bytes
    frame = _frame(payload)
    arr = np.array(img, dtype=np.uint8)
    rgb = arr[..., :3]
    flat = rgb.reshape(-1)
    bits = np.unpackbits(np.frombuffer(frame, dtype=np.uint8))
    if bits.size > flat.size:
        return None
    repeats = flat.size // bits.size
    stream = np.tile(bits, repeats)
    # Thesis: BitAnd[carrier, 254] + secretBits
    flat[: stream.size] = (flat[: stream.size] & 0xFE) | stream
    arr[..., :3] = flat.reshape(rgb.shape)
    out_img = Image.fromarray(arr, mode=img.mode)
    buf = io.BytesIO()
    save_kwargs = {}
    if fmt == "PNG":
        save_kwargs["optimize"] = False
        if "dpi" in img.info:
            save_kwargs["dpi"] = img.info["dpi"]
    out_img.save(buf, format=fmt if fmt != "GIF" else "PNG", **save_kwargs)
    return buf.getvalue()


def extract(image_bytes: bytes) -> List[bytes]:
    """Return the distinct payloads found in the picture (usually one)."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception:
        return []
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    flat = np.asarray(img, dtype=np.uint8)[..., :3].reshape(-1)
    # Thesis: BitAnd[ImageData[img], 1], then group into 8-bit words.
    data = np.packbits(flat & 1).tobytes()
    found: List[bytes] = []
    start = 0
    while True:
        idx = data.find(FRAME_MAGIC, start)
        if idx < 0 or len(found) >= 4:
            break
        start = idx + 1
        if idx + _HDR.size > len(data):
            break
        _, length = _HDR.unpack_from(data, idx)
        end = idx + _HDR.size + length
        if end + 4 > len(data):
            continue
        payload = data[idx + _HDR.size:end]
        (crc,) = struct.unpack_from(">I", data, end)
        if zlib.crc32(payload) == crc and payload not in found:
            found.append(payload)
            start = end
    return found


def pack_payload(token_chain: bytes, sealed_record: Optional[bytes]) -> bytes:
    rec = sealed_record or b""
    return struct.pack(">BH", len(token_chain), len(rec)) + token_chain + rec


def unpack_payload(payload: bytes) -> tuple[bytes, bytes]:
    if len(payload) < 3:
        return b"", b""
    ntok, nrec = struct.unpack_from(">BH", payload)
    tokens = payload[3:3 + ntok]
    record = payload[3 + ntok:3 + ntok + nrec]
    return tokens, record
