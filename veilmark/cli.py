"""Command-line interface (handy for scripting and batch jobs).

    veilmark embed report.pptx --text "© 2026 BookBeans - confidential" [--to "Alice Smith"]
    veilmark extract "found online.pptx"
    veilmark encrypt secret.xlsx            (asks for a password)
    veilmark decrypt secret.xlsx.vmk
"""

from __future__ import annotations

import argparse
import getpass
import sys

from . import __version__
from .crypto import DecryptionError, decrypt_file, encrypt_file
from .registry import Ledger
from .service import protect_file, trace_file
from .settings import Settings


def _password(confirm: bool) -> str:
    pw = getpass.getpass("Password: ")
    if confirm and getpass.getpass("Repeat password: ") != pw:
        sys.exit("Passwords do not match.")
    return pw


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="veilmark", description="Invisible document watermarking & chaotic encryption")
    ap.add_argument("--version", action="version", version=f"VeilMark {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("embed", aliases=["protect"], help="embed a watermark in files")
    p.add_argument("files", nargs="+")
    p.add_argument("--text", default="", help="the watermark text to hide")
    p.add_argument("--to", default="", help="optional: who this copy is for (enables leak tracing)")
    p.add_argument("--note", default="")
    p.add_argument("--footer", action="store_true", help="also show the text as a visible footer")
    p.add_argument("--out", default=None, help="output folder")

    t = sub.add_parser("extract", aliases=["trace"], help="read the watermark hidden in files")
    t.add_argument("files", nargs="+")

    e = sub.add_parser("encrypt", help="encrypt files with the chaotic cipher")
    e.add_argument("files", nargs="+")
    e.add_argument("--no-aes", action="store_true", help="thesis cascade only, without AES-GCM armour")

    d = sub.add_parser("decrypt", help="decrypt .vmk files")
    d.add_argument("files", nargs="+")
    d.add_argument("--out", default=None)

    args = ap.parse_args(argv)
    settings = Settings.load()
    ledger = Ledger()
    rc = 0

    if args.cmd in ("embed", "protect"):
        if not args.text and not args.to:
            ap.error("give the watermark text with --text (and optionally --to)")
        settings.visible_footer = args.footer
        for f in args.files:
            try:
                r = protect_file(f, args.to, args.note, message=args.text, settings=settings, ledger=ledger,
                                 output_dir=args.out)
                hop = "added to existing watermark history" if r.reshared else "new watermark"
                print(f"[ok] {r.output}  ({hop}; layers: {', '.join(r.report.applied())})")
            except Exception as exc:  # noqa: BLE001 - report per file and continue
                print(f"[failed] {f}: {exc}")
                rc = 1
    elif args.cmd in ("extract", "trace"):
        for f in args.files:
            rep = trace_file(f, settings=settings, ledger=ledger)
            print(f"\n== {f}\n{rep.headline}")
            if rep.message:
                print(f"Watermark text: {rep.message}")
            if rep.owner:
                print(f"Owner: {rep.owner} {('/ ' + rep.organization) if rep.organization else ''}")
            for c in rep.chain:
                print(f"  {c.step}. {c.message or '-':40s} {c.recipient or '-':25s} {c.timestamp}")
            for layer, ok, detail in rep.layer_status:
                print(f"  [{'x' if ok else ' '}] {layer}  {detail}")
    elif args.cmd == "encrypt":
        pw = _password(confirm=True)
        for f in args.files:
            print(f"[ok] {encrypt_file(f, pw, aes_armour=not args.no_aes)}")
    elif args.cmd == "decrypt":
        pw = _password(confirm=False)
        for f in args.files:
            try:
                print(f"[ok] {decrypt_file(f, pw, args.out)}")
            except DecryptionError as exc:
                print(f"[failed] {f}: {exc}")
                rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
