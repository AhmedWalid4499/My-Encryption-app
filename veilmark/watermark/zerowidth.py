"""Invisible-text layer: bytes <-> zero-width Unicode characters.

Each byte becomes four invisible characters (2 bits each). The sequence is
wrapped in invisible start/end markers so it can be found again after the text
has been copied, pasted, re-saved or emailed around.
"""

from __future__ import annotations

import re
import zlib
from typing import List

ALPHABET = ("\u200b", "\u200c", "\u200d", "\u2060")  # ZWSP, ZWNJ, ZWJ, WORD JOINER
START = "\u2063\u2062"  # invisible separator + invisible times
END = "\u2062\u2063"
_DECODE = {c: i for i, c in enumerate(ALPHABET)}
_PATTERN = re.compile(re.escape(START) + "([" + "".join(ALPHABET) + "]+)" + re.escape(END))


def encode(data: bytes) -> str:
    """bytes -> invisible string. A CRC-16-ish check (low 2 bytes of CRC32) guards against damage."""
    framed = data + (zlib.crc32(data) & 0xFFFF).to_bytes(2, "big")
    chars = []
    for byte in framed:
        for shift in (6, 4, 2, 0):
            chars.append(ALPHABET[(byte >> shift) & 3])
    return START + "".join(chars) + END


def _decode_body(body: str) -> bytes | None:
    if len(body) % 4:
        return None
    out = bytearray()
    for i in range(0, len(body), 4):
        value = 0
        for ch in body[i:i + 4]:
            value = (value << 2) | _DECODE[ch]
        out.append(value)
    data, crc = bytes(out[:-2]), bytes(out[-2:])
    if len(out) < 3 or (zlib.crc32(data) & 0xFFFF).to_bytes(2, "big") != crc:
        return None
    return data


def find_all(text: str) -> List[bytes]:
    """Return every intact payload hidden in ``text``."""
    found = []
    for match in _PATTERN.finditer(text):
        data = _decode_body(match.group(1))
        if data is not None:
            found.append(data)
    return found


def strip(text: str) -> str:
    """Remove VeilMark marks (used before re-watermarking).

    Only complete START...END sequences are removed, so legitimate zero-width
    characters (e.g. ZWNJ/ZWJ in Arabic, Persian or emoji text) are left alone.
    """
    return _PATTERN.sub("", text)


def contains_any(text: str) -> bool:
    return bool(_PATTERN.search(text))
