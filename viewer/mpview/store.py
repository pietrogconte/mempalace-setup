"""Read drawers straight from a snapshot's chroma.sqlite3 (stdlib sqlite3, read-only).

Only the four Chroma tables the metadata lives in are touched: ``collections``,
``segments``, ``embeddings`` and ``embedding_metadata``. The file is opened
with ``mode=ro&immutable=1``: no locks, no journal, no writes — it is a
snapshot, nobody else changes it.
"""

from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Dict, Iterator, List

KEYS = ("wing", "room", "source_file", "filed_at", "chroma:document")


def source_name(path: str) -> str:
    # MemPalace may store Windows paths; PureWindowsPath splits on both separators.
    return PureWindowsPath(path).name if path else "?"


@dataclass
class Drawer:
    drawer_id: str
    wing: str
    room: str
    source_file: str  # full path as stored by MemPalace
    filed_at: str
    text: str

    @property
    def source_name(self) -> str:
        return source_name(self.source_file)


def connect(db_path: str) -> sqlite3.Connection:
    if not os.path.isfile(db_path):
        raise FileNotFoundError(db_path)
    uri = Path(db_path).resolve().as_uri() + "?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def _collection_id(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise LookupError(f"collection {name!r} not found in snapshot")
    return row[0]


def iter_drawers(db_path: str, collection: str = "mempalace_drawers") -> Iterator[Drawer]:
    conn = connect(db_path)
    try:
        cid = _collection_id(conn, collection)
        rows = conn.execute(
            f"""
            SELECT e.id, e.embedding_id, m.key, m.string_value
            FROM embeddings e
            JOIN segments s ON s.id = e.segment_id
            JOIN embedding_metadata m ON m.id = e.id
            WHERE s.collection = ? AND m.key IN ({",".join("?" * len(KEYS))})
            ORDER BY e.id
            """,
            (cid, *KEYS),
        )
        cur_id = None
        cur: Dict[str, str] = {}
        for rid, emb_id, key, value in rows:
            if rid != cur_id:
                if cur_id is not None:
                    yield _drawer(cur)
                cur_id, cur = rid, {"_id": emb_id}
            cur[key] = value or ""
        if cur_id is not None:
            yield _drawer(cur)
    finally:
        conn.close()


def _drawer(d: Dict[str, str]) -> Drawer:
    return Drawer(
        drawer_id=d["_id"],
        wing=d.get("wing", "") or "?",
        room=d.get("room", "") or "?",
        source_file=d.get("source_file", ""),
        filed_at=d.get("filed_at", ""),
        text=d.get("chroma:document", ""),
    )


@dataclass
class Tree:
    """wing -> room -> source file -> drawer count, plus filed_at range per source."""

    counts: Dict[str, Dict[str, Dict[str, int]]]
    last_filed: Dict[str, str]

    def wings(self) -> List[str]:
        return sorted(self.counts)

    def rooms(self, wing: str) -> List[str]:
        return sorted(self.counts.get(wing, {}))

    def wing_total(self, wing: str) -> int:
        return sum(sum(files.values()) for files in self.counts.get(wing, {}).values())

    def room_total(self, wing: str, room: str) -> int:
        return sum(self.counts.get(wing, {}).get(room, {}).values())

    def files(self, wing: str, room: str) -> List[tuple]:
        files = self.counts.get(wing, {}).get(room, {})
        return sorted(files.items(), key=lambda kv: (-kv[1], kv[0]))

    @property
    def total(self) -> int:
        return sum(self.wing_total(w) for w in self.counts)


def build_tree(drawers) -> Tree:
    counts: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    last: Dict[str, str] = {}
    for d in drawers:
        src = d.source_file or "?"
        counts[d.wing][d.room][src] += 1
        if d.filed_at > last.get(src, ""):
            last[src] = d.filed_at
    plain = {w: {r: dict(f) for r, f in rooms.items()} for w, rooms in counts.items()}
    return Tree(plain, last)

