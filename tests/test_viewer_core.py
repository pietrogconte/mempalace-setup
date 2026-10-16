import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime

from tests import viewer_helpers as vh
from mpsync.config import ConfigError, parse_config
from mpview import filters, reports, settings, snapshot, store

VIEWER = os.path.join(os.path.dirname(vh.helpers.HERE), "viewer")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        vh.make_palace(self.tmp, [
            vh.drawer(1, "notes", "ideas", "C:\\data\\notes\\a.md", "2026-01-01T09:00:00"),
            vh.drawer(2, "notes", "ideas", "C:\\data\\notes\\a.md", "2026-01-03T09:00:00"),
            vh.drawer(3, "notes", "todo", "C:\\data\\notes\\b.md"),
            vh.drawer(4, "sessions", "technical", "/home/x/.claude/projects/p/s1.jsonl"),
        ], closets=[vh.drawer(9, "notes", "ideas", "C:\\data\\notes\\a.md")])
        self.db = os.path.join(self.tmp, "chroma.sqlite3")

    def test_iter_drawers_skips_closets(self):
        drawers = list(store.iter_drawers(self.db))
        self.assertEqual([d.drawer_id for d in drawers],
                         ["drawer_notes_1", "drawer_notes_2", "drawer_notes_3", "drawer_sessions_4"])
        self.assertEqual(drawers[0].text, "hello")
        self.assertEqual(drawers[0].source_name, "a.md")
        self.assertEqual(drawers[3].source_name, "s1.jsonl")

    def test_tree(self):
        tree = store.build_tree(store.iter_drawers(self.db))
        self.assertEqual(tree.wings(), ["notes", "sessions"])
        self.assertEqual(tree.rooms("notes"), ["ideas", "todo"])
        self.assertEqual(tree.wing_total("notes"), 3)
        self.assertEqual(tree.room_total("notes", "ideas"), 2)
        self.assertEqual(tree.files("notes", "ideas"), [("C:\\data\\notes\\a.md", 2)])
        self.assertEqual(tree.last_filed["C:\\data\\notes\\a.md"], "2026-01-03T09:00:00")
        self.assertEqual(tree.total, 4)

    def test_read_only_open(self):
        before = os.stat(self.db).st_mtime_ns
        list(store.iter_drawers(self.db))
        self.assertEqual(os.stat(self.db).st_mtime_ns, before)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["chroma.sqlite3", "seg-0001"])
        conn = store.connect(self.db)
        with self.assertRaises(Exception):
            conn.execute("DELETE FROM embeddings")
        conn.close()

    def test_unknown_collection(self):
        with self.assertRaises(LookupError):
            list(store.iter_drawers(self.db, "nope"))


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.palace = vh.make_palace(os.path.join(self.tmp, "palace"), [vh.drawer(1)])
        self.snaps = os.path.join(self.tmp, "snaps")
        self.lockf = os.path.join(self.tmp, "mine_palace_x.lock")
        self.clock = iter(datetime(2026, 1, 1, 12, 0, s) for s in range(60))

    def take(self, **kw):
        kw.setdefault("sleep", lambda s: None)
        kw.setdefault("now", lambda: next(self.clock))
        return snapshot.take(self.palace, self.snaps, self.lockf, **kw)

    def test_copy_and_metadata(self):
        snap = self.take(is_locked=lambda p: False)
        self.assertTrue(os.path.isfile(snap.db))
        self.assertEqual(snap.files, 2)
        self.assertEqual(snapshot.current(self.snaps).path, snap.path)
        self.assertEqual(list(store.iter_drawers(snap.db))[0].drawer_id, "drawer_notes_1")

    def test_new_snapshot_prunes_old(self):
        first = self.take(is_locked=lambda p: False)
        second = self.take(is_locked=lambda p: False)
        self.assertNotEqual(first.path, second.path)
        self.assertFalse(os.path.exists(first.path))
        self.assertEqual(snapshot.current(self.snaps).path, second.path)

    def test_locked_palace_is_never_copied(self):
        copies = []
        with self.assertRaises(snapshot.PalaceBusy):
            self.take(is_locked=lambda p: True, copy=lambda s, d: copies.append(d))
        self.assertEqual(copies, [])
        self.assertIsNone(snapshot.current(self.snaps))

    def test_lock_taken_during_copy_discards(self):
        states = iter([False, True, False, False])
        snap = self.take(is_locked=lambda p: next(states))
        self.assertEqual(len([n for n in os.listdir(self.snaps) if n.startswith("snap-")]), 1)
        self.assertTrue(os.path.isfile(snap.db))

    def test_palace_changing_during_copy_discards(self):
        calls = []

        def copy_then_write(src, dst):
            shutil.copytree(src, dst)
            if not calls:
                with open(os.path.join(src, "seg-0001", "data_level0.bin"), "ab") as f:
                    f.write(b"more")
            calls.append(dst)

        snap = self.take(is_locked=lambda p: False, copy=copy_then_write)
        self.assertEqual(len(calls), 2)
        self.assertFalse(os.path.exists(calls[0]))
        self.assertEqual(snap.path, calls[1])

    def test_live_palace_untouched(self):
        before = snapshot.fingerprint(self.palace)
        self.take(is_locked=lambda p: False)
        self.assertEqual(snapshot.fingerprint(self.palace), before)

    def test_not_a_chroma_palace(self):
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.take(os.path.join(self.tmp, "nothing"), self.snaps, self.lockf)


class FiltersTest(unittest.TestCase):
    def test_build_and_dates(self):
        req = filters.build("  lock  ", "notes", "", date(2026, 1, 1), date(2026, 1, 31), 5)
        self.assertEqual(req.query, "lock")
        self.assertEqual(req.since(), "2026-01-01")
        self.assertEqual(req.before(), "2026-02-01")  # end day included
        self.assertIsNone(filters.build("x").since())
        self.assertIsNone(filters.build("x").before())

    def test_errors(self):
        for kw in ({"query": " "}, {"query": "x", "start": date(2026, 2, 1), "end": date(2026, 1, 1)},
                   {"query": "x", "limit": 0}, {"query": "x", "limit": 500}):
            with self.assertRaises(filters.FilterError, msg=kw):
                filters.build(**kw)

    def test_rooms_for(self):
        tree_rooms = {"a": ["r1", "r2"], "b": ["r2", "r3"]}
        self.assertEqual(filters.rooms_for("a", tree_rooms), ["r1", "r2"])
        self.assertEqual(filters.rooms_for("", tree_rooms), ["r1", "r2", "r3"])
        self.assertEqual(filters.rooms_for("zz", tree_rooms), [])

    def test_bridge_argv(self):
        req = filters.build("q", "w", "r", date(2026, 3, 1), None, 7)
        argv = filters.bridge_argv("py", "b.py", "/snap", "/live", req)
        self.assertEqual(argv[:3], ["py", "-I", "b.py"])
        joined = " ".join(argv)
        for part in ("--palace /snap", "--live-palace /live", "--n 7", "--query q", "--wing w",
                     "--room r", "--since 2026-03-01"):
            self.assertIn(part, joined)
        self.assertNotIn("--before", argv)
        self.assertNotIn("--wing", filters.bridge_argv("py", "b", "/s", "/l", filters.build("q")))


class BridgeTest(unittest.TestCase):
    def test_refuses_live_palace(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run(
                [sys.executable, os.path.join(VIEWER, "mpbridge.py"), "--palace", tmp,
                 "--live-palace", tmp + os.sep, "--query", "x"],
                capture_output=True, text=True,
            )
        self.assertEqual(out.returncode, 2)
        self.assertIn("live palace", json.loads(out.stdout)["error"])


SYNC_PT = """# Relatório mempalace-sync — {day}

## Status do palace

| Wing | Antes | Depois | Δ |
|---|---:|---:|---:|
| `notes` | {a} | {b} | +1 |
| `sessions` | 5 | 7 | +2 |
| **total** | 0 | 0 | 0 |

## Fontes

| `not` | 1 | 2 | 3 |
"""

SYNC_EN = """# mempalace-sync report

## Palace status

| Wing | Before | After | Δ |
|---|---:|---:|---:|
| `notes` | 1 | 2 | +1 |
| **total** | 1 | 2 | +1 |
"""


class ReportsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, name, body, mtime=None):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        if mtime:
            os.utime(path, (mtime, mtime))
        return path

    def test_classify(self):
        self.assertEqual(reports.classify("2026-01-02.md"), ("sync", "2026-01-02"))
        self.assertEqual(reports.classify("2026-01-02-3.md"), ("sync", "2026-01-02"))
        self.assertEqual(reports.classify("2026-01-02-dry-run.md"), ("dry-run", "2026-01-02"))
        self.assertEqual(reports.classify("curadoria-2026-01-02.md"), ("curation", "2026-01-02"))
        self.assertEqual(reports.classify("curation-2026-01-02.diff"), ("curation", "2026-01-02"))
        self.assertEqual(reports.classify("status-antes-2026-01-02.txt"), ("other", "2026-01-02"))
        self.assertEqual(reports.classify("notes.md"), ("other", ""))

    def test_parse_status_pt_en(self):
        self.assertEqual(reports.parse_status(SYNC_PT.format(day="d", a=3, b=4)),
                         {"notes": (3, 4), "sessions": (5, 7)})
        self.assertEqual(reports.parse_status(SYNC_EN), {"notes": (1, 2)})
        self.assertIsNone(reports.parse_status("# nothing here\n"))

    def test_growth(self):
        self.write("2026-01-01.md", SYNC_PT.format(day=1, a=1, b=2), 1000)
        self.write("2026-01-01-2.md", SYNC_PT.format(day=1, a=2, b=3), 900)   # later run, older mtime
        self.write("2026-01-02-dry-run.md", SYNC_PT.format(day=2, a=9, b=99))
        self.write("2026-01-03.md", SYNC_EN)
        self.write("2026-01-04.md", "# run without status\n", 5000)
        self.write("curadoria-2026-01-03.md", "# Curadoria\n")
        files = reports.list_reports(self.tmp)
        self.assertEqual(files[0].name, "2026-01-04.md")
        self.assertEqual(reports.growth(files), [
            ("2026-01-01", {"notes": 3, "sessions": 7}),
            ("2026-01-03", {"notes": 2}),
        ])

    def test_missing_folder(self):
        self.assertEqual(reports.list_reports(os.path.join(self.tmp, "nope")), [])
        self.assertEqual(reports.list_reports(""), [])


class SettingsTest(unittest.TestCase):
    def cfg(self, **viewer):
        data = {"mempalace": {"command": ["C:/venv/python.exe", "-m", "mempalace"], "palace": "/data/palace"},
                "viewer": viewer}
        return parse_config(data)

    def test_defaults(self):
        s = settings.parse_viewer(self.cfg())
        self.assertEqual(s.port, 8501)
        self.assertEqual(s.mempalace_python, "C:/venv/python.exe")
        self.assertTrue(s.snapshot_dir.endswith(os.path.join("mempalace-viewer", "snapshot")))
        self.assertEqual(s.language, "en")

    def test_overrides(self):
        s = settings.parse_viewer(self.cfg(snapshot_dir="/cache/snap", port=9000, language="pt",
                                           audit_extra_patterns=[{"name": "cpf", "regex": r"\d{11}"}]))
        self.assertEqual((s.port, s.language), (9000, "pt"))
        self.assertEqual(s.snapshot_dir, os.path.abspath("/cache/snap"))
        self.assertEqual(s.extra_patterns[0].name, "cpf")

    def test_errors(self):
        for viewer in ({"snapshot_dir": "/data/palace/snap"}, {"snapshot_dir": "/data"}, {"port": 80},
                       {"audit_extra_patterns": [{"name": "x"}]}):
            with self.assertRaises(ConfigError, msg=viewer):
                settings.parse_viewer(self.cfg(**viewer))
        with self.assertRaises(ConfigError):
            settings.bridge_python(["mempalace"])
        self.assertEqual(settings.bridge_python(["mempalace"], "/py"), os.path.abspath("/py"))

    def test_loopback(self):
        for ok in ("127.0.0.1", "localhost", "::1", "127.0.0.2"):
            self.assertTrue(settings.is_loopback(ok), ok)
        for bad in ("0.0.0.0", "", "192.168.0.10", "::", "example.com"):
            self.assertFalse(settings.is_loopback(bad), bad)

    def test_versioned_streamlit_config_is_local_only(self):
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        with open(os.path.join(VIEWER, ".streamlit", "config.toml"), "rb") as f:
            conf = tomllib.load(f)
        self.assertEqual(conf["server"]["address"], "127.0.0.1")
        self.assertIs(conf["browser"]["gatherUsageStats"], False)

    def test_launcher_argv(self):
        sys.path.insert(0, VIEWER)
        import run_viewer

        argv = run_viewer.streamlit_argv(8600, "cfg.toml")
        self.assertEqual(argv[1:4], ["-m", "streamlit", "run"])
        pairs = dict(zip(argv, argv[1:]))
        self.assertEqual(pairs["--server.address"], "127.0.0.1")
        self.assertEqual(pairs["--browser.gatherUsageStats"], "false")
        self.assertEqual(pairs["--server.port"], "8600")
        self.assertEqual(argv[-2:], ["--config", "cfg.toml"])

    def test_example_config_viewer_section(self):
        from mpsync.config import load_config

        root = os.path.dirname(vh.helpers.HERE)
        s = settings.parse_viewer(load_config(os.path.join(root, "config.example.toml")))
        self.assertEqual(s.port, 8501)


if __name__ == "__main__":
    unittest.main()
