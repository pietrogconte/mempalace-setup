"""Fictitious palaces for the viewer tests: a chroma.sqlite3 with just the tables mpview reads."""

import os
import sqlite3
import sys

from tests import helpers

sys.path.insert(0, os.path.join(os.path.dirname(helpers.HERE), "viewer"))

SCHEMA = """
CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE segments (id TEXT PRIMARY KEY, type TEXT, scope TEXT, collection TEXT NOT NULL);
CREATE TABLE embeddings (id INTEGER PRIMARY KEY, segment_id TEXT NOT NULL, embedding_id TEXT NOT NULL);
CREATE TABLE embedding_metadata (id INTEGER, key TEXT NOT NULL, string_value TEXT,
    int_value INTEGER, float_value REAL, bool_value INTEGER, PRIMARY KEY (id, key));
"""


def make_palace(folder, drawers, closets=()):
    """drawers: dicts with drawer_id, wing, room, source_file, filed_at, text."""
    os.makedirs(folder, exist_ok=True)
    os.makedirs(os.path.join(folder, "seg-0001"), exist_ok=True)
    with open(os.path.join(folder, "seg-0001", "data_level0.bin"), "wb") as f:
        f.write(b"\0" * 64)
    conn = sqlite3.connect(os.path.join(folder, "chroma.sqlite3"))
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO collections VALUES ('c-d', 'mempalace_drawers'), ('c-c', 'mempalace_closets')")
    conn.execute("INSERT INTO segments VALUES ('s-d', 'sqlite', 'METADATA', 'c-d'), ('s-c', 'sqlite', 'METADATA', 'c-c')")
    rid = 0
    for seg, items in (("s-d", drawers), ("s-c", closets)):
        for d in items:
            rid += 1
            conn.execute("INSERT INTO embeddings VALUES (?, ?, ?)", (rid, seg, d["drawer_id"]))
            for key, value in (("wing", d.get("wing")), ("room", d.get("room")),
                               ("source_file", d.get("source_file")), ("filed_at", d.get("filed_at")),
                               ("chroma:document", d.get("text")), ("chunk_index", None)):
                if key == "chunk_index":
                    conn.execute("INSERT INTO embedding_metadata (id, key, int_value) VALUES (?, ?, 0)", (rid, key))
                elif value is not None:
                    conn.execute("INSERT INTO embedding_metadata (id, key, string_value) VALUES (?, ?, ?)",
                                 (rid, key, value))
    conn.commit()
    conn.close()
    return folder


def drawer(i, wing="notes", room="general", source="C:\\data\\notes\\a.md", filed="2026-01-02T10:00:00", text="hello"):
    return {"drawer_id": f"drawer_{wing}_{i}", "wing": wing, "room": room, "source_file": source,
            "filed_at": filed, "text": text}
