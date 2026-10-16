"""Semantic search over a palace SNAPSHOT, printed as JSON.

Runs inside MemPalace's own venv (it needs MemPalace's embedder), called by the
viewer as ``<mempalace python> -I mpbridge.py --palace <snapshot> ...``. It
refuses to run against the live palace: with the Chroma backend, even a search
writes to the palace.
"""

import argparse
import json
import os
import sys

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")  # chromadb telemetry off

FIELDS = ("drawer_id", "text", "wing", "room", "source_file", "source_path",
          "filed_at", "authored_at", "similarity")


def same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--palace", required=True, help="snapshot folder")
    p.add_argument("--live-palace", required=True, help="the live palace, which must not be searched")
    p.add_argument("--query", required=True)
    p.add_argument("--wing")
    p.add_argument("--room")
    p.add_argument("--since")
    p.add_argument("--before")
    p.add_argument("--n", type=int, default=10)
    args = p.parse_args(argv)

    if same_path(args.palace, args.live_palace):
        print(json.dumps({"error": "refusing to search the live palace; pass a snapshot"}))
        return 2

    from mempalace.searcher import search_memories

    res = search_memories(
        args.query, args.palace, wing=args.wing, room=args.room,
        since=args.since, before=args.before, n_results=args.n,
    )
    if "error" in res:
        print(json.dumps({"error": str(res["error"])}))
        return 1
    hits = [{k: h.get(k) for k in FIELDS} for h in res.get("results", [])]
    print(json.dumps({"results": hits}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
