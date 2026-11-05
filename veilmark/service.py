"""High-level operations used by both the GUI and the command line."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .registry import Issue, Ledger
from .settings import Settings
from .watermark import EmbedOptions, EmbedReport, Record, TraceResult, protect_bytes, read_existing_record, trace_bytes, trace_text
from .watermark.footer import render as render_footer
from .watermark.payload import now_iso


@dataclass
class ProtectResult:
    source: Path
    output: Path
    record: Record
    report: EmbedReport
    reshared: bool  # True if the file already carried our mark and a new hop was appended


@dataclass
class ChainEntry:
    step: int
    recipient: str
    note: str
    timestamp: str
    hop_id: str
    issued_by: str = ""
    source: str = "record"  # "record" | "ledger" | "token only"
    message: str = ""       # watermark text embedded in this copy


@dataclass
class TraceReport:
    file: str
    result: TraceResult
    verdict: str                     # "authentic" | "foreign" | "none" | "error"
    headline: str
    owner: str = ""
    organization: str = ""
    title: str = ""
    doc_id: str = ""
    created: str = ""
    chain: List[ChainEntry] = field(default_factory=list)
    likely_source: Optional[ChainEntry] = None
    message: str = ""                # the watermark text of this exact copy
    layer_status: List[tuple] = field(default_factory=list)  # (layer, found, detail)


def _safe_name(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().rstrip(".")
    return text[:60] or "recipient"


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def output_name(src: Path, recipient: str, reshared: bool, settings: Settings) -> str:
    stem = src.stem
    if reshared:  # don't stack suffixes: "Plan - for Ali - for Sara"
        stem = re.sub(r" - (for .+|watermarked)$", "", stem)
    if recipient:
        return settings.filename_pattern.format(stem=stem, recipient=_safe_name(recipient), ext=src.suffix)
    return f"{stem} - watermarked{src.suffix}"


def protect_file(src, recipient: str = "", note: str = "", *, message: str = "", settings: Settings,
                 ledger: Optional[Ledger] = None, output_dir=None, title: str = "") -> ProtectResult:
    """Embed a watermark.

    ``message`` is the watermark text the user typed (e.g. "© BookBeans 2026 - do not share").
    ``recipient`` is optional: who this copy is for, so a leaked copy can be traced to them.
    """
    src = Path(src)
    recipient, message = recipient.strip(), message.strip()
    if not recipient and not message:
        raise ValueError("Please type the watermark text.")
    data = src.read_bytes()
    key = settings.key_bytes
    record = read_existing_record(data, src.name, key)
    reshared = record is not None
    parent = record.chain[-1].hop_id if record and record.chain else None
    if record is None:
        record = Record.new(settings.owner_name or "Unknown owner", settings.organization, title or src.stem,
                            message=message)
    hop = record.add_hop(recipient, note, issued_by=settings.owner_name, message=message)
    opts = EmbedOptions(**{k: v for k, v in settings.layers.items() if k in EmbedOptions.__dataclass_fields__})
    if settings.visible_footer:
        opts.footer_text = message or render_footer(settings.footer_template, recipient, record.owner,
                                                    record.organization)
    out_bytes, report = protect_bytes(data, src.name, record, key, opts)

    out_dir = Path(output_dir or settings.output_folder or src.parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = _unique(out_dir / output_name(src, recipient, reshared, settings))
    out.write_bytes(out_bytes)

    (ledger or Ledger()).add(Issue(hop.hop_id, record.doc_id, parent, recipient, note, record.owner,
                                   settings.owner_name, str(src), str(out), hop.timestamp, message))
    return ProtectResult(src, out, record, report, reshared)


embed_watermark = protect_file  # clearer name for new code


def build_report(name: str, result: TraceResult, ledger: Optional[Ledger] = None) -> TraceReport:
    ledger = ledger or Ledger()
    layer_status = [(n, f.found, f.detail) for n, f in result.findings.items()]
    if result.error:
        return TraceReport(name, result, "error", result.error, layer_status=layer_status)
    if not result.found_anything:
        return TraceReport(name, result, "none", "No VeilMark watermark was found in this file.",
                           layer_status=layer_status)
    if not result.authentic:
        return TraceReport(name, result, "foreign",
                           "A VeilMark watermark is present, but it was made with a different team key.",
                           layer_status=layer_status)

    rep = TraceReport(name, result, "authentic", "", layer_status=layer_status)
    record = result.best_record
    if record:
        rep.owner, rep.organization, rep.title = record.owner, record.organization, record.title
        rep.doc_id, rep.created = record.doc_id, record.created
        for i, hop in enumerate(record.chain, 1):
            rep.chain.append(ChainEntry(i, hop.recipient, hop.note, hop.timestamp, hop.hop_id, hop.issued_by,
                                        message=hop.message or (record.message if i == 1 else "")))
    # tokens may reveal a *longer* chain than a stale record (e.g. record stripped after a re-share)
    known = {c.hop_id for c in rep.chain}
    for tok in result.tokens:
        if not tok.authentic or tok.hop_id in known:
            continue
        if rep.doc_id and tok.doc_id != rep.doc_id:
            continue
        known.add(tok.hop_id)
        rep.doc_id = rep.doc_id or tok.doc_id
        issue = ledger.get(tok.hop_id)
        if issue:
            rep.owner = rep.owner or issue.owner
            rep.chain.append(ChainEntry(len(rep.chain) + 1, issue.recipient, issue.note, issue.timestamp,
                                        tok.hop_id, issue.issued_by, source="ledger", message=issue.message))
        else:
            rep.chain.append(ChainEntry(len(rep.chain) + 1, "(issued on another computer)", "", "",
                                        tok.hop_id, source="token only"))
    rep.chain.sort(key=lambda c: c.timestamp or "9999")
    for i, c in enumerate(rep.chain, 1):
        c.step = i
    if rep.chain:
        rep.likely_source = rep.chain[-1]
        rep.message = next((c.message for c in reversed(rep.chain) if c.message), "")
    if not rep.message and record:
        rep.message = record.latest_message
    if rep.likely_source and rep.likely_source.recipient:
        rep.headline = f"Watermarked copy given to {rep.likely_source.recipient}"
    else:
        rep.headline = "Watermark found"
    return rep


def trace_file(path, *, settings: Settings, ledger: Optional[Ledger] = None) -> TraceReport:
    path = Path(path)
    result = trace_bytes(path.read_bytes(), path.name, settings.key_bytes)
    return build_report(path.name, result, ledger)


def trace_pasted_text(text: str, *, settings: Settings, ledger: Optional[Ledger] = None) -> TraceReport:
    return build_report("Pasted text", trace_text(text, settings.key_bytes), ledger)


__all__ = ["protect_file", "embed_watermark", "trace_file", "trace_pasted_text", "TraceReport", "ProtectResult", "now_iso"]
