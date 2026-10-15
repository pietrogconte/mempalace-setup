"""Markdown run report. Reads the wiki's sources folder; never writes to it."""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .normalize import Conversation
from .staging import StagingResult

STRINGS = {
    "pt": {
        "title": "Relatório mempalace-sync",
        "dry": "SIMULAÇÃO (--dry-run): nada foi gravado no palace",
        "status": "Status do palace",
        "wing": "Wing", "before": "Antes", "after": "Depois", "delta": "Δ",
        "sources": "Fontes",
        "files": "arquivos", "drawers": "drawers", "skipped_already": "já minerados",
        "skipped": "PULADA", "error": "ERRO", "missing": "pasta não existe — ignorada",
        "exports": "Exports (inbox)",
        "new": "novas", "updated": "atualizadas", "unchanged": "inalteradas",
        "adopted": "já existentes adotadas", "no_text": "sem texto",
        "curation": "Possível curadoria na wiki",
        "curation_hint": "Conteúdo novo/atualizado que já tem página em `wiki/sources/` — a página pode estar desatualizada.",
        "no_page": "Sem página na wiki (candidatos a Ingest)",
        "none": "nada",
        "staging": "Staging",
        "largest": "10 maiores arquivos",
        "dups": "Duplicatas (mesmo conteúdo)",
        "removed": "removidos do staging",
        "skips": "Pulados por motivo",
        "notes": "Avisos",
        "zip_moved": "movido para",
    },
    "en": {
        "title": "mempalace-sync report",
        "dry": "DRY RUN (--dry-run): nothing was written to the palace",
        "status": "Palace status",
        "wing": "Wing", "before": "Before", "after": "After", "delta": "Δ",
        "sources": "Sources",
        "files": "files", "drawers": "drawers", "skipped_already": "already mined",
        "skipped": "SKIPPED", "error": "ERROR", "missing": "folder does not exist — ignored",
        "exports": "Exports (inbox)",
        "new": "new", "updated": "updated", "unchanged": "unchanged",
        "adopted": "existing adopted", "no_text": "no text",
        "curation": "Wiki pages that may need curation",
        "curation_hint": "New/updated content that already has a page in `wiki/sources/` — the page may be stale.",
        "no_page": "No wiki page yet (Ingest candidates)",
        "none": "nothing",
        "staging": "Staging",
        "largest": "10 largest files",
        "dups": "Duplicates (same content)",
        "removed": "removed from staging",
        "skips": "Skipped by reason",
        "notes": "Warnings",
        "zip_moved": "moved to",
    },
}


@dataclass
class SourceEntry:
    name: str
    wing: str
    mode: str = "convos"
    status: str = "ok"  # ok | skipped | error | missing
    detail: str = ""
    processed: int = 0
    skipped: int = 0
    drawers: int = 0
    files: List[Tuple[str, int]] = field(default_factory=list)
    staging: Optional[StagingResult] = None


@dataclass
class ExportEntry:
    zip_name: str
    provider: str = ""
    status: str = "ok"
    detail: str = ""
    changed: List[Conversation] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)


class WikiIndex:
    """Plain-text search over wiki/sources/*.md (read-only)."""

    def __init__(self, folder: str):
        self.pages: Dict[str, str] = {}
        if folder and os.path.isdir(folder):
            for p in glob.glob(os.path.join(glob.escape(folder), "**", "*.md"), recursive=True):
                try:
                    with open(p, encoding="utf-8") as f:
                        self.pages[os.path.relpath(p, folder).replace(os.sep, "/")] = f.read()
                except OSError:
                    pass

    def find(self, needle: str) -> List[str]:
        if not needle or len(needle) < 6:
            return []
        rx = re.compile(r"(?<![0-9A-Za-z])" + re.escape(needle) + r"(?![0-9A-Za-z])", re.I)
        return sorted(name for name, text in self.pages.items() if rx.search(text))


@dataclass
class Report:
    date: str
    dry_run: bool
    lang: str = "pt"
    before: Dict[str, int] = field(default_factory=dict)
    after: Dict[str, int] = field(default_factory=dict)
    sources: List[SourceEntry] = field(default_factory=list)
    exports: List[ExportEntry] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(e.status == "error" for e in self.sources + self.exports)

    def render(self, wiki: WikiIndex) -> str:
        t = STRINGS.get(self.lang, STRINGS["en"])
        out = [f"# {t['title']} — {self.date}", ""]
        if self.dry_run:
            out += [f"> **{t['dry']}**", ""]

        out += [f"## {t['status']}", "", f"| {t['wing']} | {t['before']} | {t['after']} | {t['delta']} |", "|---|---:|---:|---:|"]
        wings = sorted(set(self.before) | set(self.after), key=lambda w: (w == "_total", w))
        for w in wings:
            b, a = self.before.get(w), self.after.get(w)
            d = ""
            if self.before and self.after:
                diff = (a or 0) - (b or 0)
                d = f"{diff:+d}" if diff else "0"
            label = "**total**" if w == "_total" else f"`{w}`"
            out.append(f"| {label} | {'' if b is None else b} | {'' if a is None else a} | {d} |")
        out.append("")

        out += [f"## {t['sources']}", ""]
        for s in self.sources:
            if s.status == "missing":
                out.append(f"- **{s.name}** → `{s.wing}`: {t['missing']}")
                continue
            if s.status in ("skipped", "error"):
                out.append(f"- **{s.name}** → `{s.wing}`: **{t[s.status]}** — {s.detail}")
                continue
            out.append(
                f"- **{s.name}** → `{s.wing}`: {s.processed} {t['files']}, "
                f"{s.drawers} {t['drawers']}, {s.skipped} {t['skipped_already']}"
            )
            for name, n in s.files:
                out.append(f"  - `{name}` (+{n})")
            st = s.staging
            if st is not None:
                out.append(
                    f"  - {t['staging']}: {len(st.files)} {t['files']}, {st.total_bytes / 1e6:.1f} MB; "
                    f"{t['skips']}: {dict(st.skipped) or '-'}"
                    + (f"; {len(st.removed)} {t['removed']}" if st.removed else "")
                )
                if self.dry_run:
                    out.append(f"  - {t['largest']}:")
                    for f in st.largest(10):
                        out.append(f"    - {f.size / 1e3:,.0f} kB — `{f.rel_out}`")
                dups = st.duplicates()
                if dups:
                    out.append(f"  - {t['dups']}:")
                    for g in dups:
                        out.append("    - " + " = ".join(f"`{f.rel_src}`" for f in g))
                for e in st.errors:
                    out.append(f"  - {t['error']}: {e}")
        out.append("")

        if self.exports:
            out += [f"## {t['exports']}", ""]
            for e in self.exports:
                if e.status != "ok":
                    out.append(f"- `{e.zip_name}`: **{t.get(e.status, e.status)}** — {e.detail}")
                    continue
                c = e.counts
                out.append(
                    f"- `{e.zip_name}` ({e.provider}): {c.get('new', 0)} {t['new']}, {c.get('updated', 0)} {t['updated']}, "
                    f"{c.get('unchanged', 0)} {t['unchanged']}, {c.get('adopted', 0)} {t['adopted']}, "
                    f"{c.get('no_text', 0)} {t['no_text']}" + (f"; {e.detail}" if e.detail else "")
                )
            out.append("")

        curation: List[str] = []
        no_page: List[str] = []
        for e in self.exports:
            for conv in e.changed:
                pages = wiki.find(conv.id[:8])
                line = f"`{conv.id[:8]}` {conv.title} ({conv.updated})"
                if pages:
                    curation.append(f"- {line} → " + ", ".join(f"`{p}`" for p in pages))
                else:
                    no_page.append(f"- {line}")
        for s in self.sources:
            if s.mode != "convos":  # file names of folders match wiki text too loosely
                continue
            for name, _ in s.files:
                stem = os.path.basename(name).split(".")[0]
                pages = wiki.find(stem)
                if pages:
                    curation.append(f"- `{s.wing}`: `{name}` → " + ", ".join(f"`{p}`" for p in pages))
        out += [f"## {t['curation']}", "", t["curation_hint"], ""]
        out += curation or [f"- {t['none']}"]
        out.append("")
        if no_page:
            out += [f"## {t['no_page']}", ""] + no_page + [""]
        if self.notes:
            out += [f"## {t['notes']}", ""] + [f"- {n}" for n in self.notes] + [""]
        return "\n".join(out)
