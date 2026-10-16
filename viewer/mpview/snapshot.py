"""Consistent, read-only copies of the palace.

Opening a Chroma palace — even to search — writes to ``chroma.sqlite3`` and may
rename HNSW segment folders, so the viewer never opens the live palace. It
copies it instead, and only while no writer holds MemPalace's palace lock:

1. the lock is free (same probe the sync uses);
2. fingerprint every file (relative path, size, mtime);
3. copy the folder to ``<snapshot_dir>/snap-<timestamp>``;
4. the lock is still free and the fingerprint is unchanged — otherwise the
   copy is discarded and retried.

The live palace is only ever read by ``shutil.copy2``. Older snapshots are
pruned best-effort (a search subprocess may still hold files open on Windows).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, Optional, Tuple

from mpsync import lock

META = "snapshot.json"
PREFIX = "snap-"

Fingerprint = Dict[str, Tuple[int, int]]


class SnapshotError(RuntimeError):
    pass


class PalaceBusy(SnapshotError):
    """A writer held the palace lock, or the palace changed during the copy."""


@dataclass
class Snapshot:
    path: str          # the copied palace folder
    taken_at: str      # ISO timestamp, local time
    source: str        # the live palace it came from
    files: int
    bytes: int

    @property
    def db(self) -> str:
        return os.path.join(self.path, "chroma.sqlite3")


def fingerprint(palace: str) -> Fingerprint:
    out: Fingerprint = {}
    for root, _dirs, files in os.walk(palace):
        for name in files:
            full = os.path.join(root, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            out[os.path.relpath(full, palace)] = (st.st_size, st.st_mtime_ns)
    return out


def current(snapshot_dir: str) -> Optional[Snapshot]:
    try:
        with open(os.path.join(snapshot_dir, META), encoding="utf-8") as f:
            meta = json.load(f)
        snap = Snapshot(**meta)
    except (OSError, ValueError, TypeError):
        return None
    return snap if os.path.isfile(snap.db) else None


def _write_meta(snapshot_dir: str, snap: Snapshot) -> None:
    tmp = os.path.join(snapshot_dir, META + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap.__dict__, f, indent=2)
    os.replace(tmp, os.path.join(snapshot_dir, META))


def prune(snapshot_dir: str, keep: str) -> None:
    for name in os.listdir(snapshot_dir):
        full = os.path.join(snapshot_dir, name)
        if name.startswith(PREFIX) and os.path.isdir(full) and os.path.normcase(full) != os.path.normcase(keep):
            shutil.rmtree(full, ignore_errors=True)


def take(
    palace: str,
    snapshot_dir: str,
    lock_file: Optional[str] = None,
    retries: int = 3,
    retry_delay: float = 2.0,
    is_locked: Callable[[str], bool] = lock.is_locked,
    copy: Callable[[str, str], object] = shutil.copytree,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = datetime.now,
) -> Snapshot:
    """Copy ``palace`` into a fresh snapshot; raise PalaceBusy if it never held still."""
    if not os.path.isfile(os.path.join(palace, "chroma.sqlite3")):
        raise SnapshotError(f"no chroma.sqlite3 in {palace} (only the Chroma backend is supported)")
    lock_file = lock_file or lock.lock_path(palace)
    os.makedirs(snapshot_dir, exist_ok=True)
    for attempt in range(retries):
        if attempt:
            sleep(retry_delay)
        if is_locked(lock_file):
            continue
        before = fingerprint(palace)
        stamp = now()
        dest = os.path.join(snapshot_dir, PREFIX + stamp.strftime("%Y%m%d-%H%M%S-%f"))
        try:
            copy(palace, dest)
        except (OSError, shutil.Error):
            shutil.rmtree(dest, ignore_errors=True)
            continue
        if is_locked(lock_file) or fingerprint(palace) != before:
            shutil.rmtree(dest, ignore_errors=True)
            continue
        snap = Snapshot(
            path=dest,
            taken_at=stamp.isoformat(timespec="seconds"),
            source=palace,
            files=len(before),
            bytes=sum(size for size, _ in before.values()),
        )
        _write_meta(snapshot_dir, snap)
        prune(snapshot_dir, keep=dest)
        return snap
    raise PalaceBusy(f"palace busy (lock held or files changing) after {retries} attempts")
