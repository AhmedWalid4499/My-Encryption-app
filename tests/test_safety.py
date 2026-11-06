"""Embedding and decrypting must never produce a damaged or wrong file."""
import io
import zipfile
from collections import Counter

import pytest
from lxml import etree

from samples import make_pptx
from veilmark import fileio
from veilmark.crypto import cipher
from veilmark.registry import Ledger
from veilmark.service import embed_watermark, trace_file
from veilmark.settings import Settings
from veilmark.watermark import engine

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@pytest.fixture()
def s(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILMARK_HOME", str(tmp_path / "home"))
    st = Settings.load()
    st.owner_name = "Ahmed"
    return st


def test_broken_result_is_never_saved(s, tmp_path, monkeypatch):
    src = tmp_path / "deck.pptx"
    make_pptx(src)
    monkeypatch.setattr("veilmark.service.protect_bytes",
                        lambda data, name, rec, key, opts: (b"PK\x03\x04 not a real zip", engine.EmbedReport()))
    with pytest.raises(engine.EmbedCheckError, match="original file is untouched"):
        embed_watermark(src, message="x", settings=s, ledger=Ledger())
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["deck.pptx"]


def test_password_or_label_protected_office_file(s, tmp_path):
    fake = engine.OLE_MAGIC + b"\x00" * 100 + "EncryptedPackage".encode("utf-16-le") + b"\x00" * 100
    src = tmp_path / "labelled.pptx"
    src.write_bytes(fake)
    with pytest.raises(ValueError, match="protected"):
        embed_watermark(src, message="x", settings=s, ledger=Ledger())
    rep = trace_file(src, settings=s, ledger=Ledger())
    assert rep.verdict == "error" and "sensitivity label" in rep.headline


def test_word_footer_multi_section_has_no_duplicate_bookmarks(s, tmp_path):
    import docx
    from docx.enum.section import WD_SECTION

    d = docx.Document()
    d.add_paragraph("Section one")
    d.add_section(WD_SECTION.NEW_PAGE)
    d.add_paragraph("Section two")
    d.sections[1].footer.is_linked_to_previous = False
    d.sections[1].footer.paragraphs[0].text = "Author footer"
    table = d.add_table(rows=1, cols=1)
    table.cell(0, 0).paragraphs[0].text = "CONFIDENTIAL – prepared for the board"  # must never be removed
    src = tmp_path / "multi.docx"
    d.save(src)
    s.visible_footer = True
    a = embed_watermark(src, message="Owned by BookBeans", settings=s, ledger=Ledger()).output
    b = embed_watermark(a, message="Second text", settings=s, ledger=Ledger()).output
    with zipfile.ZipFile(b) as z:
        ids, names = Counter(), Counter()
        for n in z.namelist():
            if n.startswith("word/") and n.endswith(".xml"):
                root = etree.fromstring(z.read(n))
                for bm in root.iter(W + "bookmarkStart"):
                    ids[bm.get(W + "id")] += 1
                    names[bm.get(W + "name")] += 1
                for tc in root.iter(W + "tc"):
                    assert tc.findall(W + "p"), "table cell left without a paragraph"
    assert all(c == 1 for c in ids.values()) and all(c == 1 for c in names.values())
    doc = docx.Document(b)
    from veilmark.watermark import zerowidth

    assert zerowidth.strip(doc.tables[0].cell(0, 0).text) == "CONFIDENTIAL – prepared for the board"
    footers = [zerowidth.strip(" ".join(p.text for p in sec.footer.paragraphs)) for sec in doc.sections]
    assert all("Second text" in f and "Owned by" not in f for f in footers)
    assert "Author footer" in footers[1]


def test_powerpoint_field_text_untouched(s, tmp_path):
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Title"
    tb = slide.shapes.add_textbox(0, 0, 100, 100)
    p = tb.text_frame.paragraphs[0]._p
    fld = etree.SubElement(p, "{http://schemas.openxmlformats.org/drawingml/2006/main}fld",
                           id="{5C1F2B6A-0000-4000-8000-000000000001}", type="slidenum")
    etree.SubElement(fld, "{http://schemas.openxmlformats.org/drawingml/2006/main}t").text = "1"
    src = tmp_path / "fld.pptx"
    prs.save(src)
    out = embed_watermark(src, message="x", settings=s, ledger=Ledger()).output
    with zipfile.ZipFile(out) as z:
        root = etree.fromstring(z.read("ppt/slides/slide1.xml"))
    fld_texts = [t.text for t in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t")
                 if t.getparent().tag.endswith("}fld")]
    assert fld_texts == ["1"]


def test_decrypt_refuses_wrong_content(tmp_path):
    blob = cipher.encrypt_bytes(b"real content", "pw", metadata={"name": "a.txt", "size": 12, "sha256": "0" * 64},
                                scrypt_log2n=12)
    src = tmp_path / "a.txt.vmk"
    src.write_bytes(blob)
    with pytest.raises(cipher.DecryptionError, match="doesn't match"):
        cipher.decrypt_file(src, "pw", tmp_path / "out" if (tmp_path / "out").mkdir() is None else None)
    assert not list((tmp_path / "out").iterdir())


def test_encrypt_decrypt_files_are_verified_and_identical(tmp_path):
    src = tmp_path / "deck.pptx"
    make_pptx(src)
    enc = cipher.encrypt_file(src, "a good password")
    out = tmp_path / "back"
    out.mkdir()
    dec = cipher.decrypt_file(enc, "a good password", out)
    assert dec.read_bytes() == src.read_bytes() and dec.name == "deck.pptx"
    with zipfile.ZipFile(io.BytesIO(dec.read_bytes())) as z:
        assert z.testzip() is None


def test_saved_file_is_read_back(tmp_path, monkeypatch):
    target = tmp_path / "x.bin"
    real = fileio._verify_on_disk

    def tamper(path, data):  # a sync tool changes the file right after it is written
        path.write_bytes(b"changed")
        real(path, data)
    monkeypatch.setattr(fileio, "_verify_on_disk", tamper)
    with pytest.raises(fileio.FileAccessError, match="wasn't saved correctly"):
        fileio.write_bytes(target, b"original")
    assert not target.exists()


def test_hidden_watermark_never_looks_like_our_footer_tag():
    """Regression: the author's own footer (carrying random invisible marks) must never be mistaken for ours."""
    import os

    from veilmark.watermark import footer, zerowidth

    for _ in range(2000):
        p = etree.Element(W + "p")
        r = etree.SubElement(p, W + "r")
        etree.SubElement(r, W + "t").text = "Author footer" + zerowidth.encode(os.urandom(32))
        assert not footer._is_our_word_paragraph(p)
