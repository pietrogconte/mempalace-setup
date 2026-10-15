"""Build a filtered, converted copy of a source folder for mining.

The staging tree mirrors the source's relative layout. Converted files get a
``.md`` suffix appended (``aula.html`` -> ``aula.html.md``). A file is only
rewritten when its content changed, so its mtime - which MemPalace uses for
idempotency - stays put across runs. Files that no longer come out of the
source are removed from staging.
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

from .config import Source
from .convert import converter_for

log = logging.getLogger("mpsync")

MARKER = ".mpsync-staging"

DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", ".env", "node_modules", "__pycache__",
    ".ipynb_checkpoints", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    ".idea", ".vscode", ".obsidian", ".trash",
}
# Never copied, whatever include says.
SENSITIVE_PATTERNS = [
    ".env", ".env.*", "*.env", ".envrc", ".netrc", ".pgpass", ".npmrc", ".pypirc",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.kdbx", "*.keystore", "*.jks",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    "*credential*", "*credencia*", "*secret*", "*senha*", "*password*",
    "*token*.json", "service-account*.json",
]
BINARY_EXTENSIONS = {
    ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".pdf", ".docx", ".doc",
    ".pptx", ".ppt", ".xlsx", ".xls", ".odt", ".png", ".jpg", ".jpeg", ".gif",
    ".bmp", ".ico", ".webp", ".mp3", ".mp4", ".wav", ".mov", ".avi", ".exe",
    ".dll", ".so", ".dylib", ".pyc", ".pyo", ".whl", ".pkl", ".pickle", ".npy",
    ".npz", ".h5", ".parquet", ".db", ".sqlite", ".sqlite3", ".bin", ".onnx",
    ".pt", ".pth", ".ckpt", ".safetensors", ".ttf", ".otf", ".woff", ".woff2",
}


def _match(name: str, rel: str, patterns: List[str]) -> bool:
    name_l, rel_l = name.lower(), rel.lower()
    for p in patterns:
        p_l = p.lower()
        target = rel_l if "/" in p_l else name_l
        if fnmatch.fnmatchcase(target, p_l):
            return True
    return False


def is_sensitive(name: str) -> bool:
    return _match(name, name, SENSITIVE_PATTERNS)


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _utf16_tail_ok(tail: bytes) -> bool:
    """Looks like UTF-16LE text: (nearly) every odd byte is NUL, even bytes are not."""
    odd, even = tail[1::2], tail[0::2]
    if len(odd) < 2:
        return False
    return odd.count(0) / len(odd) >= 0.9 and even.count(0) / max(1, len(even)) <= 0.05


def decode_utf16(data: bytes) -> Optional[bytes]:
    """UTF-8 bytes for UTF-16 text, else None.

    Handles a BOM, BOM-less UTF-16LE, and a UTF-8 head followed by a UTF-16LE
    tail - what `echo ... >> file` in Windows PowerShell 5 appends to a UTF-8 file.
    """
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16").encode("utf-8")
        except UnicodeDecodeError:
            return None
    nul = data.find(b"\x00")
    if nul < 1:
        return None
    head, tail = data[: nul - 1], data[nul - 1:]
    if len(tail) % 2:
        tail = tail[:-1]
    if not _utf16_tail_ok(tail):
        return None
    try:
        text = head.decode("utf-8") + tail.decode("utf-16-le")
    except UnicodeDecodeError:
        return None
    return text.replace("\r\n", "\n").encode("utf-8")


def walk(root: str, exclude: List[str]) -> Iterator[Tuple[str, str]]:
    """Yield (abs_path, posix_rel_path) skipping default/excluded directories."""
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in DEFAULT_EXCLUDE_DIRS
            and not d.endswith(".egg-info")
            and not _match(d, rel_dir + d, exclude)
        )
        for fn in sorted(filenames):
            yield os.path.join(dirpath, fn), rel_dir + fn


def find_sensitive(root: str) -> List[str]:
    """Sensitive-looking files MemPalace would see if `root` were mined in place."""
    return [rel for _, rel in walk(root, []) if is_sensitive(os.path.basename(rel))]


@dataclass
class StagedFile:
    rel_src: str
    rel_out: str
    size: int
    sha256: str
    converted: bool
    changed: bool = False


@dataclass
class StagingResult:
    files: List[StagedFile] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    removed: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)

    def duplicates(self) -> List[List[StagedFile]]:
        groups: Dict[str, List[StagedFile]] = defaultdict(list)
        for f in self.files:
            groups[f.sha256].append(f)
        return [g for g in groups.values() if len(g) > 1]

    def largest(self, n: int = 10) -> List[StagedFile]:
        return sorted(self.files, key=lambda f: f.size, reverse=True)[:n]


def _select(src: Source, name: str, rel: str) -> Optional[str]:
    """Return a skip reason, or None if the file is kept."""
    if is_sensitive(name):
        return "sensitive"
    if _match(name, rel, src.exclude):
        return "excluded"
    if src.include and not _match(name, rel, src.include):
        return "not-included"
    if os.path.splitext(name)[1].lower() in BINARY_EXTENSIONS:
        return "binary"
    return None


def build(src: Source, out_root: str, write: bool = True) -> StagingResult:
    """Stage `src` into `out_root`. With write=False nothing touches the disk."""
    res = StagingResult()
    produced = set()
    if write:
        if os.path.isdir(out_root) and os.listdir(out_root) and not os.path.exists(os.path.join(out_root, MARKER)):
            raise RuntimeError(f"{out_root} exists, is not empty and was not created by mempalace-sync")
        os.makedirs(out_root, exist_ok=True)
        open(os.path.join(out_root, MARKER), "a").close()

    for abs_path, rel in walk(src.path, src.exclude):
        name = os.path.basename(rel)
        reason = _select(src, name, rel)
        if reason:
            res.skipped[reason] += 1
            continue
        try:
            with open(abs_path, "rb") as f:
                raw = f.read()
        except OSError as exc:
            res.errors.append(f"{rel}: {exc}")
            continue
        if not raw.strip():
            res.skipped["empty"] += 1
            continue
        if _looks_binary(raw) or raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            raw = decode_utf16(raw) or raw
        conv = converter_for(name, src.convert)
        if conv:
            try:
                data = conv(raw.decode("utf-8", errors="replace")).encode("utf-8")
            except (ValueError, KeyError, TypeError) as exc:
                res.errors.append(f"{rel}: conversion failed: {exc}")
                continue
            rel_out = rel + ".md"
        else:
            if _looks_binary(raw):
                res.skipped["binary"] += 1
                continue
            data, rel_out = raw, rel
        if not data.strip():
            res.skipped["empty"] += 1
            continue
        sf = StagedFile(rel, rel_out, len(data), hashlib.sha256(data).hexdigest(), bool(conv))
        out_path = os.path.join(out_root, *rel_out.split("/"))
        produced.add(os.path.normcase(os.path.abspath(out_path)))
        try:
            with open(out_path, "rb") as f:
                sf.changed = f.read() != data
        except OSError:
            sf.changed = True
        if write and sf.changed:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(data)
        res.files.append(sf)

    if write:
        for dirpath, dirnames, filenames in os.walk(out_root, topdown=False):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                if fn == MARKER and dirpath == out_root:
                    continue
                if os.path.normcase(os.path.abspath(p)) not in produced:
                    os.remove(p)
                    res.removed.append(os.path.relpath(p, out_root).replace(os.sep, "/"))
            if dirpath != out_root and not os.listdir(dirpath):
                os.rmdir(dirpath)
    log.info(
        "staged %s: %d files (%d changed), skipped %s",
        src.name, len(res.files), sum(f.changed for f in res.files), dict(res.skipped),
    )
    return res
