"""Builders for realistic sample Office documents used by the tests."""
import io

import numpy as np
from PIL import Image


def png_bytes(w=160, h=120, seed=1):
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def make_docx(path, with_image=True):
    import docx

    d = docx.Document()
    d.add_heading("Quarterly strategy", 0)
    for i in range(12):
        d.add_paragraph(f"Paragraph {i}: confidential plans for the next quarter and beyond.")
    if with_image:
        d.add_picture(io.BytesIO(png_bytes()))
    d.sections[0].header.paragraphs[0].text = "Company confidential"
    d.save(path)


def make_pptx(path, with_image=True):
    from pptx import Presentation
    from pptx.util import Inches

    p = Presentation()
    for i in range(3):
        s = p.slides.add_slide(p.slide_layouts[1])
        s.shapes.title.text = f"Slide {i + 1} title"
        s.placeholders[1].text = f"Key point number {i + 1}\nSecond bullet with details"
        if with_image and i == 1:
            s.shapes.add_picture(io.BytesIO(png_bytes(seed=i)), Inches(5), Inches(4), Inches(2))
    p.save(path)


def make_xlsx(path, with_image=True):
    import openpyxl
    from openpyxl.drawing.image import Image as XLImage

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Budget"
    ws.append(["Item", "Cost", "Comment"])
    for i in range(10):
        ws.append([f"Item {i}", i * 100, "Long free text comment about this line item"])
    ws["E1"] = "=SUM(B2:B11)"
    if with_image:
        ws.add_image(XLImage(io.BytesIO(png_bytes(seed=7))), "G2")
    wb.save(path)
