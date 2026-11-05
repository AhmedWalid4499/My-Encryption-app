"""Distribution ledger: every protected copy that leaves your hands is logged here.

If a leaked file only carries the tiny invisible tokens (because the encrypted
record was stripped), the hop IDs in those tokens are looked up in this ledger
to name the recipient.
"""

from __future__ import annotations

import csv
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .settings import data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS issues (
    hop_id      TEXT PRIMARY KEY,
    doc_id      TEXT NOT NULL,
    parent_hop  TEXT,
    recipient   TEXT NOT NULL,
    note        TEXT,
    owner       TEXT,
    issued_by   TEXT,
    source_file TEXT,
    output_file TEXT,
    timestamp   TEXT
);
CREATE INDEX IF NOT EXISTS idx_issues_doc ON issues(doc_id);
"""


@dataclass
class Issue:
    hop_id: str
    doc_id: str
    parent_hop: Optional[str]
    recipient: str
    note: str
    owner: str
    issued_by: str
    source_file: str
    output_file: str
    timestamp: str


class Ledger:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else data_dir() / "ledger.db"
        with closing(self._conn()) as conn, conn:
            conn.executescript(SCHEMA)

    def _conn(self):
        return sqlite3.connect(self.path)

    def add(self, issue: Issue) -> None:
        with closing(self._conn()) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO issues VALUES (?,?,?,?,?,?,?,?,?,?)", (
                issue.hop_id, issue.doc_id, issue.parent_hop, issue.recipient, issue.note,
                issue.owner, issue.issued_by, issue.source_file, issue.output_file, issue.timestamp))

    def get(self, hop_id: str) -> Optional[Issue]:
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT * FROM issues WHERE hop_id=?", (hop_id,)).fetchone()
        return Issue(*row) if row else None

    def for_document(self, doc_id: str) -> List[Issue]:
        with closing(self._conn()) as conn:
            rows = conn.execute("SELECT * FROM issues WHERE doc_id=? ORDER BY timestamp", (doc_id,)).fetchall()
        return [Issue(*r) for r in rows]

    def search(self, text: str = "", limit: int = 2000) -> List[Issue]:
        like = f"%{text}%"
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM issues WHERE recipient LIKE ? OR note LIKE ? OR source_file LIKE ? "
                "OR doc_id LIKE ? OR hop_id LIKE ? ORDER BY timestamp DESC LIMIT ?",
                (like, like, like, like, like, limit)).fetchall()
        return [Issue(*r) for r in rows]

    def export_csv(self, dest: Path) -> int:
        rows = self.search("")
        with open(dest, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["Date (UTC)", "Recipient", "Note", "Original file", "Protected copy",
                        "Document ID", "Copy ID", "Shared from copy", "Owner", "Issued by"])
            for r in rows:
                w.writerow([r.timestamp, r.recipient, r.note, r.source_file, r.output_file,
                            r.doc_id, r.hop_id, r.parent_hop or "", r.owner, r.issued_by])
        return len(rows)
