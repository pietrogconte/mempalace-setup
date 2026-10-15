"""One sync run: agents/folders, then the export inbox, then the report."""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import shutil
import sys
import tempfile
from typing import Dict, List, Optional

from . import lock, normalize, staging
from .config import Config, Source
from .report import ExportEntry, Report, SourceEntry, WikiIndex
from .runner import MineResult, Runner

log = logging.getLogger("mpsync")


# --------------------------------------------------------------------------
# State / logging
# --------------------------------------------------------------------------

def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def setup_logging(log_dir: str, verbose: bool, today: str) -> str:
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"mempalace-sync-{today}.log")
    logger = logging.getLogger("mpsync")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG if verbose else logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    if sys.stderr is not None:  # None under pythonw.exe
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(logging.DEBUG if verbose else logging.INFO)
        ch.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(ch)
    return log_file


# --------------------------------------------------------------------------
# Mining with the one-writer rule
# --------------------------------------------------------------------------

class Syncer:
    def __init__(self, cfg: Config, runner: Runner, dry_run: bool, report: Report):
        self.cfg = cfg
        self.runner = runner
        self.dry_run = dry_run
        self.report = report
        self.lock_file = lock.lock_path(cfg.palace)

    def mine(self, path: str, mode: str, wing: str, entry: SourceEntry) -> Optional[MineResult]:
        if not self.dry_run:  # MemPalace takes no lock on --dry-run either
            free = lock.wait_until_free(
                self.lock_file, self.cfg.lock_policy, self.cfg.lock_wait_seconds, self.cfg.lock_poll_seconds
            )
            if not free:
                entry.status, entry.detail = "skipped", f"palace lock held by another writer (policy {self.cfg.lock_policy})"
                log.warning("%s: %s", entry.name, entry.detail)
                return None
        log.info("mine %s (%s, wing %s)%s", path, mode, wing, " [dry-run]" if self.dry_run else "")
        res = self.runner.mine(path, mode, wing, dry_run=self.dry_run)
        if res.locked:
            entry.status, entry.detail = "skipped", "palace lock taken by another writer during mine"
            log.warning("%s: %s", entry.name, entry.detail)
            return None
        if not res.ok:
            entry.status = "error"
            entry.detail = (res.output.strip().splitlines() or ["mine failed"])[-1][:300]
            log.error("%s: mine failed: %s", entry.name, entry.detail)
            return None
        entry.processed, entry.skipped, entry.drawers = res.processed, res.skipped, res.drawers
        entry.files = [f for f in res.files if f[1] > 0]
        log.info("%s: %d files, %d drawers, %d already mined", entry.name, res.processed, res.drawers, res.skipped)
        return res

    # -- sources -------------------------------------------------------
    def run_source(self, src: Source) -> None:
        entry = SourceEntry(src.name, src.wing, src.mode)
        self.report.sources.append(entry)
        if not os.path.isdir(src.path):
            entry.status = "missing"
            log.info("%s: %s does not exist, skipping", src.name, src.path)
            return
        if not src.staged:
            if src.mode == "projects":
                risky = staging.find_sensitive(src.path)
                if risky:
                    entry.status = "error"
                    entry.detail = (
                        f"{len(risky)} sensitive-looking file(s) (e.g. {risky[0]}); "
                        "add include/exclude so it is mined from staging"
                    )
                    log.error("%s: %s", src.name, entry.detail)
                    return
            self.mine(src.path, src.mode, src.wing, entry)
            if self.dry_run and src.mode == "projects" and entry.status == "ok":
                self.report.notes.append(
                    f"{src.name}: MemPalace's projects-mode --dry-run does not check what is already "
                    "mined, so its counts are an upper bound; files with an unchanged mtime are "
                    "skipped in a real run."
                )
            return

        if self.dry_run:
            tmp = tempfile.mkdtemp(prefix=f"mpsync-preview-{src.name}-")
            try:
                entry.staging = staging.build(src, tmp, write=True)
                self.mine(tmp, src.mode, src.wing, entry)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            return
        out = os.path.join(self.cfg.staging, src.name)
        try:
            entry.staging = staging.build(src, out, write=True)
        except (OSError, RuntimeError) as exc:
            entry.status, entry.detail = "error", f"staging failed: {exc}"
            log.error("%s: %s", src.name, entry.detail)
            return
        self.mine(out, src.mode, src.wing, entry)

    # -- inbox ---------------------------------------------------------
    def run_inbox(self, state: dict) -> None:
        exports_state = state.setdefault("exports", {})
        zips = []
        if os.path.isdir(self.cfg.inbox):
            zips = sorted(
                os.path.join(self.cfg.inbox, f) for f in os.listdir(self.cfg.inbox) if f.lower().endswith(".zip")
            )
        touched = set()
        for z in zips:
            entry = ExportEntry(os.path.basename(z))
            self.report.exports.append(entry)
            try:
                with normalize.ExtractedExport(z) as root:
                    provider, raw = normalize.load_conversations(root)
            except (OSError, ValueError) as exc:
                entry.status, entry.detail = "error", f"could not read: {exc}"
                log.error("%s: %s", entry.zip_name, entry.detail)
                continue
            target = self.cfg.exports.get(provider or "")
            if not provider or not target:
                entry.status = "skipped"
                entry.detail = "no conversations found" if not provider else f"no [exports.{provider}] in config"
                log.warning("%s: %s", entry.zip_name, entry.detail)
                continue
            entry.provider = provider
            pstate = exports_state.setdefault(provider, {})
            convs = normalize.to_conversations(provider, raw)
            res = normalize.normalize_export(convs, target.normalized_dir, pstate, dry_run=self.dry_run)
            entry.changed = res.changed
            entry.counts = {
                "new": len(res.new), "updated": len(res.updated), "unchanged": res.unchanged,
                "adopted": res.adopted, "no_text": res.skipped_empty,
            }
            log.info("%s (%s): %s", entry.zip_name, provider, entry.counts)

            mine_entry = SourceEntry(f"export:{provider}", target.wing)
            if self.dry_run:
                entry.detail = "dry-run: not normalized/mined"
                continue
            mine_entry.name += f" ({entry.zip_name})"
            self.report.sources.append(mine_entry)
            touched.add(provider)
            self.mine(target.normalized_dir, "convos", target.wing, mine_entry)
            if mine_entry.status == "ok":
                os.makedirs(self.cfg.processed, exist_ok=True)
                dest = os.path.join(self.cfg.processed, entry.zip_name)
                stem, ext = os.path.splitext(dest)
                n = 1
                while os.path.exists(dest):
                    dest = f"{stem}-{n}{ext}"
                    n += 1
                shutil.move(z, dest)
                entry.detail = f"→ {os.path.relpath(dest, self.cfg.inbox)}"
            else:
                entry.status, entry.detail = mine_entry.status, "zip kept in inbox: " + mine_entry.detail

        # Re-mine export folders not touched above (idempotent; catches a
        # previous run whose mine was skipped because of the lock).
        for provider, target in self.cfg.exports.items():
            if provider in touched or not os.path.isdir(target.normalized_dir):
                continue
            mine_entry = SourceEntry(f"export:{provider}", target.wing)
            self.report.sources.append(mine_entry)
            self.mine(target.normalized_dir, "convos", target.wing, mine_entry)


def run(cfg: Config, runner: Runner, dry_run: bool = False, only: Optional[List[str]] = None,
        lang: str = "pt", today: Optional[str] = None) -> int:
    today = today or _dt.date.today().isoformat()
    report = Report(date=today, dry_run=dry_run, lang=lang)
    state = load_state(cfg.state_file)
    syncer = Syncer(cfg, runner, dry_run, report)
    log.info("mempalace-sync start%s (palace %s)", " [dry-run]" if dry_run else "", cfg.palace)

    try:
        report.before = runner.status()
    except Exception as exc:  # status is informative only
        report.notes.append(f"status (before) failed: {exc}")

    for src in cfg.sources:
        if not src.enabled or (only and src.name not in only):
            continue
        syncer.run_source(src)
    if not only or "inbox" in only:
        syncer.run_inbox(state)

    if not dry_run:
        try:
            report.after = runner.status()
        except Exception as exc:
            report.notes.append(f"status (after) failed: {exc}")
        state["last_run"] = _dt.datetime.now().isoformat(timespec="seconds")
        save_state(cfg.state_file, state)

    os.makedirs(cfg.reports, exist_ok=True)
    base = f"{today}{'-dry-run' if dry_run else ''}"
    path = os.path.join(cfg.reports, base + ".md")
    n = 2
    while not dry_run and os.path.exists(path):  # never overwrite an earlier real run
        path = os.path.join(cfg.reports, f"{base}-{n}.md")
        n += 1
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(report.render(WikiIndex(cfg.wiki_sources)))
    log.info("report: %s", path)
    return 1 if report.has_errors else 0
