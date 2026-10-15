"""Stand-in for `python -m mempalace` used by the tests.

Records every call in $FAKE_MP_LOG (JSON lines). `mine` reports each file of
the directory as filed with one drawer, except paths listed in
$FAKE_MP_ALREADY (os.pathsep-separated); $FAKE_MP_LOCKED makes `mine` fail the
way MemPalace does when another writer holds the palace lock.
"""

import json
import os
import sys

args = sys.argv[1:]
if args[:1] == ["--palace"]:
    args = args[2:]
with open(os.environ["FAKE_MP_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")

if args[0] == "status":
    print("=" * 20)
    print("  MemPalace Status -- 7 drawers")
    print("  WING: sessions")
    print("    ROOM: technical               5 drawers")
    print("  WING: claude_ai")
    print("    ROOM: planning                2 drawers")
    sys.exit(0)

if args[0] == "mine":
    if os.environ.get("FAKE_MP_LOCKED"):
        print("mempalace: palace /x is held by pid 1; wait for it to finish", file=sys.stderr)
        sys.exit(1)
    root = args[1]
    dry = "--dry-run" in args
    files = []
    for dp, _, fns in os.walk(root):
        files += [os.path.join(dp, fn) for fn in sorted(fns) if not fn.startswith(".")]
    done = set(filter(None, os.environ.get("FAKE_MP_ALREADY", "").split(os.pathsep)))
    new = [p for p in files if p not in done]
    for i, p in enumerate(new, 1):
        name = os.path.basename(p)
        if dry:
            print(f"    [DRY RUN] {name} -> room:general (1 drawers)")
        else:
            print(f"  + [{i:4}/{len(new)}] {name[:50]:50} +1")
    print(f"  Files processed: {len(new)}")
    print(f"  Files skipped (already filed): {len(files) - len(new)}")
    print(f"  Drawers filed: {len(new)}")
    sys.exit(0)
sys.exit(2)
