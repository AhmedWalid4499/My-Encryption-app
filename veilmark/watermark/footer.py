"""Visible deterrent: a "Confidential – prepared for <recipient>" footer.

* Word       - a footer paragraph on every section (added to existing footers, or a new footer part)
* PowerPoint - a small grey text box at the bottom of every slide
* Excel      - the printed page footer of every visible worksheet (shown in Page Layout view / print)

Our footer is recognisable (bookmark / shape name / marker text), so when a copy is
re-shared the old recipient's footer is *replaced* instead of piling up.
"""

from __future__ import annotations

import datetime as dt
import posixpath
import re

from lxml import etree

from .ooxml import Package, parse_xml, to_xml

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
SS_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
FOOTER_REL = R_NS + "/footer"
FOOTER_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"

MARK = "_VeilMarkFooter"          # Word bookmark name / PowerPoint shape name
# Invisible tag identifying a footer VeilMark added. Built from characters the invisible-text watermark
# never uses, so a watermark hidden inside the author's own footer can't be mistaken for our tag.
FOOTER_MARK = "\u2061\u2064\u2061"
LEGACY_XL_MARK = "\u2060\u200b\u2060"  # Excel footers made by 1.2.x (Excel footers never carry text marks)
XL_MARK = FOOTER_MARK
SHAPE_NAME = "VeilMark Footer"
DEFAULT_TEMPLATE = "CONFIDENTIAL – Prepared for {recipient} · {organization} · {date}"


def render(template: str, recipient: str, owner: str = "", organization: str = "") -> str:
    values = {"recipient": recipient, "owner": owner, "organization": organization,
              "date": dt.date.today().strftime("%d %b %Y")}
    try:
        text = (template or DEFAULT_TEMPLATE).format(**values)
    except (KeyError, IndexError, ValueError):
        text = DEFAULT_TEMPLATE.format(**values)
    # drop separators left behind by empty fields, e.g. "Sara ·  · 05 Nov" -> "Sara · 05 Nov"
    seps = "·|•"
    text = re.sub(rf"\s*[{seps}]\s*(?=[{seps}]|$)", "", text)
    text = re.sub(rf"^\s*[{seps}]\s*", "", text)
    text = re.sub(rf"\s*([{seps}])\s*", r" \1 ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _w(tag):
    return f"{{{W_NS}}}{tag}"


# --------------------------------------------------------------------------- #
# Word
# --------------------------------------------------------------------------- #
def _word_paragraph(text: str):
    """Centred grey 8 pt paragraph. Tagged with invisible characters (not a bookmark: bookmark ids must be
    unique across the whole document, and repeated ids make Word offer to "repair" the file)."""
    p = etree.Element(_w("p"))
    ppr = etree.SubElement(p, _w("pPr"))
    etree.SubElement(ppr, _w("jc")).set(_w("val"), "center")
    r = etree.SubElement(p, _w("r"))
    rpr = etree.SubElement(r, _w("rPr"))
    etree.SubElement(rpr, _w("color")).set(_w("val"), "808080")
    etree.SubElement(rpr, _w("sz")).set(_w("val"), "16")  # 8 pt
    t = etree.SubElement(r, _w("t"))
    t.text = text + FOOTER_MARK
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return p


def _is_our_word_paragraph(p) -> bool:
    from . import zerowidth

    text = zerowidth.strip("".join(p.itertext()))  # ignore hidden watermark characters
    if FOOTER_MARK in text:
        return True
    if any(b.get(_w("name")) == MARK for b in p.iter(_w("bookmarkStart"))):  # made by VeilMark 1.1-1.3
        return True
    return text.upper().startswith("CONFIDENTIAL") and "prepared for" in text.lower()


def _word_set_footer_part(pkg: Package, part: str, text: str) -> None:
    root = parse_xml(pkg.get(part))
    # only top-level paragraphs VeilMark added itself; never touch paragraphs inside tables/text boxes
    # (removing those can leave an empty table cell, which Word treats as a damaged file)
    for p in list(root.findall(_w("p"))):
        if _is_our_word_paragraph(p):
            root.remove(p)
    root.append(_word_paragraph(text))  # the footer is never left without a paragraph
    pkg.set(part, to_xml(root))


def _word(pkg: Package, text: str) -> str:
    doc_name = pkg.main_part
    doc = parse_xml(pkg.get(doc_name))
    rel_targets = {rel.get("Id"): pkg.resolve(doc_name, rel.get("Target"))
                   for rel in pkg.relationships(doc_name)}
    sections = list(doc.iter(_w("sectPr")))
    if not sections:
        body = doc.find(_w("body"))
        sections = [etree.SubElement(body, _w("sectPr"))]
    done, created = set(), 0
    for sect in sections:
        refs = [r for r in sect.findall(_w("footerReference")) if r.get(_w("type"), "default") == "default"]
        if refs:
            part = rel_targets.get(refs[0].get(f"{{{R_NS}}}id"))
            if part and pkg.get(part) is not None:
                if part not in done:
                    _word_set_footer_part(pkg, part, text)
                    done.add(part)
                continue
        # no default footer in this section -> create one
        part = pkg.unused_name("word/footer{}.xml")
        ftr = etree.Element(_w("ftr"), nsmap={"w": W_NS, "r": R_NS})
        ftr.append(_word_paragraph(text))
        pkg.set(part, to_xml(ftr))
        pkg.ensure_override(part, FOOTER_CT)
        rid = pkg.add_relationship(doc_name, FOOTER_REL, part)
        ref = etree.Element(_w("footerReference"))
        ref.set(_w("type"), "default")
        ref.set(f"{{{R_NS}}}id", rid)
        # header/footer references must come first inside sectPr
        idx = sum(1 for c in sect if c.tag in (_w("headerReference"), _w("footerReference")))
        sect.insert(idx, ref)
        done.add(part)
        created += 1
    pkg.set(doc_name, to_xml(doc))
    return f"footer on {len(sections)} section(s)"


# --------------------------------------------------------------------------- #
# PowerPoint
# --------------------------------------------------------------------------- #
def _p(tag):
    return f"{{{P_NS}}}{tag}"


def _a(tag):
    return f"{{{A_NS}}}{tag}"


def _ppt(pkg: Package, text: str) -> str:
    pres = parse_xml(pkg.get(pkg.main_part))
    size = pres.find(_p("sldSz"))
    cx = int(size.get("cx")) if size is not None else 12192000
    cy = int(size.get("cy")) if size is not None else 6858000
    height = int(cy * 0.045)
    count = 0
    for name in pkg.names():
        if not re.fullmatch(r"ppt/slides/slide\d+\.xml", name):
            continue
        root = parse_xml(pkg.get(name))
        tree = root.find(f"{_p('cSld')}/{_p('spTree')}")
        if tree is None:
            continue
        for sp in list(tree.findall(_p("sp"))):
            c = sp.find(f"{_p('nvSpPr')}/{_p('cNvPr')}")
            if c is not None and c.get("name") == SHAPE_NAME:
                tree.remove(sp)
        ids = [int(e.get("id")) for e in root.iter(_p("cNvPr")) if (e.get("id") or "").isdigit()]
        sp = etree.Element(_p("sp"))
        nv = etree.SubElement(sp, _p("nvSpPr"))
        etree.SubElement(nv, _p("cNvPr"), id=str(max(ids + [1]) + 1), name=SHAPE_NAME)
        etree.SubElement(nv, _p("cNvSpPr"), txBox="1")
        etree.SubElement(nv, _p("nvPr"))
        sppr = etree.SubElement(sp, _p("spPr"))
        xfrm = etree.SubElement(sppr, _a("xfrm"))
        etree.SubElement(xfrm, _a("off"), x=str(int(cx * 0.05)), y=str(cy - height - int(cy * 0.01)))
        etree.SubElement(xfrm, _a("ext"), cx=str(int(cx * 0.9)), cy=str(height))
        etree.SubElement(etree.SubElement(sppr, _a("prstGeom"), prst="rect"), _a("avLst"))
        etree.SubElement(sppr, _a("noFill"))
        body = etree.SubElement(sp, _p("txBody"))
        etree.SubElement(body, _a("bodyPr"), wrap="square", lIns="0", tIns="0", rIns="0", bIns="0", anchor="b")
        etree.SubElement(body, _a("lstStyle"))
        para = etree.SubElement(body, _a("p"))
        etree.SubElement(para, _a("pPr"), algn="ctr")
        run = etree.SubElement(para, _a("r"))
        rpr = etree.SubElement(run, _a("rPr"), lang="en-US", sz="900", dirty="0")
        etree.SubElement(etree.SubElement(rpr, _a("solidFill")), _a("srgbClr"), val="7F7F7F")
        etree.SubElement(run, _a("t")).text = text
        ext = tree.find(_p("extLst"))
        if ext is not None:
            ext.addprevious(sp)
        else:
            tree.append(sp)
        pkg.set(name, to_xml(root))
        count += 1
    return f"footer on {count} slide(s)" if count else "skipped - no slides"


# --------------------------------------------------------------------------- #
# Excel
# --------------------------------------------------------------------------- #
# CT_Worksheet child order: headerFooter must come after these elements
_BEFORE_HF = ["sheetPr", "dimension", "sheetViews", "sheetFormatPr", "cols", "sheetData", "sheetCalcPr",
              "sheetProtection", "protectedRanges", "scenarios", "autoFilter", "sortState", "dataConsolidate",
              "customSheetViews", "mergeCells", "phoneticPr", "conditionalFormatting", "dataValidations",
              "hyperlinks", "printOptions", "pageMargins", "pageSetup"]


def _xl_escape(text: str) -> str:
    return text.replace("&", "&&")


def _xl(pkg: Package, text: str) -> str:
    wb_name = pkg.main_part
    wb = parse_xml(pkg.get(wb_name))
    if wb.tag != f"{{{SS_NS}}}workbook":
        return "skipped - strict OOXML workbook"
    targets = {rel.get("Id"): pkg.resolve(wb_name, rel.get("Target")) for rel in pkg.relationships(wb_name)}
    ours = "&C&8&K7F7F7F" + _xl_escape(text) + XL_MARK
    count = 0
    for sh in wb.iter(f"{{{SS_NS}}}sheet"):
        if sh.get("state") in ("hidden", "veryHidden"):
            continue
        part = targets.get(sh.get(f"{{{R_NS}}}id"))
        data = pkg.get(part) if part else None
        if data is None or not posixpath.basename(part).startswith("sheet"):
            continue
        ws = parse_xml(data)
        if ws.tag != f"{{{SS_NS}}}worksheet":
            continue  # chart sheets etc.
        hf = ws.find(f"{{{SS_NS}}}headerFooter")
        if hf is None:
            hf = etree.Element(f"{{{SS_NS}}}headerFooter")
            anchor = None
            for child in ws:
                if etree.QName(child).localname in _BEFORE_HF:
                    anchor = child
            if anchor is not None:
                anchor.addnext(hf)
            else:
                ws.insert(0, hf)
        footer = hf.find(f"{{{SS_NS}}}oddFooter")
        if footer is None:
            footer = etree.Element(f"{{{SS_NS}}}oddFooter")
            oh = hf.find(f"{{{SS_NS}}}oddHeader")
            if oh is not None:
                oh.addnext(footer)
            else:
                hf.insert(0, footer)
            footer.text = ours
        else:
            existing = footer.text or ""
            if FOOTER_MARK in existing or LEGACY_XL_MARK in existing or "prepared for" in existing.lower() \
                    or not existing.strip():
                footer.text = ours
            elif "&C" not in existing:
                footer.text = existing + ours
            else:
                continue  # leave the author's centre footer alone
        for tag in ("evenFooter", "firstFooter"):
            alt = hf.find(f"{{{SS_NS}}}{tag}")
            alt_text = alt.text or "" if alt is not None else ""
            if alt is not None and (FOOTER_MARK in alt_text or LEGACY_XL_MARK in alt_text
                                    or "prepared for" in alt_text.lower()):
                alt.text = ours
        pkg.set(part, to_xml(ws))
        count += 1
    return f"print footer on {count} sheet(s)" if count else "skipped - sheets already have a centre footer"


def apply(pkg: Package, text: str) -> str:
    return {"docx": _word, "pptx": _ppt, "xlsx": _xl}[pkg.kind](pkg, text)
