import shutil
import subprocess
import zipfile

import pytest

from samples import make_docx, make_pptx, make_xlsx
from veilmark.registry import Ledger
from veilmark.service import protect_file, trace_file
from veilmark.settings import Settings
from veilmark.watermark import zerowidth

MAKERS = {"docx": make_docx, "pptx": make_pptx, "xlsx": make_xlsx}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILMARK_HOME", str(tmp_path / "home"))
    s = Settings.load()
    s.owner_name, s.organization = "Ahmed", "BookBeans"
    s.visible_footer = True
    return s, Ledger(), tmp_path


def _all_text(path):
    with zipfile.ZipFile(path) as z:
        return "".join(zerowidth.strip(z.read(n).decode("utf-8", "ignore")) for n in z.namelist()
                       if n.endswith(".xml"))


@pytest.mark.parametrize("ext", ["docx", "pptx", "xlsx"])
def test_footer_added_and_replaced_on_reshare(env, ext):
    s, ledger, tmp = env
    src = tmp / f"plan.{ext}"
    MAKERS[ext](src)
    a = protect_file(src, "Alice", settings=s, ledger=ledger)
    assert "Visible footer" in a.report.applied()
    text_a = _all_text(a.output)
    assert "Prepared for Alice" in text_a and "BookBeans" in text_a
    b = protect_file(a.output, "Bob", settings=s, ledger=ledger)
    text_b = _all_text(b.output)
    assert "Prepared for Bob" in text_b and "Prepared for Alice" not in text_b
    # watermark tracing unaffected
    assert [c.recipient for c in trace_file(b.output, settings=s, ledger=ledger).chain] == ["Alice", "Bob"]


def test_footer_off_by_default(env):
    s, ledger, tmp = env
    s.visible_footer = False
    src = tmp / "plan.docx"
    make_docx(src)
    out = protect_file(src, "Alice", settings=s, ledger=ledger).output
    assert "Prepared for" not in _all_text(out)


def test_word_existing_footer_kept(env):
    import docx

    s, ledger, tmp = env
    src = tmp / "f.docx"
    d = docx.Document()
    d.add_paragraph("Body")
    d.sections[0].footer.paragraphs[0].text = "Page footer by author"
    d.save(src)
    out = protect_file(src, "Carol", settings=s, ledger=ledger).output
    footer_texts = [p.text for p in docx.Document(out).sections[0].footer.paragraphs]
    joined = zerowidth.strip(" | ".join(footer_texts))
    assert "Page footer by author" in joined and "Prepared for Carol" in joined


def test_pptx_shape_is_valid(env):
    from pptx import Presentation

    s, ledger, tmp = env
    src = tmp / "d.pptx"
    make_pptx(src)
    out = protect_file(src, "Dan", settings=s, ledger=ledger).output
    prs = Presentation(out)
    for slide in prs.slides:
        shapes = [sh for sh in slide.shapes if sh.name == "VeilMark Footer"]
        assert len(shapes) == 1 and "Prepared for Dan" in zerowidth.strip(shapes[0].text_frame.text)
        ids = [sh.shape_id for sh in slide.shapes]
        assert len(ids) == len(set(ids))


def test_xlsx_footer_and_hidden_sheet_untouched(env):
    import openpyxl

    s, ledger, tmp = env
    src = tmp / "b.xlsx"
    make_xlsx(src)
    out = protect_file(src, "Eve", settings=s, ledger=ledger).output
    wb = openpyxl.load_workbook(out)
    assert "Prepared for Eve" in wb["Budget"].oddFooter.center.text
    assert not wb["_vm"].oddFooter.center.text


@pytest.mark.skipif(not (shutil.which("soffice") and shutil.which("pdftotext")), reason="needs LibreOffice")
@pytest.mark.parametrize("ext", ["docx", "pptx", "xlsx"])
def test_footer_visible_when_rendered(env, ext):
    s, ledger, tmp = env
    src = tmp / f"r.{ext}"
    MAKERS[ext](src)
    out = protect_file(src, "Frank Visible", settings=s, ledger=ledger).output
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(tmp / "pdf"), str(out)],
                   check=True, capture_output=True, timeout=240)
    pdf = tmp / "pdf" / (out.stem + ".pdf")
    text = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True).stdout
    assert "Frank Visible" in zerowidth.strip(text)
