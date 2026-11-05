import os

import numpy as np
import pytest

from veilmark.crypto import cipher
from veilmark.crypto.chaos import HyperChen4D, Hyper5D, MersenneStream
from veilmark.crypto.sboxes import INV_SBOXES, SBOXES


def test_sboxes_are_permutations_and_inverses():
    for s, inv in zip(SBOXES, INV_SBOXES):
        assert sorted(s.tolist()) == list(range(256))
        assert np.array_equal(inv[s], np.arange(256))


def test_state_machine_matches_thesis_and_is_involution():
    for a in range(0, 256, 3):
        for b in range(0, 256, 5):
            literal = cipher.state_machine_byte(a, b)
            vec = cipher.state_machine(np.array([a], np.uint8), np.array([b], np.uint8))[0]
            assert literal == vec
            assert cipher.state_machine_byte(literal, b) == a


@pytest.mark.parametrize("cls", [HyperChen4D, Hyper5D, MersenneStream])
def test_keystreams_deterministic_and_key_sensitive(cls):
    a = cls(b"key-one").take(5000)
    b = cls(b"key-one").take(5000)
    c = cls(b"key-onf").take(5000)
    assert np.array_equal(a, b)
    assert np.mean(a == c) < 0.02  # ~1/256 expected


def test_keystream_take_is_streaming_consistent():
    s1 = HyperChen4D(b"k")
    parts = np.concatenate([s1.take(7), s1.take(1000), s1.take(3)])
    assert np.array_equal(parts, HyperChen4D(b"k").take(1010))


def test_chaotic_keystream_known_answer():
    """Fixed vectors: the same keystream must come out on every OS / CPU, or files
    encrypted on one PC could not be decrypted on another (checked in Windows CI)."""
    assert HyperChen4D(b"veilmark").take(16).tobytes().hex() == "5e79ec5d7aa069bd57d78372810ec690"
    assert Hyper5D(b"veilmark").take(16).tobytes().hex() == "f2a6ed74fce39c8ced10e14d3e921794"
    assert MersenneStream(b"veilmark").take(16).tobytes().hex() == "f3a8bcb4c0dd7f396e4cebd0328e772a"


KAT_BLOBS = [
    # chaotic cascade + HMAC (no AES)
    "564d4b31000c34b6ddfc4c7521d88ec7728af39ff2fafe1126e73d76dca137258088ecb52d82ef03aa005fb64ac6399167757d4510"
    "ff696a60ee1e4fb055c409a34d7f438941a9db569e12487746ed64edfb0de7c7ed9c575c64dcef62f0b1ddfbd9d72948bc179c8120"
    "9686ecbf",
    # chaotic cascade + AES-256-GCM armour
    "564d4b31010c0a1625ba2492ebdf17ca5234129a59e8b1603d3ff825f31d74adf4181309751282edc69813530c2aa035eac23172f6"
    "9c1aac64f8eca11cd0f66596ca7c35a1e152fd9ae3fba3a6831da22c1e3fc30e64735176fa12aaee75",
]


@pytest.mark.parametrize("blob", KAT_BLOBS)
def test_decrypts_file_made_on_another_machine(blob):
    data, meta = cipher.decrypt_bytes(bytes.fromhex(blob), "kat-password")
    assert data == b"Hello from the thesis!" and meta["name"] == "kat.txt"


@pytest.mark.parametrize("armour", [True, False])
@pytest.mark.parametrize("size", [0, 1, 1000, 300_001])
def test_roundtrip(armour, size):
    data = os.urandom(size)
    blob = cipher.encrypt_bytes(data, "correct horse", aes_armour=armour, metadata={"name": "x.pptx"},
                                scrypt_log2n=12)
    out, meta = cipher.decrypt_bytes(blob, "correct horse")
    assert out == data and meta["name"] == "x.pptx"
    with pytest.raises(cipher.DecryptionError):
        cipher.decrypt_bytes(blob, "wrong horse")


def test_ciphertext_differs_each_time_and_hides_plaintext():
    data = b"A" * 50_000
    b1 = cipher.encrypt_bytes(data, "pw", aes_armour=False, scrypt_log2n=12)
    b2 = cipher.encrypt_bytes(data, "pw", aes_armour=False, scrypt_log2n=12)
    assert b1 != b2
    body = np.frombuffer(b1[34:-32], np.uint8)
    counts = np.bincount(body, minlength=256)
    assert counts.max() < 3 * counts.mean()  # constant input -> near-uniform output


def test_tamper_detected():
    blob = bytearray(cipher.encrypt_bytes(b"hello world" * 100, "pw", aes_armour=False, scrypt_log2n=12))
    blob[60] ^= 1
    with pytest.raises(cipher.DecryptionError):
        cipher.decrypt_bytes(bytes(blob), "pw")


def test_file_roundtrip(tmp_path):
    src = tmp_path / "deck.pptx"
    src.write_bytes(os.urandom(4096))
    enc = cipher.encrypt_file(src, "pw")
    assert enc.name == "deck.pptx.vmk" and cipher.is_encrypted_file(enc)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    dec = cipher.decrypt_file(enc, "pw", out_dir)
    assert dec.name == "deck.pptx" and dec.read_bytes() == src.read_bytes()


def test_not_a_vmk():
    with pytest.raises(cipher.DecryptionError):
        cipher.decrypt_bytes(b"PK\x03\x04 nope", "pw")
