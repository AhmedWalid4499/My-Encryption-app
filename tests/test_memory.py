"""VeilMark must never 'forget': team keys, settings and old watermarks survive updates and accidents."""
import json
import os

import pytest

from samples import make_docx, make_pptx
from veilmark.registry import Ledger
from veilmark.service import embed_watermark, trace_file
from veilmark.settings import Settings, _new_key, keyring_load


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILMARK_HOME", str(tmp_path / "home"))
    return tmp_path


def test_damaged_settings_never_replace_the_key(home):
    s = Settings.load()
    s.owner_name = "Ahmed"
    s.save()
    key = s.team_key
    Settings.path().write_text("{ this is not json", encoding="utf-8")  # damaged
    again = Settings.load()
    assert again.team_key == key and again.owner_name == "Ahmed"      # restored from the backup copy
    assert list(Settings.path().parent.glob("settings.damaged-*.json"))  # damaged file kept aside


def test_settings_and_backup_lost_but_keyring_keeps_key(home):
    key = Settings.load().team_key
    Settings.path().unlink()
    Settings.backup_path().unlink()
    assert Settings.load().team_key == key


def test_changing_key_keeps_old_watermarks_readable(home):
    s = Settings.load()
    src = home / "deck.pptx"
    make_pptx(src)
    old_copy = embed_watermark(src, message="Made with the first key", settings=s, ledger=Ledger()).output
    s.set_team_key(_new_key(), "generated")
    assert len(keyring_load()) == 2
    rep = trace_file(old_copy, settings=Settings.load())
    assert rep.verdict == "authentic" and rep.message == "Made with the first key"
    # re-watermarking that old copy continues its history under the new key
    s = Settings.load()
    newer = embed_watermark(old_copy, message="Second", settings=s, ledger=Ledger()).output
    rep = trace_file(newer, settings=s)
    assert [c.message for c in rep.chain] == ["Made with the first key", "Second"]


def test_settings_from_older_version_load(home):
    """settings.json written by 1.1.0 (no last_message etc.) keeps its key and values."""
    Settings.path().parent.mkdir(parents=True, exist_ok=True)
    old = {"owner_name": "Ahmed", "organization": "BookBeans", "team_key": _new_key(), "output_folder": "",
           "filename_pattern": "{stem} - for {recipient}{ext}", "aes_armour": True, "visible_footer": True,
           "footer_template": "x", "check_updates": True, "last_update_check": 0.0,
           "layers": {"properties": True}, "some_future_setting": 1}
    Settings.path().write_text(json.dumps(old), encoding="utf-8")
    s = Settings.load()
    assert s.team_key == old["team_key"] and s.owner_name == "Ahmed" and s.visible_footer
    assert s.layers["images"] is True  # defaults filled in for missing layers


def test_last_watermark_text_is_remembered(home):
    s = Settings.load()
    src = home / "d.docx"
    make_docx(src)
    embed_watermark(src, message="© 2026 BookBeans", settings=s, ledger=Ledger())
    assert Settings.load().last_message == "© 2026 BookBeans"


def test_settings_files_are_written_atomically(home):
    s = Settings.load()
    s.save()
    names = sorted(p.name for p in Settings.path().parent.iterdir())
    assert names == ["keyring.json", "settings.backup.json", "settings.json"]
    assert not [n for n in os.listdir(Settings.path().parent) if n.endswith(".tmp")]
