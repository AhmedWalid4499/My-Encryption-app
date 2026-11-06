"""Invisible text marks must stay invisible in Word / PowerPoint / Excel on Windows *and* Mac.

Up to 1.5.1 the marks were framed with U+2063 / U+2062 (invisible separator / invisible times). Word for Mac draws
those with Cambria Math as a visible comma and a boxed X, so a watermarked CV showed "Name‚⊠⊠‚".
"""
import shutil
import zipfile
from pathlib import Path

import pytest

from veilmark.registry import Ledger
from veilmark.service import protect_file, trace_file
from veilmark.watermark import zerowidth

from test_compatibility import FIXTURES, settings  # noqa: F401 - shared fixture

# characters Office on Windows and Mac draws as nothing at all
SAFE = set(zerowidth.ALPHABET) | {"﻿"}
VISIBLE_ON_MAC = ("⁡", "⁢", "⁣", "⁤")  # math "invisible" operators: Cambria Math draws them


def _office_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        return "".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))


def test_new_marks_use_only_truly_invisible_characters():
    mark = zerowidth.encode(b"\x00\xff" * 20 + b"hello")
    assert set(mark) <= SAFE
    assert zerowidth.find_all("Ahmed" + mark + " Walid") == [b"\x00\xff" * 20 + b"hello"]


def test_old_marks_are_still_read_and_stripped():
    body = zerowidth.encode(b"from 1.5.1")[len(zerowidth.START):-len(zerowidth.END)]
    legacy = zerowidth.LEGACY_START + body + zerowidth.LEGACY_END
    assert zerowidth.find_all("CV" + legacy) == [b"from 1.5.1"]
    assert zerowidth.strip("Bourgy" + legacy) == "Bourgy"


@pytest.mark.parametrize("ext", ["docx", "pptx"])
def test_new_watermark_has_no_mac_visible_characters(settings, tmp_path, ext):  # noqa: F811
    from samples import make_docx, make_pptx

    src = tmp_path / f"cv.{ext}"
    (make_docx if ext == "docx" else make_pptx)(str(src))
    out = protect_file(src, "Sara", message="Confidential", settings=settings, ledger=Ledger()).output
    text = _office_text(Path(out))
    assert not any(c in text for c in VISIBLE_ON_MAC)
    assert trace_file(out, settings=settings, ledger=Ledger()).message == "Confidential"


@pytest.mark.parametrize("ext", ["docx", "pptx"])
def test_rewatermarking_an_old_file_removes_the_boxes(settings, tmp_path, ext):  # noqa: F811
    old = tmp_path / f"old.{ext}"
    shutil.copy(FIXTURES / f"v1_2_1.{ext}", old)
    assert "⁣" in _office_text(old)  # the fixture really has the old, visible-on-Mac frame
    out = protect_file(old, "Omar", message="Re-marked", settings=settings, ledger=Ledger()).output
    assert not any(c in _office_text(Path(out)) for c in VISIBLE_ON_MAC)
    rep = trace_file(out, settings=settings, ledger=Ledger())
    assert rep.message == "Re-marked" and len(rep.chain) >= 2  # history from the old watermark is kept
