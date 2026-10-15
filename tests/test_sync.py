import json
import os
import tempfile
import unittest
from unittest import mock

from tests.helpers import claude_conv, fake_cmd, write_zip
from mpsync import lock, sync, task
from mpsync.config import parse_config
from mpsync.runner import Runner


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.p = lambda *a: os.path.join(t, *a)
        self.mp_log = self.p("mp-calls.jsonl")
        os.makedirs(self.p("agent"))
        with open(self.p("agent", "s1.jsonl"), "w") as f:
            f.write("{}")
        os.makedirs(self.p("course"))
        with open(self.p("course", "aula.html"), "w") as f:
            f.write("<h1>Aula</h1>")
        with open(self.p("course", "data.csv"), "w") as f:
            f.write("a,b")
        os.makedirs(self.p("wiki"))
        with open(self.p("wiki", "2026-01-10 Starter.md"), "w", encoding="utf-8") as f:
            f.write("Fonte: claude.ai | conversa `aaaaaaaa` | ...")
        os.makedirs(self.p("inbox"))
        write_zip(self.p("inbox", "export.zip"), [
            claude_conv("aaaaaaaa-1111", "Starter", "2026-01-10T10:00:00Z"),
            claude_conv("bbbbbbbb-2222", "Brand new", "2026-01-11T10:00:00Z"),
        ])
        self.cfg = parse_config({
            "mempalace": {"command": fake_cmd(), "palace": self.p("palace"), "lock_policy": "skip"},
            "paths": {
                "inbox": self.p("inbox"), "processed": self.p("inbox", "done"), "reports": self.p("reports"),
                "staging": self.p("staging"), "state_dir": self.p("state"), "wiki_sources": self.p("wiki"),
            },
            "exports": {"claude_ai": {"wing": "claude_ai", "normalized_dir": self.p("norm")}},
            "source": [
                {"name": "agent", "path": self.p("agent"), "mode": "convos", "wing": "sessions"},
                {"name": "absent", "path": self.p("nope"), "mode": "convos", "wing": "x"},
                {"name": "course", "path": self.p("course"), "wing": "course",
                 "exclude": ["*.csv"], "convert": ["html"]},
            ],
        })
        self.env = mock.patch.dict(os.environ, {"FAKE_MP_LOG": self.mp_log, "HOME": t, "USERPROFILE": t})
        self.env.start()
        self.runner = Runner(self.cfg.mempalace_cmd, self.cfg.palace, "mempalace-sync", 60)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def calls(self):
        with open(self.mp_log, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def report(self, name):
        with open(self.p("reports", name), encoding="utf-8") as f:
            return f.read()

    def test_dry_run_writes_nothing_to_palace_or_inbox(self):
        rc = sync.run(self.cfg, self.runner, dry_run=True, today="2026-01-12")
        self.assertEqual(rc, 0)
        mines = [c for c in self.calls() if c[0] == "mine"]
        self.assertTrue(mines and all("--dry-run" in c for c in mines))
        self.assertTrue(os.path.exists(self.p("inbox", "export.zip")))
        self.assertFalse(os.path.exists(self.p("norm")))
        self.assertFalse(os.path.exists(self.p("staging")))
        self.assertFalse(os.path.exists(self.cfg.state_file))
        rep = self.report("2026-01-12-dry-run.md")
        self.assertIn("aula.html.md", rep)  # largest-files listing of the staged preview
        self.assertIn("`aaaaaaaa` Starter", rep)

    def test_real_run_then_idempotent_rerun(self):
        rc = sync.run(self.cfg, self.runner, today="2026-01-12")
        self.assertEqual(rc, 0)
        mines = [c for c in self.calls() if c[0] == "mine"]
        self.assertEqual(sorted((c[1], c[c.index("--wing") + 1]) for c in mines), sorted([
            (self.p("agent"), "sessions"),
            (os.path.join(self.p("staging"), "course"), "course"),
            (self.p("norm"), "claude_ai"),
        ]))
        self.assertTrue(all("--dry-run" not in c and "--agent" in c for c in mines))
        self.assertTrue(os.path.exists(self.p("inbox", "done", "export.zip")))
        self.assertEqual(len(os.listdir(self.p("norm"))), 2)
        self.assertEqual(os.listdir(os.path.join(self.p("staging"), "course")), [".mpsync-staging", "aula.html.md"])
        rep = self.report("2026-01-12.md")
        self.assertIn("2026-01-10 Starter.md", rep)  # existing wiki page flagged for curation
        self.assertIn("`bbbbbbbb` Brand new", rep)  # no page yet
        self.assertIn("pasta não existe", rep)  # absent source
        with open(self.cfg.state_file, encoding="utf-8") as f:
            state = json.load(f)
        self.assertEqual(set(state["exports"]["claude_ai"]), {"aaaaaaaa-1111", "bbbbbbbb-2222"})

        # Same export again: nothing new is written.
        write_zip(self.p("inbox", "export.zip"), [claude_conv("aaaaaaaa-1111", "Starter", "2026-01-10T10:00:00Z")])
        sync.run(self.cfg, self.runner, today="2026-01-12")
        rep = self.report("2026-01-12-2.md")  # same day: earlier report kept
        self.assertIn("0 novas, 0 atualizadas, 1 inalteradas", rep)
        self.assertIn("`bbbbbbbb` Brand new", self.report("2026-01-12.md"))
        self.assertTrue(os.path.exists(self.p("inbox", "done", "export-1.zip")))

    def test_lock_held_skips_and_keeps_zip(self):
        with mock.patch.object(lock, "is_locked", return_value=True):
            rc = sync.run(self.cfg, self.runner, today="2026-01-12")
        self.assertEqual(rc, 0)
        self.assertFalse([c for c in self.calls() if c[0] == "mine"])
        self.assertTrue(os.path.exists(self.p("inbox", "export.zip")))
        self.assertIn("PULADA", self.report("2026-01-12.md"))

    def test_lock_taken_during_mine_is_a_skip(self):
        with mock.patch.dict(os.environ, {"FAKE_MP_LOCKED": "1"}):
            sync.run(self.cfg, self.runner, only=["agent"], today="2026-01-12")
        self.assertIn("lock taken by another writer", self.report("2026-01-12.md"))

    def test_sensitive_file_blocks_in_place_projects_mining(self):
        os.makedirs(self.p("notes"))
        with open(self.p("notes", ".env"), "w") as f:
            f.write("TOKEN=x")
        self.cfg.sources.append(parse_config({
            "mempalace": {"command": ["x"]},
            "source": [{"name": "notes", "path": self.p("notes"), "wing": "notes"}],
        }).sources[0])
        rc = sync.run(self.cfg, self.runner, only=["notes"], today="2026-01-12")
        self.assertEqual(rc, 1)
        self.assertFalse([c for c in self.calls() if c[0] == "mine"])


class TaskXmlTest(unittest.TestCase):
    def test_xml_settings(self):
        xml = task.build_xml("C:/venv/Scripts/pythonw.exe", "C:/repo/scripts/mempalace_sync.py",
                             ["--config", "C:/cfg.toml"], "21:00", "PC\\me", "C:/Users/me")
        for needle in (
            "<StartWhenAvailable>true</StartWhenAvailable>",
            "<LogonType>InteractiveToken</LogonType>",
            "<DaysInterval>1</DaysInterval>",
            "T21:00:00</StartBoundary>",
            "<Command>C:/venv/Scripts/pythonw.exe</Command>",
            "<Arguments>\"C:/repo/scripts/mempalace_sync.py\" \"--config\" \"C:/cfg.toml\"</Arguments>",
            "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>",
        ):
            self.assertIn(needle, xml)


if __name__ == "__main__":
    unittest.main()
