import io
import shutil
import subprocess
import zipfile

import pytest
from PIL import Image

from samples import make_docx, make_pptx, make_xlsx, png_bytes
from veilmark.registry import Ledger
from veilmark.service import protect_file, trace_file, trace_pasted_text
from veilmark.settings import Settings
from veilmark.watermark import zerowidth
from veilmark.watermark.engine import (LAYER_CUSTOMXML, LAYER_IMAGES, LAYER_PROPS, LAYER_SHEET,
                                       LAYER_TEXT)

MAKERS = {"docx": make_docx, "pptx": make_pptx, "xlsx": make_xlsx}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILMARK_HOME", str(tmp_path / "home"))
    s = Settings.load()
    s.owner_name, s.organization = "Ahmed", "BookBeans"
    return s, Ledger(), tmp_path


def _rewrite_zip(path, drop=lambda n: False, transform=lambda n, d: d):
    src = path.read_bytes()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(src)) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            if drop(info.filename):
                continue
            zout.writestr(info.filename, transform(info.filename, zin.read(info.filename)))
    path.write_bytes(out.getvalue())


@pytest.mark.parametrize("ext", ["docx", "pptx", "xlsx"])
def test_protect_and_trace(env, ext):
    s, ledger, tmp = env
    src = tmp / f"plan.{ext}"
    MAKERS[ext](src)
    res = protect_file(src, "Alice Smith", "board pack", settings=s, ledger=ledger)
    assert res.output.name == f"plan - for Alice Smith.{ext}"
    rep = trace_file(res.output, settings=s, ledger=ledger)
    assert rep.verdict == "authentic"
    assert rep.owner == "Ahmed" and rep.organization == "BookBeans"
    assert [c.recipient for c in rep.chain] == ["Alice Smith"]
    found = {name for name, ok, _ in rep.layer_status if ok}
    assert {LAYER_PROPS, LAYER_CUSTOMXML, LAYER_IMAGES} <= found
    assert (LAYER_SHEET if ext == "xlsx" else LAYER_TEXT) in found


@pytest.mark.parametrize("ext", ["docx", "pptx", "xlsx"])
def test_output_still_opens_in_python_office_libs(env, ext):
    s, ledger, tmp = env
    src = tmp / f"plan.{ext}"
    MAKERS[ext](src)
    out = protect_file(src, "Bob", settings=s, ledger=ledger).output
    if ext == "docx":
        import docx

        text = "\n".join(p.text for p in docx.Document(out).paragraphs)
        assert "Paragraph 3" in text
    elif ext == "pptx":
        from pptx import Presentation

        assert len(Presentation(out).slides) == 3
    else:
        import openpyxl

        wb = openpyxl.load_workbook(out)
        assert wb["Budget"]["B3"].value == 100
        assert wb["_vm"].sheet_state == "veryHidden"


def test_multi_hop_chain(env):
    s, ledger, tmp = env
    src = tmp / "deck.pptx"
    make_pptx(src)
    a = protect_file(src, "Alice", settings=s, ledger=ledger)
    b = protect_file(a.output, "Bob", settings=s, ledger=ledger)
    c = protect_file(b.output, "Carol", settings=s, ledger=ledger)
    assert b.reshared and c.reshared
    assert a.record.doc_id == b.record.doc_id == c.record.doc_id
    assert c.output.name == "deck - for Carol.pptx"
    rep = trace_file(c.output, settings=s, ledger=ledger)
    assert [x.recipient for x in rep.chain] == ["Alice", "Bob", "Carol"]
    assert rep.likely_source.recipient == "Carol"
    # Bob's copy still points at Bob, not Carol
    assert trace_file(b.output, settings=s, ledger=ledger).likely_source.recipient == "Bob"
    # the ledger links each copy to the one it was made from
    issues = ledger.for_document(a.record.doc_id)
    assert [i.parent_hop for i in issues] == [None, a.record.chain[-1].hop_id, b.record.chain[-1].hop_id]


@pytest.mark.parametrize("ext", ["docx", "pptx"])
def test_survives_document_inspector(env, ext):
    """Inspect Document removes custom properties and custom XML; text + image layers must remain."""
    s, ledger, tmp = env
    src = tmp / f"x.{ext}"
    MAKERS[ext](src)
    out = protect_file(src, "Dana", settings=s, ledger=ledger).output
    _rewrite_zip(out, drop=lambda n: n.startswith("customXml/") or n == "docProps/custom.xml")
    rep = trace_file(out, settings=s, ledger=ledger)
    assert rep.verdict == "authentic" and rep.likely_source.recipient == "Dana"
    found = {name for name, ok, _ in rep.layer_status if ok}
    assert LAYER_PROPS not in found and LAYER_TEXT in found


def test_text_only_with_ledger(env):
    """Only invisible text left (no pictures, no record) -> ledger names the recipient."""
    s, ledger, tmp = env
    src = tmp / "x.docx"
    make_docx(src, with_image=False)
    out = protect_file(src, "Eve", settings=s, ledger=ledger).output
    _rewrite_zip(out, drop=lambda n: n.startswith("customXml/") or n == "docProps/custom.xml")
    rep = trace_file(out, settings=s, ledger=ledger)
    assert rep.verdict == "authentic"
    assert rep.chain[-1].recipient == "Eve" and rep.chain[-1].source == "ledger"


def test_copied_slide_text_is_traceable(env):
    s, ledger, tmp = env
    src = tmp / "deck.pptx"
    make_pptx(src)
    out = protect_file(src, "Frank", settings=s, ledger=ledger).output
    from pptx import Presentation

    copied = "\n".join(sh.text_frame.text for sh in Presentation(out).slides[0].shapes if sh.has_text_frame)
    assert "Slide 1 title" in zerowidth.strip(copied)
    rep = trace_pasted_text(copied, settings=s, ledger=ledger)
    assert rep.verdict == "authentic" and rep.likely_source.recipient == "Frank"


def test_slide_copied_into_new_deck(env):
    """Simulate copying a slide (text + picture) into somebody else's presentation."""
    s, ledger, tmp = env
    src = tmp / "deck.pptx"
    make_pptx(src)
    out = protect_file(src, "Grace", settings=s, ledger=ledger).output
    with zipfile.ZipFile(out) as z:
        slide2 = z.read("ppt/slides/slide2.xml")
        media = {n: z.read(n) for n in z.namelist() if n.startswith("ppt/media/")}
    other = tmp / "other.pptx"
    make_pptx(other, with_image=False)

    def transform(name, data):
        return slide2 if name == "ppt/slides/slide1.xml" else data

    _rewrite_zip(other, transform=transform)
    with zipfile.ZipFile(other, "a") as z:
        for n, d in media.items():
            z.writestr(n, d)
    rep = trace_file(other, settings=s, ledger=ledger)
    assert rep.verdict == "authentic" and rep.likely_source.recipient == "Grace"


def test_wrong_team_key_reports_foreign(env, monkeypatch):
    s, ledger, tmp = env
    src = tmp / "x.docx"
    make_docx(src)
    out = protect_file(src, "Heidi", settings=s, ledger=ledger).output
    other = Settings()
    rep = trace_file(out, settings=other, ledger=ledger)
    assert rep.verdict == "foreign" and not rep.chain


def test_clean_file_reports_none(env):
    s, ledger, tmp = env
    src = tmp / "x.xlsx"
    make_xlsx(src)
    assert trace_file(src, settings=s, ledger=ledger).verdict == "none"


def test_png_protect_and_jpeg_destroys(env):
    s, ledger, tmp = env
    src = tmp / "logo.png"
    src.write_bytes(png_bytes(200, 200))
    out = protect_file(src, "Ivan", settings=s, ledger=ledger).output
    assert trace_file(out, settings=s, ledger=ledger).likely_source.recipient == "Ivan"
    # crop: repetition across the image means a part still carries the mark
    img = Image.open(out)
    img.crop((0, 0, 200, 120)).save(tmp / "crop.png")
    assert trace_file(tmp / "crop.png", settings=s, ledger=ledger).verdict == "authentic"
    img.convert("RGB").save(tmp / "lossy.jpg", quality=90)
    assert trace_file(tmp / "lossy.jpg", settings=s, ledger=ledger).verdict == "none"


def test_plain_text_file(env):
    s, ledger, tmp = env
    src = tmp / "notes.txt"
    src.write_text("Line one\n\nLine two is here\nمرحبا‌ بالعالم\n", encoding="utf-8")
    out = protect_file(src, "Judy", settings=s, ledger=ledger).output
    text = out.read_text(encoding="utf-8")
    assert "‌" in zerowidth.strip(text)  # legitimate ZWNJ preserved
    assert trace_file(out, settings=s, ledger=ledger).likely_source.recipient == "Judy"


def test_rewatermark_does_not_accumulate(env):
    s, ledger, tmp = env
    src = tmp / "x.docx"
    make_docx(src)
    a = protect_file(src, "A", settings=s, ledger=ledger).output
    b = protect_file(a, "B", settings=s, ledger=ledger).output
    with zipfile.ZipFile(a) as z:
        marks_a = len(zerowidth.find_all(z.read("word/document.xml").decode()))
    with zipfile.ZipFile(b) as z:
        doc = z.read("word/document.xml").decode()
        props = z.read("docProps/custom.xml").decode()
    assert marks_a > 0 and len(zerowidth.find_all(doc)) == marks_a
    assert props.count("VeilMark.Record.00") == 1
    with zipfile.ZipFile(b) as z:
        ours = [n for n in z.namelist() if n.startswith("customXml/item") and b"urn:veilmark" in z.read(n)
                and "Props" not in n]
    assert len(ours) == 1


def test_legacy_format_rejected(env):
    s, ledger, tmp = env
    src = tmp / "old.ppt"
    src.write_bytes(b"\xd0\xcf\x11\xe0legacy")
    with pytest.raises(ValueError, match="Save As"):
        protect_file(src, "X", settings=s, ledger=ledger)


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
@pytest.mark.parametrize("ext", ["docx", "pptx", "xlsx"])
def test_survives_office_resave(env, ext):
    s, ledger, tmp = env
    src = tmp / f"doc.{ext}"
    MAKERS[ext](src)
    a = protect_file(src, "Alice", settings=s, ledger=ledger).output
    b = protect_file(a, "Bob", settings=s, ledger=ledger).output
    outdir = tmp / "resaved"
    subprocess.run(["soffice", "--headless", "--convert-to", ext, "--outdir", str(outdir), str(b)],
                   check=True, capture_output=True, timeout=240)
    rep = trace_file(outdir / b.name, settings=s, ledger=ledger)
    assert rep.verdict == "authentic"
    assert [c.recipient for c in rep.chain] == ["Alice", "Bob"]
