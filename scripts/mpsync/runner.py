"""Drive the MemPalace CLI (`mine`, `status`) and parse its output."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("mpsync")

_STATUS_TOTAL = re.compile(r"MemPalace Status\s*--\s*(\d+)\s+drawers")
_STATUS_WING = re.compile(r"^\s*WING:\s*(\S+)")
_STATUS_ROOM = re.compile(r"^\s*ROOM:\s*(.+?)\s+(\d+)\s+drawers")
_MINE_FILE = re.compile(r"^\s*\+\s*\[\s*\d+/\d+\]\s+(.+?)\s+\+(\d+)\s*$")
_MINE_DRY_FILE = re.compile(r"^\s*\[DRY RUN\]\s+(.+?)\s+->\s+room:\S+\s+\((\d+) drawers\)")
_MINE_PROCESSED = re.compile(r"Files processed:\s*(\d+)")
_MINE_SKIPPED = re.compile(r"Files skipped[^:]*:\s*(\d+)")
_MINE_DRAWERS = re.compile(r"Drawers filed:\s*(\d+)")
LOCK_HELD_MARKER = "is held by"


@dataclass
class MineResult:
    ok: bool
    locked: bool = False
    processed: int = 0
    skipped: int = 0
    drawers: int = 0
    files: List[Tuple[str, int]] = field(default_factory=list)
    output: str = ""


def parse_status(text: str) -> Dict[str, int]:
    """{wing: drawers, ..., "_total": n}."""
    wings: Dict[str, int] = {}
    current = None
    for line in text.splitlines():
        m = _STATUS_WING.match(line)
        if m:
            current = m.group(1)
            wings.setdefault(current, 0)
            continue
        m = _STATUS_ROOM.match(line)
        if m and current:
            wings[current] += int(m.group(2))
    m = _STATUS_TOTAL.search(text)
    wings["_total"] = int(m.group(1)) if m else sum(wings.values())
    return wings


def parse_mine(text: str) -> MineResult:
    res = MineResult(ok=True, output=text)
    for line in text.splitlines():
        m = _MINE_FILE.match(line) or _MINE_DRY_FILE.match(line)
        if m:
            res.files.append((m.group(1).strip(), int(m.group(2))))
    for attr, rx in (("processed", _MINE_PROCESSED), ("skipped", _MINE_SKIPPED), ("drawers", _MINE_DRAWERS)):
        m = rx.search(text)
        if m:
            setattr(res, attr, int(m.group(1)))
    return res


class Runner:
    def __init__(self, cmd: List[str], palace: str, agent: str, timeout: int):
        self.cmd = list(cmd)
        self.palace = palace
        self.agent = agent
        self.timeout = timeout

    def _run(self, args: List[str], timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        full = self.cmd + ["--palace", self.palace] + args
        log.debug("run: %s", " ".join(full))
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        return subprocess.run(
            full,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout or self.timeout,
            # Under pythonw.exe (scheduled task) don't flash a console per call.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def status(self) -> Dict[str, int]:
        proc = self._run(["status"], timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(f"mempalace status failed: {proc.stderr.strip()[-500:]}")
        return parse_status(proc.stdout)

    def mine(self, path: str, mode: str, wing: str, dry_run: bool = False) -> MineResult:
        args = ["mine", path, "--mode", mode, "--wing", wing, "--agent", self.agent]
        if dry_run:
            args.append("--dry-run")
        try:
            proc = self._run(args)
        except subprocess.TimeoutExpired as exc:
            return MineResult(ok=False, output=f"timeout after {exc.timeout}s")
        text = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        res = parse_mine(text)
        if proc.returncode != 0:
            res.ok = False
            res.locked = LOCK_HELD_MARKER in (proc.stderr or "")
        log.debug("mine output:\n%s", text)
        return res
