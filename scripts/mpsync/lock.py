"""Probe MemPalace's per-palace writer lock without holding it.

MemPalace serializes writers with a non-blocking lock on
``~/.mempalace/locks/mine_palace_<sha256(normcase(realpath(palace)))[:16]>.lock``
(byte 0 via msvcrt on Windows, flock elsewhere). We take and immediately
release the same lock to see whether another writer (a hook-spawned mine, an
MCP server) holds it. The probe is advisory: the mine itself still fails
cleanly with "is held by" if someone grabs the lock in between.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Callable, Optional


def lock_path(palace: str, home: Optional[str] = None) -> str:
    resolved = os.path.realpath(os.path.expanduser(palace))
    key = hashlib.sha256(os.path.normcase(resolved).encode()).hexdigest()[:16]
    home = home or os.path.expanduser("~")
    return os.path.join(home, ".mempalace", "locks", f"mine_palace_{key}.lock")


def is_locked(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        f = open(path, "r+b")
    except OSError:
        return True
    with f:
        f.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            return False
        import fcntl

        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
        return False


def wait_until_free(
    path: str,
    policy: str,
    wait_seconds: int,
    poll_seconds: int,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """True when the lock is free; False when we gave up (policy skip or timeout)."""
    if not is_locked(path):
        return True
    if policy == "skip":
        return False
    deadline = clock() + wait_seconds
    while clock() < deadline:
        sleep(poll_seconds)
        if not is_locked(path):
            return True
    return False
