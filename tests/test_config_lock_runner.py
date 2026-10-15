import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

from tests import helpers  # noqa: F401  (sys.path)
from mpsync import lock
from mpsync.config import ConfigError, load_config, parse_config
from mpsync.runner import parse_mine, parse_status


class ConfigTest(unittest.TestCase):
    def test_example_config_parses(self):
        root = os.path.dirname(helpers.HERE)
        cfg = load_config(os.path.join(root, "config.example.toml"))
        self.assertEqual([s.name for s in cfg.sources], ["claude-code", "codex", "pi", "gemini-cli"])
        self.assertEqual(cfg.sources[0].wing, "sessions")
        self.assertEqual(set(cfg.exports), {"claude_ai", "chatgpt"})
        self.assertTrue(cfg.inbox.endswith(os.path.join("exports", "inbox")))

    def base(self, **source):
        src = {"name": "x", "path": "/data/x", "wing": "x"}
        src.update(source)
        return {"mempalace": {"command": ["mp"]}, "paths": {"staging": "/staging"}, "source": [src]}

    def test_staged_flag(self):
        cfg = parse_config(self.base(include=["*.md"]))
        self.assertTrue(cfg.sources[0].staged)
        self.assertFalse(parse_config(self.base()).sources[0].staged)

    def test_errors(self):
        bad = [
            {"mempalace": {}},
            self.base(mode="weird"),
            self.base(convert=["pdf"]),
            self.base(mode="convos", include=["*.md"]),
            dict(self.base(include=["*.md"]), paths={"staging": "/data/x/staging"}),
            {"mempalace": {"command": ["mp"], "lock_policy": "maybe"}},
        ]
        for data in bad:
            with self.assertRaises(ConfigError, msg=str(data)):
                parse_config(data)


class LockTest(unittest.TestCase):
    def test_lock_path_is_mempalace_compatible(self):
        p = lock.lock_path("/some/palace", home="/home/u")
        self.assertRegex(os.path.basename(p), r"^mine_palace_[0-9a-f]{16}\.lock$")
        self.assertEqual(p, lock.lock_path("/some/palace/", home="/home/u"))

    def test_free_and_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mine_palace_x.lock")
            self.assertFalse(lock.is_locked(path))  # missing file
            open(path, "w").close()
            self.assertFalse(lock.is_locked(path))
            holder = textwrap.dedent(f"""
                import os, sys, time
                f = open({path!r}, "r+b"); f.seek(0)
                if os.name == "nt":
                    import msvcrt; msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl; fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                print("held", flush=True); sys.stdin.readline()
            """)
            proc = subprocess.Popen([sys.executable, "-c", holder], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(proc.stdout.readline().strip(), "held")
                self.assertTrue(lock.is_locked(path))
                self.assertFalse(lock.wait_until_free(path, "skip", 60, 1))
                clock = iter(range(0, 1000, 10))
                self.assertFalse(lock.wait_until_free(path, "wait", 30, 10, sleep=lambda s: None,
                                                      clock=lambda: next(clock)))
            finally:
                proc.communicate("\n")
            self.assertTrue(lock.wait_until_free(path, "wait", 30, 10))


class ParseTest(unittest.TestCase):
    def test_status(self):
        text = (
            "  MemPalace Status -- 14 drawers\n"
            "  WING: claude_ai\n    ROOM: technical             3 drawers\n    ROOM: planning 4 drawers\n"
            "  WING: sessions\n    ROOM: architecture        7 drawers\n"
        )
        self.assertEqual(parse_status(text), {"claude_ai": 7, "sessions": 7, "_total": 14})

    def test_mine_real_and_dry(self):
        real = parse_mine(
            "  + [   1/2] a562cddf.jsonl                                   +81\n"
            "  + [   2/2] notes with spaces.md                             +0\n"
            "  Files processed: 2\n  Files skipped (already filed): 26\n  Drawers filed: 81\n"
        )
        self.assertEqual((real.processed, real.skipped, real.drawers), (2, 26, 81))
        self.assertEqual(real.files, [("a562cddf.jsonl", 81), ("notes with spaces.md", 0)])
        dry = parse_mine("    [DRY RUN] MEMORY.md -> room:technical (1 drawers)\n  Drawers filed: 1\n")
        self.assertEqual(dry.files, [("MEMORY.md", 1)])


if __name__ == "__main__":
    unittest.main()
