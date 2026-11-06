"""Embed and trace watermarks in Office documents, images and plain text.

Five independent layers are used, so the mark survives even when some are lost
on the way (re-saving, "Inspect Document", copying slides, pasting text...):

    1. Document properties  - encrypted record in custom document properties
    2. Custom XML part      - encrypted record in a hidden customXml data part
    3. Invisible text       - token chain as zero-width characters inside the text
    4. Hidden data sheet    - (Excel) encrypted record in a "very hidden" worksheet
    5. Image pixels (LSB)   - token chain + record inside lossless pictures (thesis method)
"""

from __future__ import annotations

import base64
import html
import io
import posixpath
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from lxml import etree

from . import footer, lsb, zerowidth
from .ooxml import NotOfficeFile, Package, parse_xml, to_xml
from .payload import Record, Token, open_record, open_record_b64, split_tokens

OFFICE_EXTS = {".docx", ".docm", ".pptx", ".pptm", ".xlsx", ".xlsm"}
IMAGE_EXTS = {".png", ".bmp", ".tif", ".tiff"}
TEXT_EXTS = {".txt", ".csv", ".md", ".html", ".htm", ".json", ".xml", ".rtf", ".eml"}
LEGACY_EXTS = {".doc", ".ppt", ".xls"}

LAYER_PROPS = "Document properties"
LAYER_CUSTOMXML = "Custom XML part"
LAYER_TEXT = "Invisible text marks"
LAYER_SHEET = "Hidden data sheet"
LAYER_IMAGES = "Image pixels (LSB)"
LAYER_FOOTER = "Visible footer"  # deterrent only - not used for tracing
ALL_LAYERS = [LAYER_PROPS, LAYER_CUSTOMXML, LAYER_TEXT, LAYER_SHEET, LAYER_IMAGES]

PROP_PREFIX = "VeilMark.Record."
PROP_CHUNK = 240  # Office truncates custom property strings at 255 chars
RECORD_TAG = "VMREC1:"
_RECORD_RE = re.compile(re.escape(RECORD_TAG) + r"([A-Za-z0-9+/=]{40,})")
VM_XML_NS = "urn:veilmark:watermark:v1"
HIDDEN_SHEET = "_vm"

CUSTOM_PROPS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
CUSTOM_PROPS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties"
CUSTOM_PROPS_CT = "application/vnd.openxmlformats-officedocument.custom-properties+xml"
CUSTOMXML_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml"
CUSTOMXML_PROPS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps"
CUSTOMXML_PROPS_CT = "application/vnd.openxmlformats-officedocument.customXmlProperties+xml"
DS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/customXml"
SS_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
WORKSHEET_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
WORKSHEET_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

PROPS_FMTID = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"


@dataclass
class EmbedOptions:
    properties: bool = True
    custom_xml: bool = True
    invisible_text: bool = True
    hidden_sheet: bool = True
    images: bool = True
    excel_cell_text: bool = False  # opt-in: alters cell strings, may affect formulas/lookups
    footer_text: str = ""          # non-empty -> add a visible "Confidential - prepared for ..." footer


@dataclass
class EmbedReport:
    layers: Dict[str, str] = field(default_factory=dict)  # layer -> human description

    def applied(self) -> List[str]:
        return [k for k, v in self.layers.items() if not v.startswith("skipped")]


@dataclass
class LayerFinding:
    layer: str
    found: bool = False
    detail: str = ""
    tokens: List[Token] = field(default_factory=list)
    records: List[Record] = field(default_factory=list)


@dataclass
class TraceResult:
    findings: Dict[str, LayerFinding] = field(default_factory=dict)
    file_kind: str = ""
    error: str = ""

    @property
    def records(self) -> List[Record]:
        out: List[Record] = []
        for f in self.findings.values():
            out.extend(f.records)
        return out

    @property
    def tokens(self) -> List[Token]:
        out: List[Token] = []
        for f in self.findings.values():
            out.extend(f.tokens)
        return out

    @property
    def best_record(self) -> Optional[Record]:
        recs = self.records
        return max(recs, key=lambda r: len(r.chain)) if recs else None

    @property
    def found_anything(self) -> bool:
        return any(f.found for f in self.findings.values())

    @property
    def authentic(self) -> bool:
        return bool(self.records) or any(t.authentic for t in self.tokens)

    @property
    def layers_found(self) -> List[str]:
        return [name for name, f in self.findings.items() if f.found]


# =========================================================================== #
# Embedding - Office
# =========================================================================== #
def _write_properties(pkg: Package, record_b64: str) -> str:
    name = "docProps/custom.xml"
    data = pkg.get(name)
    if data is None:
        root = etree.Element(f"{{{CUSTOM_PROPS_NS}}}Properties", nsmap={None: CUSTOM_PROPS_NS, "vt": VT_NS})
    else:
        root = parse_xml(data)
    for prop in list(root):
        if (prop.get("name") or "").startswith(PROP_PREFIX):
            root.remove(prop)
    pids = [int(p.get("pid")) for p in root if (p.get("pid") or "").isdigit()]
    pid = max(pids + [1]) + 1
    chunks = [record_b64[i:i + PROP_CHUNK] for i in range(0, len(record_b64), PROP_CHUNK)]
    for i, chunk in enumerate(chunks):
        prop = etree.SubElement(root, f"{{{CUSTOM_PROPS_NS}}}property",
                                fmtid=PROPS_FMTID, pid=str(pid + i), name=f"{PROP_PREFIX}{i:02d}")
        etree.SubElement(prop, f"{{{VT_NS}}}lpwstr").text = chunk
    pkg.set(name, to_xml(root))
    pkg.ensure_override(name, CUSTOM_PROPS_CT)
    pkg.add_relationship("", CUSTOM_PROPS_REL, name)
    return f"{len(chunks)} encrypted properties"


def _find_vm_customxml(pkg: Package) -> Optional[str]:
    for name in pkg.names():
        if re.fullmatch(r"customXml/item\d+\.xml", name) and VM_XML_NS.encode() in pkg.get(name)[:400]:
            return name
    return None


def _write_customxml(pkg: Package, record_b64: str) -> str:
    item = _find_vm_customxml(pkg) or pkg.unused_name("customXml/item{}.xml")
    num = re.search(r"(\d+)", posixpath.basename(item)).group(1)
    props = f"customXml/itemProps{num}.xml"
    root = etree.Element(f"{{{VM_XML_NS}}}watermark", nsmap={"vm": VM_XML_NS})
    root.text = RECORD_TAG + record_b64
    pkg.set(item, to_xml(root))
    if pkg.get(props) is None:
        ds = etree.Element(f"{{{DS_NS}}}datastoreItem", nsmap={"ds": DS_NS})
        ds.set(f"{{{DS_NS}}}itemID", "{" + str(uuid.uuid4()).upper() + "}")
        etree.SubElement(etree.SubElement(ds, f"{{{DS_NS}}}schemaRefs"), f"{{{DS_NS}}}schemaRef").set(
            f"{{{DS_NS}}}uri", VM_XML_NS)
        pkg.set(props, to_xml(ds))
    pkg.ensure_default("xml", "application/xml")
    pkg.ensure_override(props, CUSTOMXML_PROPS_CT)
    pkg.add_relationship(item, CUSTOMXML_PROPS_REL, props)
    pkg.add_relationship(pkg.main_part, CUSTOMXML_REL, item)
    return "encrypted data part"


def _mark_text_nodes(nodes, mark: str, every: int) -> int:
    """Strip old marks from text nodes and append ``mark`` to a spread-out subset."""
    non_empty = []
    for node in nodes:
        if node.text and zerowidth.contains_any(node.text):
            node.text = zerowidth.strip(node.text)
        if node.text and node.text.strip():
            non_empty.append(node)
    if not non_empty:
        return 0
    chosen = {0, len(non_empty) - 1} | set(range(0, len(non_empty), max(1, every)))
    for i in sorted(chosen):
        non_empty[i].text = non_empty[i].text + mark
    return len(chosen)


def _text_parts(pkg: Package) -> List[tuple]:
    """(part name, text element tag, spacing) for every part whose text should carry marks."""
    names = pkg.names()
    if pkg.kind == "docx":
        tag = f"{{{W_NS}}}t"
        parts = [pkg.main_part] + [n for n in names if re.fullmatch(r"word/(header|footer|footnotes|endnotes)\d*\.xml", n)]
        return [(p, tag, 6) for p in parts]
    if pkg.kind == "pptx":
        tag = f"{{{A_NS}}}t"
        parts = [n for n in names if re.fullmatch(r"ppt/(slides/slide|notesSlides/notesSlide)\d+\.xml", n)]
        return [(p, tag, 4) for p in parts]
    return []


def _write_invisible_text(pkg: Package, mark: str, excel_cells: bool) -> str:
    total, parts_marked = 0, 0
    targets = _text_parts(pkg)
    if pkg.kind == "xlsx" and excel_cells and pkg.get("xl/sharedStrings.xml") is not None:
        targets.append(("xl/sharedStrings.xml", f"{{{SS_NS}}}t", 10))
    for part, tag, every in targets:
        data = pkg.get(part)
        if data is None:
            continue
        root = parse_xml(data)
        # never touch field text (slide numbers, dates): PowerPoint regenerates it
        nodes = [n for n in root.iter(tag) if n.getparent() is None or n.getparent().tag != f"{{{A_NS}}}fld"]
        if pkg.kind == "xlsx":
            # only longer free-text strings, never things that look like keys/numbers
            nodes = [n for n in nodes if n.text and len(n.text.strip()) >= 12 and " " in n.text.strip()]
        count = _mark_text_nodes(nodes, mark, every)
        if count:
            pkg.set(part, to_xml(root))
            total += count
            parts_marked += 1
    if not total:
        return "skipped - no text found"
    return f"{total} marks in {parts_marked} part(s)"


def _write_hidden_sheet(pkg: Package, record_b64: str) -> str:
    wb_name = pkg.main_part
    wb = parse_xml(pkg.get(wb_name))
    if wb.tag != f"{{{SS_NS}}}workbook":
        return "skipped - strict OOXML workbook"
    sheets = wb.find(f"{{{SS_NS}}}sheets")
    existing = None
    for sh in sheets:
        if sh.get("name") == HIDDEN_SHEET:
            existing = sh
    if existing is not None:
        rid = existing.get(f"{{{R_NS}}}id")
        target = None
        for rel in pkg.relationships(wb_name):
            if rel.get("Id") == rid:
                target = pkg.resolve(wb_name, rel.get("Target"))
        sheet_part = target or pkg.unused_name("xl/worksheets/sheet{}.xml")
    else:
        sheet_part = pkg.unused_name("xl/worksheets/sheet{}.xml")
    payload = RECORD_TAG + record_b64
    ws = etree.Element(f"{{{SS_NS}}}worksheet", nsmap={None: SS_NS})
    data = etree.SubElement(ws, f"{{{SS_NS}}}sheetData")
    row = etree.SubElement(data, f"{{{SS_NS}}}row", r="1")
    cell = etree.SubElement(row, f"{{{SS_NS}}}c", r="A1", t="inlineStr")
    etree.SubElement(etree.SubElement(cell, f"{{{SS_NS}}}is"), f"{{{SS_NS}}}t").text = payload
    pkg.set(sheet_part, to_xml(ws))
    pkg.ensure_override(sheet_part, WORKSHEET_CT)
    rid = pkg.add_relationship(wb_name, WORKSHEET_REL, sheet_part)
    if existing is None:
        ids = [int(s.get("sheetId")) for s in sheets if (s.get("sheetId") or "").isdigit()]
        el = etree.SubElement(sheets, f"{{{SS_NS}}}sheet", name=HIDDEN_SHEET,
                              sheetId=str(max(ids + [0]) + 1), state="veryHidden")
        el.set(f"{{{R_NS}}}id", rid)
    else:
        existing.set("state", "veryHidden")
        existing.set(f"{{{R_NS}}}id", rid)
    pkg.set(wb_name, to_xml(wb))
    return "very hidden worksheet"


def _write_images(pkg: Package, lsb_payload: bytes) -> str:
    media_dir = {"docx": "word/media/", "pptx": "ppt/media/", "xlsx": "xl/media/"}[pkg.kind]
    marked = 0
    for name in pkg.names():
        if not name.startswith(media_dir):
            continue
        if posixpath.splitext(name)[1].lower() not in {".png", ".bmp", ".tif", ".tiff"}:
            continue
        new = lsb.embed(pkg.get(name), lsb_payload)
        if new:
            pkg.set(name, new)
            marked += 1
    return f"{marked} picture(s)" if marked else "skipped - no lossless pictures"


def embed_office(data: bytes, record: Record, key: bytes, options: EmbedOptions = None) -> tuple[bytes, EmbedReport]:
    options = options or EmbedOptions()
    pkg = Package(data)
    sealed = record.seal(key)
    record_b64 = base64.b64encode(sealed).decode("ascii")
    tokens = record.token_chain(key)
    report = EmbedReport()
    off = "skipped - turned off"

    if options.footer_text:
        # added before the invisible marks so the footer text carries marks too
        report.layers[LAYER_FOOTER] = footer.apply(pkg, options.footer_text)
    report.layers[LAYER_PROPS] = _write_properties(pkg, record_b64) if options.properties else off
    report.layers[LAYER_CUSTOMXML] = _write_customxml(pkg, record_b64) if options.custom_xml else off
    if options.invisible_text:
        report.layers[LAYER_TEXT] = _write_invisible_text(pkg, zerowidth.encode(tokens), options.excel_cell_text)
    else:
        report.layers[LAYER_TEXT] = off
    if pkg.kind == "xlsx":
        report.layers[LAYER_SHEET] = _write_hidden_sheet(pkg, record_b64) if options.hidden_sheet else off
    report.layers[LAYER_IMAGES] = _write_images(pkg, lsb.pack_payload(tokens, sealed)) if options.images else off
    return pkg.save(), report


# =========================================================================== #
# Embedding - images and text
# =========================================================================== #
def embed_image(data: bytes, record: Record, key: bytes) -> tuple[bytes, EmbedReport]:
    out = lsb.embed(data, lsb.pack_payload(record.token_chain(key), record.seal(key)))
    if out is None:
        raise ValueError("This picture is too small or not lossless (use PNG or BMP).")
    return out, EmbedReport({LAYER_IMAGES: "picture pixels"})


def embed_text(text: str, record: Record, key: bytes) -> str:
    """Hide the token chain after every paragraph of plain text."""
    mark = zerowidth.encode(record.token_chain(key))
    lines = zerowidth.strip(text).split("\n")
    idx = [i for i, line in enumerate(lines) if line.strip()]
    for i in idx[:: max(1, len(idx) // 20 or 1)] + idx[-1:]:
        if not lines[i].endswith(mark):
            lines[i] += mark
    return "\n".join(lines)


# =========================================================================== #
# Tracing
# =========================================================================== #
def _records_from_text(text: str, key: Optional[bytes]) -> List[Record]:
    out = []
    if key is None:
        return out
    for m in _RECORD_RE.finditer(text):
        rec = open_record_b64(m.group(1), key)
        if rec:
            out.append(rec)
    return out


def _tokens_from_text(text: str, key: Optional[bytes]) -> List[Token]:
    out = []
    for blob in zerowidth.find_all(text):
        out.extend(split_tokens(blob, key))
    return out


def _part_text(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", "ignore")
    return html.unescape(text) if "&#" in text else text


def trace_office(data: bytes, key: Optional[bytes]) -> TraceResult:
    pkg = Package(data)
    res = TraceResult(file_kind=pkg.kind)
    f = {name: LayerFinding(name) for name in ALL_LAYERS}
    if pkg.kind != "xlsx":
        f.pop(LAYER_SHEET)
    res.findings = f

    # 1. custom properties (chunks re-assembled in name order)
    props = pkg.get("docProps/custom.xml")
    if props is not None:
        root = parse_xml(props)
        chunks = sorted(((p.get("name"), "".join(p.itertext())) for p in root
                         if (p.get("name") or "").startswith(PROP_PREFIX)))
        if chunks:
            f[LAYER_PROPS].found = True
            rec = open_record_b64("".join(c for _, c in chunks), key) if key else None
            if rec:
                f[LAYER_PROPS].records.append(rec)
                f[LAYER_PROPS].detail = "encrypted record decoded"
            else:
                f[LAYER_PROPS].detail = "present, but cannot be decrypted with your key"

    for name in pkg.names():
        raw = pkg.get(name)
        lower = name.lower()
        if lower.endswith((".xml", ".rels", ".vml")):
            text = _part_text(raw)
            if re.fullmatch(r"customxml/item\d+\.xml", lower) and VM_XML_NS in text:
                layer = f[LAYER_CUSTOMXML]
                layer.found = True
                recs = _records_from_text(text, key)
                layer.records += recs
                layer.detail = "encrypted record decoded" if recs else "present, but cannot be decrypted with your key"
                continue
            # the hidden sheet's cell may live inline in the worksheet or (after another
            # app re-saves the workbook) in xl/sharedStrings.xml
            if LAYER_SHEET in f and lower.startswith("xl/") and RECORD_TAG in text:
                layer = f[LAYER_SHEET]
                layer.found = True
                recs = _records_from_text(text, key)
                layer.records += recs
                layer.detail = "encrypted record decoded" if recs else "present, but cannot be decrypted with your key"
            toks = _tokens_from_text(text, key)
            if toks:
                layer = f[LAYER_TEXT]
                layer.found = True
                layer.tokens += toks
        elif posixpath.splitext(lower)[1] in {".png", ".bmp", ".tif", ".tiff", ".gif"}:
            payloads = lsb.extract(raw)
            if payloads:
                layer = f[LAYER_IMAGES]
                layer.found = True
                for p in payloads:
                    tok_blob, rec_blob = lsb.unpack_payload(p)
                    layer.tokens += split_tokens(tok_blob, key)
                    if key and rec_blob:
                        rec = open_record(rec_blob, key)
                        if rec:
                            layer.records.append(rec)
    text_layer = f[LAYER_TEXT]
    if text_layer.found:
        text_layer.detail = f"{len(text_layer.tokens)} token(s) recovered from text"
    img = f[LAYER_IMAGES]
    if img.found:
        img.detail = f"payload recovered ({len(img.records)} record(s), {len(img.tokens)} token(s))"
    return res


def trace_image(data: bytes, key: Optional[bytes]) -> TraceResult:
    res = TraceResult(file_kind="image")
    layer = LayerFinding(LAYER_IMAGES)
    for p in lsb.extract(data):
        layer.found = True
        tok_blob, rec_blob = lsb.unpack_payload(p)
        layer.tokens += split_tokens(tok_blob, key)
        if key and rec_blob:
            rec = open_record(rec_blob, key)
            if rec:
                layer.records.append(rec)
    if layer.found:
        layer.detail = "payload recovered from pixels"
    res.findings[LAYER_IMAGES] = layer
    return res


def trace_text(text: str, key: Optional[bytes]) -> TraceResult:
    res = TraceResult(file_kind="text")
    layer = LayerFinding(LAYER_TEXT)
    layer.tokens = _tokens_from_text(text, key)
    layer.records = _records_from_text(text, key)
    layer.found = bool(layer.tokens or layer.records)
    if layer.found:
        layer.detail = f"{len(layer.tokens)} token(s) recovered from text"
    res.findings[LAYER_TEXT] = layer
    return res


def _decode_text_file(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def trace_bytes(data: bytes, filename: str, key: Optional[bytes]) -> TraceResult:
    ext = Path(filename).suffix.lower()
    if is_protected_office(data, filename):
        return TraceResult(error=PROTECTED_MSG)
    if ext in LEGACY_EXTS:
        return TraceResult(error="Old binary Office format. Open it in Office and 'Save As' .docx/.pptx/.xlsx first.")
    if data[:2] == b"PK":
        try:
            return trace_office(data, key)
        except NotOfficeFile as exc:
            return TraceResult(error=str(exc))
    try:
        from PIL import Image

        Image.open(io.BytesIO(data)).verify()
        return trace_image(data, key)
    except Exception:
        pass
    return trace_text(_decode_text_file(data), key)


def read_existing_record(data: bytes, filename: str, key: bytes) -> Optional[Record]:
    """If the file already carries *our* watermark, return its record so a new hop can be appended."""
    try:
        return trace_bytes(data, filename, key).best_record
    except Exception:
        return None


def protect_bytes(data: bytes, filename: str, record: Record, key: bytes,
                  options: EmbedOptions = None) -> tuple[bytes, EmbedReport]:
    ext = Path(filename).suffix.lower()
    if is_protected_office(data, filename):
        raise ValueError(PROTECTED_MSG)
    if ext in OFFICE_EXTS:
        return embed_office(data, record, key, options)
    if ext in IMAGE_EXTS:
        return embed_image(data, record, key)
    if ext in TEXT_EXTS:
        text = _decode_text_file(data)
        return embed_text(text, record, key).encode("utf-8"), EmbedReport({LAYER_TEXT: "invisible text marks"})
    if ext in LEGACY_EXTS:
        raise ValueError("Old binary Office format. Please 'Save As' .docx / .pptx / .xlsx first.")
    raise ValueError(f"Unsupported file type: {ext or 'unknown'}")


SUPPORTED_PROTECT = sorted(OFFICE_EXTS | IMAGE_EXTS | TEXT_EXTS)

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
PROTECTED_MSG = ("This Office file is protected (a password or a sensitivity label such as “Confidential” that "
                 "encrypts the file). VeilMark can't look inside it. Open it in Office, save a copy without the "
                 "encryption (File → Info → Protect / Sensitivity), and use that copy.")


def is_protected_office(data: bytes, filename: str) -> bool:
    """Password-protected or Microsoft Purview (sensitivity label) encrypted .docx/.pptx/.xlsx."""
    return (Path(filename).suffix.lower() in OFFICE_EXTS and data[:8] == OLE_MAGIC
            and "EncryptedPackage".encode("utf-16-le") in data[:200_000])


class EmbedCheckError(ValueError):
    pass


def verify_protected(out: bytes, filename: str, key: bytes, doc_id: str, hop_id: str) -> None:
    """Re-open the watermarked result before it is saved. Raises EmbedCheckError if anything is off."""
    ext = Path(filename).suffix.lower()
    fail = ("VeilMark stopped before saving because the watermarked copy didn't pass its safety check "
            "({}). Your original file is untouched.")
    if ext in OFFICE_EXTS:
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(out)) as z:
                if z.testzip() is not None:
                    raise EmbedCheckError(fail.format("damaged archive"))
                for name in z.namelist():
                    if name.lower().endswith((".xml", ".rels")):
                        parse_xml(z.read(name))
            Package(out)
        except EmbedCheckError:
            raise
        except Exception as exc:  # noqa: BLE001 - any parse problem means "don't save"
            raise EmbedCheckError(fail.format(f"invalid document structure: {exc}")) from exc
    result = trace_bytes(out, filename, key)
    hops = {t.hop_id for t in result.tokens if t.authentic}
    for rec in result.records:
        if rec.doc_id == doc_id:
            hops |= {h.hop_id for h in rec.chain}
    if hop_id not in hops:
        raise EmbedCheckError(fail.format("the watermark could not be read back"))
ProgressFn = Optional[Callable[[str, float], None]]
