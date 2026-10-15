import os
import tempfile
import unittest

from tests import helpers  # noqa: F401  (sys.path)
from mpsync import staging
from mpsync.config import Source


def write(root, rel, data):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


class StagingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src_dir = os.path.join(self.tmp.name, "course")
        self.out = os.path.join(self.tmp.name, "staging", "course")
        files = {
            "notes.md": "# notes",
            "lesson/aula-01.html": "<html><body><h1>Aula</h1><script>x()</script></body></html>",
            "lesson/nb.ipynb": '{"cells": [{"cell_type": "code", "source": "print(2)"}]}',
            "lesson/query.sql": "select 1;",
            "lesson/copy.sql": "select 1;",
            "data/titanic.csv": "a,b\n1,2",
            "data/pacientes.json": "[]",
            "manuals/EB70-MC-10.223.md": "manual",
            "MC 3-1 Campanha.md": "manual",
            ".env": "API_KEY=x",
            "aws_credentials.txt": "key",
            "photo.png": b"\x89PNG\x00\x00",
            "weird.md": b"bin\x00ary",
            ".git/config": "[core]",
            "node_modules/pkg/index.md": "dep",
            "empty.md": "   ",
        }
        for rel, data in files.items():
            write(self.src_dir, rel, data)
        self.src = Source(
            name="course", path=self.src_dir, wing="course",
            include=["*.md", "*.py", "*.sql", "*.html", "*.ipynb"],
            exclude=["EB20-*", "EB70-*", "MC *", "MD33-*", "*.csv", "*.json"],
            convert=["html", "ipynb"],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_filters_and_converts(self):
        res = staging.build(self.src, self.out)
        outs = sorted(f.rel_out for f in res.files)
        self.assertEqual(outs, ["lesson/aula-01.html.md", "lesson/copy.sql", "lesson/nb.ipynb.md",
                                "lesson/query.sql", "notes.md"])
        self.assertEqual(res.skipped["sensitive"], 2)
        self.assertEqual(res.skipped["excluded"], 4)
        self.assertEqual(res.skipped["binary"], 1)  # weird.md (NUL byte); photo.png is not included
        self.assertEqual(res.skipped["empty"], 1)
        with open(os.path.join(self.out, "lesson", "aula-01.html.md"), encoding="utf-8") as f:
            html_md = f.read()
        self.assertEqual(html_md, "# Aula\n")
        dups = res.duplicates()
        self.assertEqual([sorted(f.rel_src for f in g) for g in dups], [["lesson/copy.sql", "lesson/query.sql"]])
        self.assertEqual(res.largest(1)[0].rel_out, "lesson/nb.ipynb.md")

    def test_rerun_keeps_mtime_and_removes_stale(self):
        staging.build(self.src, self.out)
        notes = os.path.join(self.out, "notes.md")
        os.utime(notes, (1000, 1000))
        os.remove(os.path.join(self.src_dir, "lesson", "copy.sql"))
        res = staging.build(self.src, self.out)
        self.assertEqual(os.path.getmtime(notes), 1000)
        self.assertEqual(res.removed, ["lesson/copy.sql"])
        self.assertFalse(any(f.changed for f in res.files))

    def test_preview_writes_nothing(self):
        res = staging.build(self.src, self.out, write=False)
        self.assertEqual(len(res.files), 5)
        self.assertFalse(os.path.exists(self.out))

    def test_refuses_foreign_non_empty_folder(self):
        write(self.out, "mine.txt", "user data")
        with self.assertRaises(RuntimeError):
            staging.build(self.src, self.out)

    def test_utf16_files_are_decoded_not_skipped(self):
        write(self.src_dir, "bom.md", "﻿# Título".encode("utf-16-le"))
        write(self.src_dir, "mixed.md", "# Curso\n".encode("utf-8") + "# Básico\r\nfim".encode("utf-16-le"))
        res = staging.build(self.src, self.out)
        with open(os.path.join(self.out, "bom.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "# Título")
        with open(os.path.join(self.out, "mixed.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "# Curso\n# Básico\nfim")
        self.assertEqual(res.skipped["binary"], 1)  # weird.md is still binary

    def test_find_sensitive(self):
        self.assertEqual(sorted(staging.find_sensitive(self.src_dir)), [".env", "aws_credentials.txt"])


if __name__ == "__main__":
    unittest.main()
