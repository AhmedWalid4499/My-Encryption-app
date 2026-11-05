import sqlite3
import zipfile

import pytest

from samples import make_docx, make_pptx, make_xlsx, png_bytes
from veilmark.registry import Ledger
from veilmark.service import embed_watermark, protect_file, trace_file, trace_pasted_text
from veilmark.settings import Settings
from veilmark.watermark import zerowidth
from veilmark.watermark.payload import Record

MAKERS = {"docx": make_docx, "pptx": make_pptx, "xlsx": make_xlsx}
TEXT = "© 2026 BookBeans – Confidential, do not distribute"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILMARK_HOME", str(tmp_path / "home"))
    s = Settings.load()
    s.owner_name, s.organization = "Ahmed", "BookBeans"
    return s, Ledger(), tmp_path


@pytest.mark.parametrize("ext", ["docx", "pptx", "xlsx"])
def test_embed_text_and_extract_it(env, ext):
    s, ledger, tmp = env
    src = tmp / f"plan.{ext}"
    MAKERS[ext](src)
    res = embed_watermark(src, message=TEXT, settings=s, ledger=ledger)
    assert res.output.name == f"plan - watermarked.{ext}"
    rep = trace_file(res.output, settings=s, ledger=ledger)
    assert rep.verdict == "authentic" and rep.message == TEXT
    assert rep.headline == "Watermark found"
    assert src.read_bytes() != res.output.read_bytes()  # original untouched, copy written


def test_text_and_recipient_together(env):
    s, ledger, tmp = env
    src = tmp / "deck.pptx"
    make_pptx(src)
    res = embed_watermark(src, "Sara Ahmed", message=TEXT, settings=s, ledger=ledger)
    assert res.output.name == "deck - for Sara Ahmed.pptx"
    rep = trace_file(res.output, settings=s, ledger=ledger)
    assert rep.message == TEXT and rep.likely_source.recipient == "Sara Ahmed"


def test_rewatermark_keeps_history_of_texts(env):
    s, ledger, tmp = env
    src = tmp / "doc.docx"
    make_docx(src)
    a = embed_watermark(src, message="First text", settings=s, ledger=ledger)
    b = embed_watermark(a.output, message="Second text", settings=s, ledger=ledger)
    assert b.reshared and b.output.stem.startswith("doc - watermarked")
    assert " - watermarked - watermarked" not in b.output.name
    rep = trace_file(b.output, settings=s, ledger=ledger)
    assert rep.message == "Second text"
    assert [c.message for c in rep.chain] == ["First text", "Second text"]


def test_text_needed(env):
    s, ledger, tmp = env
    src = tmp / "doc.docx"
    make_docx(src)
    with pytest.raises(ValueError, match="watermark text"):
        embed_watermark(src, message="   ", settings=s, ledger=ledger)


def test_picture_and_pasted_text(env):
    s, ledger, tmp = env
    pic = tmp / "logo.png"
    pic.write_bytes(png_bytes(160, 160))
    out = embed_watermark(pic, message=TEXT, settings=s, ledger=ledger).output
    assert trace_file(out, settings=s, ledger=ledger).message == TEXT
    # invisible text marks only carry an ID: the text comes back from the local history
    doc = tmp / "d.docx"
    make_docx(doc, with_image=False)
    out = embed_watermark(doc, message=TEXT, settings=s, ledger=ledger).output
    import docx

    copied = "\n".join(p.text for p in docx.Document(out).paragraphs)
    assert trace_pasted_text(copied, settings=s, ledger=ledger).message == TEXT


@pytest.mark.parametrize("ext", ["docx", "pptx", "xlsx"])
def test_visible_footer_shows_the_watermark_text(env, ext):
    s, ledger, tmp = env
    s.visible_footer = True
    src = tmp / f"f.{ext}"
    MAKERS[ext](src)
    a = embed_watermark(src, message="Owned by BookBeans", settings=s, ledger=ledger).output
    b = embed_watermark(a, message="Second owner text", settings=s, ledger=ledger).output
    with zipfile.ZipFile(b) as z:
        xml = "".join(zerowidth.strip(z.read(n).decode("utf-8", "ignore")) for n in z.namelist()
                      if n.endswith(".xml"))
    assert "Second owner text" in xml
    # the old footer was replaced, not stacked (the old text may survive only inside encrypted data)
    if ext == "docx":
        import docx

        footer = " ".join(p.text for p in docx.Document(b).sections[0].footer.paragraphs)
        assert "Owned by BookBeans" not in footer
    elif ext == "pptx":
        from pptx import Presentation

        for slide in Presentation(b).slides:
            texts = [sh.text_frame.text for sh in slide.shapes if sh.name == "VeilMark Footer"]
            assert len(texts) == 1 and "Second owner text" in texts[0]
    else:
        import openpyxl

        center = openpyxl.load_workbook(b)["Budget"].oddFooter.center.text
        assert "Second owner text" in center and "Owned by" not in center


def test_old_ledger_is_upgraded(tmp_path):
    db = tmp_path / "ledger.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE issues (hop_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, parent_hop TEXT, "
                "recipient TEXT NOT NULL, note TEXT, owner TEXT, issued_by TEXT, source_file TEXT, "
                "output_file TEXT, timestamp TEXT)")
    con.execute("INSERT INTO issues VALUES ('aa','bb',NULL,'Sara','','Ahmed','Ahmed','a.docx','b.docx','t')")
    con.commit()
    con.close()
    ledger = Ledger(db)
    old = ledger.get("aa")
    assert old.recipient == "Sara" and old.message == ""
    assert len(ledger.search("Sara")) == 1


def test_records_from_newer_versions_still_open():
    rec = Record.new("Ahmed", message="hello")
    rec.add_hop("", message="hello")
    import json

    data = json.loads(rec.to_json())
    data["future_field"] = 1
    data["chain"][0]["another_future_field"] = 2
    back = Record.from_json(json.dumps(data).encode())
    assert back.latest_message == "hello"


def test_old_positional_api_still_works(env):
    s, ledger, tmp = env
    src = tmp / "x.docx"
    make_docx(src)
    out = protect_file(src, "Alice", "note", settings=s, ledger=ledger).output
    rep = trace_file(out, settings=s, ledger=ledger)
    assert rep.likely_source.recipient == "Alice" and rep.headline == "Watermarked copy given to Alice"


def test_file_from_older_version_shows_recipient_text(env):
    """1.1.0 had no text box: what people typed as 'Recipient' is shown as the watermark text."""
    s, ledger, tmp = env
    src = tmp / "deck.pptx"
    make_pptx(src)
    old = protect_file(src, "Confidential BookBeans 2026", settings=s, ledger=ledger).output
    rep = trace_file(old, settings=s, ledger=ledger)
    assert rep.message == "Confidential BookBeans 2026" and rep.legacy_text
    new = embed_watermark(src, message=TEXT, settings=s, ledger=ledger).output
    rep = trace_file(new, settings=s, ledger=ledger)
    assert rep.message == TEXT and not rep.legacy_text
