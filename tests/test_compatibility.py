"""Files made by every released VeilMark version must keep extracting / decrypting forever.

The files in tests/fixtures were produced by the *released* code of each version (checked out from its
git tag), with a fixed test team key. Add a new pair here whenever a version changes a file format.
"""
from pathlib import Path

import pytest

from veilmark.crypto import decrypt_bytes
from veilmark.registry import Ledger
from veilmark.service import trace_file
from veilmark.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures"
TEAM_KEY = "OZSWS3DNMFZGWLLGNF4HI5LSMUWXIZLBNUWWWZLZFUYDAMBR"

EXPECTED = {
    "v1_1_0": "Watermark typed in 1.1",       # 1.1.0 had only "Recipient"
    "v1_2_1": "Watermark from 1.2.1",
}


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILMARK_HOME", str(tmp_path))  # fresh PC: no local history to help
    s = Settings.load()
    s.team_key = TEAM_KEY
    return s


@pytest.mark.parametrize("version", sorted(EXPECTED))
@pytest.mark.parametrize("ext", ["pptx", "docx", "xlsx"])
def test_old_watermarks_still_extract(settings, version, ext):
    rep = trace_file(FIXTURES / f"{version}.{ext}", settings=settings, ledger=Ledger())
    assert rep.verdict == "authentic"
    assert rep.message == EXPECTED[version]
    assert rep.owner == "Ahmed Walid" and rep.organization == "BookBeans"


@pytest.mark.parametrize("version", sorted(EXPECTED))
def test_old_encrypted_files_still_decrypt(version):
    data, meta = decrypt_bytes((FIXTURES / f"{version}.vmk").read_bytes(), "fixture-pass")
    assert data == b"secret made by " + version[1:].replace("_", ".").encode() and meta["name"] == "secret.txt"


def test_old_key_still_works_after_switching_team_key(settings):
    from veilmark.settings import _new_key

    settings.save()                           # puts the fixture key on this PC's keyring
    settings.set_team_key(_new_key(), "new")  # e.g. user clicked "Generate new key"
    rep = trace_file(FIXTURES / "v1_2_1.pptx", settings=settings, ledger=Ledger())
    assert rep.verdict == "authentic" and rep.message == "Watermark from 1.2.1"
