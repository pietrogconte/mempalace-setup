"""Normalize claude.ai / ChatGPT data exports into one transcript .md per conversation.

Output format (what MemPalace's convo miner reads verbatim, since it has
`>` user markers)::

    # <title>

    Fonte: claude.ai | conversa <uuid> | criada YYYY-MM-DD | atualizada YYYY-MM-DD | N mensagens

    > user turn
    assistant turn

File names are ``<created>_<id[:8]>_<slug>.md`` and stay stable per
conversation: once a conversation has a file, later exports rewrite that same
file (even if the title changed), and only when its content actually differs,
so MemPalace's mtime-based idempotency skips everything else.

Usable on its own:
    python scripts/mempalace_sync.py normalize <export.zip|dir|conversations.json> <out_dir>
"""

from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

Message = Tuple[str, str]

_TOOL_RESULT_MAX = 2048
_HEADER_UPDATED = re.compile(r"\|\s*atualizada\s+(\d{4}-\d{2}-\d{2})")


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def safe_extract(zip_path: str, dest: str) -> None:
    """Extract a zip refusing absolute paths and `..` (zip-slip)."""
    dest_real = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = os.path.realpath(os.path.join(dest, member.filename))
            if os.path.commonpath([target, dest_real]) != dest_real:
                raise ValueError(f"unsafe path in zip: {member.filename!r}")
        zf.extractall(dest)


def find_conversation_files(root: str) -> List[str]:
    if os.path.isfile(root):
        return [root]
    found = glob.glob(os.path.join(root, "**", "conversations*.json"), recursive=True)
    return sorted(found)


def detect_provider(conversations: list) -> Optional[str]:
    for c in conversations[:20]:
        if not isinstance(c, dict):
            continue
        if "chat_messages" in c:
            return "claude_ai"
        if isinstance(c.get("mapping"), dict):
            return "chatgpt"
    return None


def load_conversations(path: str) -> Tuple[Optional[str], list]:
    """Read every conversations*.json under `path` (file or extracted dir)."""
    convs: list = []
    for f in find_conversation_files(path):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data = data.get("conversations", [])
        if isinstance(data, list):
            convs.extend(data)
    return detect_provider(convs), convs


class ExtractedExport:
    """Context manager: zip -> fresh temp dir; dir/file -> used as is."""

    def __init__(self, path: str):
        self.path = path
        self._tmp: Optional[str] = None

    def __enter__(self) -> str:
        if zipfile.is_zipfile(self.path):
            self._tmp = tempfile.mkdtemp(prefix="mpsync-export-")
            safe_extract(self.path, self._tmp)
            return self._tmp
        return self.path

    def __exit__(self, *exc) -> None:
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# Message extraction
# --------------------------------------------------------------------------

def _block_text(content) -> str:
    """Text from a claude.ai message `content` (str, list of blocks or dict)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return str(content.get("text", "")).strip()
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            kind = item.get("type")
            if kind == "text":
                parts.append(item.get("text", ""))
            elif kind == "tool_use":
                summary = json.dumps(item.get("input", {}), ensure_ascii=False, separators=(",", ":"))
                if len(summary) > 200:
                    summary = summary[:200] + "..."
                parts.append(f"[{item.get('name', 'tool')}] {summary}")
            elif kind == "tool_result":
                text = _block_text(item.get("content", ""))
                if len(text) > _TOOL_RESULT_MAX:
                    text = text[:_TOOL_RESULT_MAX] + f"... [truncated, {len(text)} chars]"
                if text:
                    parts.append("→ " + text)
    return "\n".join(p for p in parts if p).strip()


def claude_messages(conv: dict) -> List[Message]:
    out: List[Message] = []
    for item in conv.get("chat_messages") or conv.get("messages") or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role") or item.get("sender", "")
        text = _block_text(item.get("content", "")) or str(item.get("text") or "").strip()
        if role in ("user", "human") and text:
            out.append(("user", text))
        elif role in ("assistant", "ai") and text:
            out.append(("assistant", text))
    return out


def chatgpt_messages(conv: dict) -> List[Message]:
    """Walk the branch the user last saw: current_node -> root, then reverse."""
    mapping = conv.get("mapping")
    if not isinstance(mapping, dict):
        return []
    chain: List[dict] = []
    node_id = conv.get("current_node")
    seen = set()
    if node_id not in mapping:
        # No current_node: follow first children from the root.
        node_id = next((k for k, v in mapping.items() if isinstance(v, dict) and v.get("parent") is None), None)
        while isinstance(node_id, str) and node_id not in seen and node_id in mapping:
            seen.add(node_id)
            chain.append(mapping[node_id])
            children = mapping[node_id].get("children") or []
            node_id = children[0] if children else None
    else:
        while isinstance(node_id, str) and node_id not in seen and node_id in mapping:
            seen.add(node_id)
            chain.append(mapping[node_id])
            node_id = mapping[node_id].get("parent")
        chain.reverse()
    out: List[Message] = []
    for node in chain:
        msg = node.get("message") if isinstance(node, dict) else None
        if not isinstance(msg, dict):
            continue
        role = (msg.get("author") or {}).get("role", "")
        content = msg.get("content") or {}
        parts = content.get("parts") if isinstance(content, dict) else None
        text = "\n".join(p for p in (parts or []) if isinstance(p, str) and p).strip()
        if role in ("user", "assistant") and text:
            out.append((role, text))
    return out


def transcript(messages: Iterable[Message]) -> str:
    lines: List[str] = []
    msgs = list(messages)
    i = 0
    while i < len(msgs):
        role, text = msgs[i]
        if role == "user":
            lines.append(f"> {text}")
            if i + 1 < len(msgs) and msgs[i + 1][0] == "assistant":
                lines.append(msgs[i + 1][1])
                i += 2
            else:
                i += 1
        else:
            lines.append(text)
            i += 1
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Conversation records
# --------------------------------------------------------------------------

@dataclass
class Conversation:
    provider: str
    id: str
    title: str
    created: str  # YYYY-MM-DD
    updated_at: str  # full timestamp as given by the export (state key)
    n_messages: int
    messages: List[Message]

    @property
    def updated(self) -> str:
        return self.updated_at[:10]

    def header(self) -> str:
        label = {"claude_ai": "claude.ai", "chatgpt": "chatgpt"}[self.provider]
        return (
            f"# {self.title}\n\n"
            f"Fonte: {label} | conversa {self.id} | criada {self.created} | "
            f"atualizada {self.updated} | {self.n_messages} mensagens\n\n"
        )

    def render(self) -> str:
        return self.header() + transcript(self.messages)


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s[:60] or "sem-titulo"


def _epoch_iso(value) -> str:
    if isinstance(value, (int, float)):
        return _dt.datetime.fromtimestamp(value, tz=_dt.timezone.utc).isoformat()
    return str(value or "")


def to_conversations(provider: str, raw: list) -> List[Conversation]:
    out = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        if provider == "claude_ai":
            cid = str(c.get("uuid") or "")
            created, updated = str(c.get("created_at") or ""), str(c.get("updated_at") or "")
            msgs = claude_messages(c)
            n = len(c.get("chat_messages") or c.get("messages") or [])
            title = c.get("name") or "(sem título)"
        else:
            cid = str(c.get("conversation_id") or c.get("id") or "")
            created, updated = _epoch_iso(c.get("create_time")), _epoch_iso(c.get("update_time"))
            msgs = chatgpt_messages(c)
            n = len(msgs)
            title = c.get("title") or "(sem título)"
        if not cid:
            continue
        out.append(Conversation(provider, cid, title, created[:10], updated or created, n, msgs))
    return out


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

@dataclass
class NormalizeResult:
    new: List[Conversation] = field(default_factory=list)
    updated: List[Conversation] = field(default_factory=list)
    adopted: int = 0
    unchanged: int = 0
    skipped_empty: int = 0
    files: Dict[str, str] = field(default_factory=dict)  # id -> file name

    @property
    def changed(self) -> List[Conversation]:
        return self.new + self.updated


def _existing_file(out_dir: str, conv: Conversation) -> Optional[str]:
    hits = sorted(glob.glob(os.path.join(glob.escape(out_dir), f"*_{glob.escape(conv.id[:8])}_*.md")))
    return os.path.basename(hits[0]) if hits else None


def _header_updated(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(2048)
    except OSError:
        return None
    m = _HEADER_UPDATED.search(head)
    return m.group(1) if m else None


def normalize_export(
    convs: List[Conversation],
    out_dir: str,
    state: Dict[str, dict],
    dry_run: bool = False,
) -> NormalizeResult:
    """Write new/updated conversations; `state` ({id: {updated_at, file}}) is updated in place.

    A conversation with no state entry whose file already exists (e.g. from an
    earlier manual run) is *adopted*: if the file's "atualizada" date matches
    the export, it is recorded as known and left untouched.
    """
    res = NormalizeResult()
    if not dry_run:
        os.makedirs(out_dir, exist_ok=True)
    for conv in convs:
        if len(conv.messages) < 2:
            res.skipped_empty += 1
            continue
        known = state.get(conv.id) or {}
        name = (
            known.get("file")
            or (_existing_file(out_dir, conv) if os.path.isdir(out_dir) else None)
            or f"{conv.created}_{conv.id[:8]}_{slug(conv.title)}.md"
        )
        path = os.path.join(out_dir, name)
        exists = os.path.isfile(path)
        res.files[conv.id] = name

        if known.get("updated_at") == conv.updated_at and exists:
            res.unchanged += 1
            continue
        if not known and exists and _header_updated(path) == conv.updated:
            res.adopted += 1
            state[conv.id] = {"updated_at": conv.updated_at, "file": name}
            continue

        text = conv.render()
        if exists:
            with open(path, encoding="utf-8") as f:
                if f.read() == text:
                    res.unchanged += 1
                    state[conv.id] = {"updated_at": conv.updated_at, "file": name}
                    continue
        (res.updated if exists or known else res.new).append(conv)
        if not dry_run:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            state[conv.id] = {"updated_at": conv.updated_at, "file": name}
    return res


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="mempalace_sync.py normalize", description=__doc__.split("\n")[0])
    ap.add_argument("export", help="export .zip, extracted folder or conversations.json")
    ap.add_argument("out_dir")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    with ExtractedExport(args.export) as root:
        provider, raw = load_conversations(root)
    if not provider:
        print("no claude.ai or ChatGPT conversations found")
        return 1
    res = normalize_export(to_conversations(provider, raw), args.out_dir, {}, args.dry_run)
    print(
        f"{provider}: new {len(res.new)}, updated {len(res.updated)}, adopted {res.adopted}, "
        f"unchanged {res.unchanged}, skipped (no text) {res.skipped_empty}"
    )
    return 0
