"""Watermark payloads.

Two forms are embedded:

* **Token** (16 bytes) - tiny, authenticated, survives almost anywhere (invisible
  characters in text, image pixels). ``magic | doc_id(6) | hop_id(4) | hmac(5)``.
  One token is minted every time the document is handed to a new recipient, so a
  copy carries the whole *chain* of tokens (original -> recipient 1 -> recipient 2...).

* **Record** - the full, AES-256-GCM encrypted description: owner, organisation,
  title, and the chain of custody with recipient names, notes and timestamps.
  This is the Python version of what the thesis did with ``Encrypt[key, Msg]``
  before hiding the bits in the carrier.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import json
import os
import zlib
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TOKEN_MAGIC = 0xA7
TOKEN_LEN = 16
MAX_CHAIN = 8  # tokens kept in the compact (text/image) layers


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Token:
    doc_id: str   # 12 hex chars
    hop_id: str   # 8 hex chars
    authentic: bool = True

    def short(self) -> str:
        return f"{self.doc_id}-{self.hop_id}"


def _token_mac(key: bytes, body: bytes) -> bytes:
    return hmac.new(key, b"veilmark-token" + body, hashlib.sha256).digest()[:5]


def make_token(key: bytes, doc_id: str, hop_id: str) -> bytes:
    body = bytes([TOKEN_MAGIC]) + bytes.fromhex(doc_id) + bytes.fromhex(hop_id)
    return body + _token_mac(key, body)


def parse_token(raw: bytes, key: Optional[bytes]) -> Optional[Token]:
    if len(raw) != TOKEN_LEN or raw[0] != TOKEN_MAGIC:
        return None
    body, mac = raw[:11], raw[11:]
    authentic = key is not None and hmac.compare_digest(mac, _token_mac(key, body))
    return Token(body[1:7].hex(), body[7:11].hex(), authentic)


def split_tokens(blob: bytes, key: Optional[bytes]) -> List[Token]:
    out = []
    for i in range(0, len(blob) - TOKEN_LEN + 1, TOKEN_LEN):
        tok = parse_token(blob[i:i + TOKEN_LEN], key)
        if tok:
            out.append(tok)
    return out


# --------------------------------------------------------------------------- #
# Records (full chain of custody)
# --------------------------------------------------------------------------- #
@dataclass
class Hop:
    hop_id: str
    recipient: str
    note: str = ""
    issued_by: str = ""
    timestamp: str = field(default_factory=now_iso)
    message: str = ""  # the watermark text the user typed for this copy


@dataclass
class Record:
    doc_id: str
    owner: str
    organization: str = ""
    title: str = ""
    created: str = field(default_factory=now_iso)
    chain: List[Hop] = field(default_factory=list)
    version: int = 1
    message: str = ""  # watermark text of the first embed

    @staticmethod
    def new(owner: str, organization: str = "", title: str = "", message: str = "") -> "Record":
        return Record(doc_id=os.urandom(6).hex(), owner=owner, organization=organization, title=title,
                      message=message)

    @property
    def latest_message(self) -> str:
        for hop in reversed(self.chain):
            if hop.message:
                return hop.message
        return self.message

    def add_hop(self, recipient: str, note: str = "", issued_by: str = "", message: str = "") -> Hop:
        hop = Hop(hop_id=os.urandom(4).hex(), recipient=recipient, note=note, issued_by=issued_by,
                  message=message)
        self.chain.append(hop)
        return hop

    def token_chain(self, key: bytes) -> bytes:
        hops = self.chain[-MAX_CHAIN:]
        return b"".join(make_token(key, self.doc_id, h.hop_id) for h in hops)

    # -- serialisation ------------------------------------------------------ #
    def to_json(self) -> bytes:
        return json.dumps(asdict(self), separators=(",", ":"), ensure_ascii=False).encode()

    @staticmethod
    def from_json(raw: bytes) -> "Record":
        data = json.loads(raw)
        hop_fields, rec_fields = Hop.__dataclass_fields__, Record.__dataclass_fields__
        # ignore unknown keys so records written by newer versions still open
        data["chain"] = [Hop(**{k: v for k, v in h.items() if k in hop_fields}) for h in data.get("chain", [])]
        return Record(**{k: v for k, v in data.items() if k in rec_fields})

    def seal(self, key: bytes) -> bytes:
        """compress + AES-256-GCM. Output: b'VR1' | nonce(12) | ciphertext+tag."""
        nonce = os.urandom(12)
        return b"VR1" + nonce + AESGCM(key).encrypt(nonce, zlib.compress(self.to_json(), 9), b"VR1")

    def seal_b64(self, key: bytes) -> str:
        return base64.b64encode(self.seal(key)).decode("ascii")


def open_record(blob: bytes, key: bytes) -> Optional[Record]:
    if not blob.startswith(b"VR1") or len(blob) < 3 + 12 + 16:
        return None
    try:
        raw = AESGCM(key).decrypt(blob[3:15], blob[15:], b"VR1")
        return Record.from_json(zlib.decompress(raw))
    except (InvalidTag, ValueError, zlib.error, TypeError, KeyError):
        return None


def open_record_b64(text: str, key: bytes) -> Optional[Record]:
    try:
        return open_record(base64.b64decode(text.strip(), validate=True), key)
    except (ValueError, TypeError):
        return None
