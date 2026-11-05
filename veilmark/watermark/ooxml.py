"""Low-level helpers for Office Open XML packages (.docx / .pptx / .xlsx).

An Office file is a ZIP of XML "parts" wired together by relationship files and
a ``[Content_Types].xml`` manifest. lxml is used (rather than ElementTree)
because it preserves namespace prefixes; Office refuses files whose
``mc:Ignorable`` prefixes were renamed.
"""

from __future__ import annotations

import io
import posixpath
import zipfile
from typing import Dict, List, Optional

from lxml import etree

PKG_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
OFFICE_DOC_REL = R_NS + "/officeDocument"
STRICT_OFFICE_DOC_REL = "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument"

MAIN_TYPES = {
    "docx": "word",
    "pptx": "ppt",
    "xlsx": "xl",
}


class NotOfficeFile(Exception):
    pass


def parse_xml(data: bytes):
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False, huge_tree=True)
    return etree.fromstring(data, parser)


def to_xml(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


class Package:
    def __init__(self, data: bytes):
        try:
            self._zip_in = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise NotOfficeFile("Not a modern Office file (.docx/.pptx/.xlsx)") from exc
        self.order: List[str] = []
        self.parts: Dict[str, bytes] = {}
        for info in self._zip_in.infolist():
            if info.is_dir():
                continue
            self.order.append(info.filename)
            self.parts[info.filename] = self._zip_in.read(info.filename)
        if "[Content_Types].xml" not in self.parts:
            raise NotOfficeFile("Missing [Content_Types].xml - not an Office Open XML file")
        self.main_part = self._find_main_part()
        top = self.main_part.split("/", 1)[0]
        self.kind = {v: k for k, v in MAIN_TYPES.items()}.get(top)
        if self.kind is None:
            raise NotOfficeFile("Unsupported Office document type")

    # -- generic part access ------------------------------------------------ #
    def get(self, name: str) -> Optional[bytes]:
        return self.parts.get(name)

    def set(self, name: str, data: bytes) -> None:
        if name not in self.parts:
            self.order.append(name)
        self.parts[name] = data

    def delete(self, name: str) -> None:
        if name in self.parts:
            del self.parts[name]
            self.order.remove(name)

    def names(self) -> List[str]:
        return list(self.order)

    def save(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
            # [Content_Types].xml first, as Office itself writes it
            for name in sorted(self.order, key=lambda n: n != "[Content_Types].xml"):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                out.writestr(info, self.parts[name])
        return buf.getvalue()

    # -- relationships ------------------------------------------------------ #
    @staticmethod
    def rels_name(part: str) -> str:
        directory, base = posixpath.split(part)
        return posixpath.join(directory, "_rels", base + ".rels")

    def _find_main_part(self) -> str:
        rels = self.get("_rels/.rels")
        if rels is None:
            raise NotOfficeFile("Missing package relationships")
        for rel in parse_xml(rels):
            if rel.get("Type") in (OFFICE_DOC_REL, STRICT_OFFICE_DOC_REL):
                return rel.get("Target").lstrip("/")
        raise NotOfficeFile("No main document part found")

    def relationships(self, part: str):
        data = self.get(self.rels_name(part))
        if data is None:
            root = etree.Element(f"{{{PKG_RELS_NS}}}Relationships", nsmap={None: PKG_RELS_NS})
        else:
            root = parse_xml(data)
        return root

    def resolve(self, source_part: str, target: str) -> str:
        if target.startswith("/"):
            return target.lstrip("/")
        base = posixpath.dirname(source_part)
        return posixpath.normpath(posixpath.join(base, target))

    def add_relationship(self, source_part: str, rel_type: str, target_part: str) -> str:
        """Add (or reuse) a relationship; returns its rId. ``source_part`` '' = package root."""
        rels_name = "_rels/.rels" if source_part == "" else self.rels_name(source_part)
        root = self.relationships(source_part) if source_part else parse_xml(self.get("_rels/.rels"))
        base = posixpath.dirname(source_part) if source_part else ""
        target = posixpath.relpath(target_part, base) if base else target_part
        used = set()
        for rel in root:
            used.add(rel.get("Id"))
            if rel.get("Type") == rel_type and self.resolve(source_part, rel.get("Target")) == target_part:
                return rel.get("Id")
        n = 1
        while f"rId{n}" in used or f"rIdVm{n}" in used:
            n += 1
        rid = f"rIdVm{n}"
        etree.SubElement(root, f"{{{PKG_RELS_NS}}}Relationship",
                         Id=rid, Type=rel_type, Target=target)
        self.set(rels_name, to_xml(root))
        return rid

    def related_parts(self, source_part: str, rel_type_suffix: str) -> List[str]:
        out = []
        for rel in self.relationships(source_part):
            if (rel.get("Type") or "").endswith(rel_type_suffix) and rel.get("TargetMode") != "External":
                out.append(self.resolve(source_part, rel.get("Target")))
        return out

    # -- content types ------------------------------------------------------ #
    def ensure_override(self, part: str, content_type: str) -> None:
        root = parse_xml(self.get("[Content_Types].xml"))
        partname = "/" + part
        for el in root:
            if el.tag == f"{{{CT_NS}}}Override" and el.get("PartName") == partname:
                el.set("ContentType", content_type)
                break
        else:
            etree.SubElement(root, f"{{{CT_NS}}}Override", PartName=partname, ContentType=content_type)
        self.set("[Content_Types].xml", to_xml(root))

    def ensure_default(self, ext: str, content_type: str) -> None:
        root = parse_xml(self.get("[Content_Types].xml"))
        for el in root:
            if el.tag == f"{{{CT_NS}}}Default" and (el.get("Extension") or "").lower() == ext:
                return
        el = etree.Element(f"{{{CT_NS}}}Default", Extension=ext, ContentType=content_type)
        root.insert(0, el)
        self.set("[Content_Types].xml", to_xml(root))

    def unused_name(self, pattern: str) -> str:
        n = 1
        while pattern.format(n) in self.parts:
            n += 1
        return pattern.format(n)
