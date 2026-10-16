"""Read the sync and curation reports (paths.reports) and the growth per wing.

Sync reports are ``<date>.md``, ``<date>-2.md``... (``<date>-dry-run.md`` for
simulations), each with a "Palace status" / "Status do palace" table whose
"after" column is the palace size per wing at the end of that run. Curation
reports (``curadoria-*`` / ``curation-*``) are only rendered.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

STATUS_HEADINGS = ("status do palace", "palace status")
_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_ROW = re.compile(r"^\|\s*`?([^|`*]+?)`?\s*\|\s*(-?\d+)\s*\|\s*(-?\d+)\s*\|")
_RUN = re.compile(r"^\d{4}-\d{2}-\d{2}-(\d+)\.md$")

SYNC, DRY_RUN, CURATION, OTHER = "sync", "dry-run", "curation", "other"


@dataclass
class ReportFile:
    path: str
    name: str
    kind: str
    date: str     # YYYY-MM-DD, or "" when the name has no date
    mtime: float

    @property
    def is_markdown(self) -> bool:
        return self.name.lower().endswith(".md")


def classify(name: str) -> Tuple[str, str]:
    lower = name.lower()
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    date = m.group(1) if m else ""
    if lower.startswith(("curadoria-", "curation-")):
        return CURATION, date
    if _DATE.match(name) and lower.endswith(".md"):
        return (DRY_RUN if "dry-run" in lower else SYNC), date
    return OTHER, date


def list_reports(folder: str) -> List[ReportFile]:
    if not folder or not os.path.isdir(folder):
        return []
    out = []
    for name in os.listdir(folder):
        full = os.path.join(folder, name)
        if not os.path.isfile(full) or name.startswith("."):
            continue
        kind, date = classify(name)
        out.append(ReportFile(full, name, kind, date, os.path.getmtime(full)))
    # newest first: by date in the name, then by modification time
    out.sort(key=lambda r: (r.date, r.mtime), reverse=True)
    return out


def parse_status(text: str) -> Optional[Dict[str, Tuple[int, int]]]:
    """wing -> (before, after) from the status table, or None if there is none."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("#") and line.lstrip("#").strip().lower() in STATUS_HEADINGS:
            start = i + 1
            break
    if start is None:
        return None
    out: Dict[str, Tuple[int, int]] = {}
    in_table = False
    for line in lines[start:]:
        if line.startswith("#"):
            break
        if not line.startswith("|"):
            if in_table:
                break
            continue
        in_table = True
        m = _ROW.match(line)
        if not m or "**" in line.split("|")[1]:
            continue  # header, separator or the bold total row
        out[m.group(1).strip()] = (int(m.group(2)), int(m.group(3)))
    return out


def _run_key(r: ReportFile) -> Tuple[int, float]:
    m = _RUN.match(r.name)
    return (int(m.group(1)) if m else 1, r.mtime)


def growth(reports: List[ReportFile], read=None) -> List[Tuple[str, Dict[str, int]]]:
    """[(date, {wing: drawers})], oldest first: per day, the last real run with a status table."""
    read = read or (lambda p: open(p, encoding="utf-8", errors="replace").read())
    by_day: Dict[str, List[ReportFile]] = {}
    for r in reports:
        if r.kind == SYNC and r.date:
            by_day.setdefault(r.date, []).append(r)
    out = []
    for day in sorted(by_day):
        for r in sorted(by_day[day], key=_run_key, reverse=True):
            status = parse_status(read(r.path))
            if status:
                out.append((day, {wing: after for wing, (_before, after) in status.items()}))
                break
    return out
