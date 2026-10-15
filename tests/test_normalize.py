import json
import os
import tempfile
import unittest
import zipfile

from tests.helpers import chatgpt_conv, claude_conv, write_zip
from mpsync import normalize as nz


class ClaudeNormalizeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def convs(self, *raw):
        return nz.to_conversations("claude_ai", list(raw))

    def test_new_then_unchanged_then_updated(self):
        state = {}
        c1 = claude_conv("aaaaaaaa-1111", "Sourdough starter", "2026-01-10T10:00:00Z")
        res = nz.normalize_export(self.convs(c1), self.out, state)
        self.assertEqual([c.id for c in res.new], ["aaaaaaaa-1111"])
        files = os.listdir(self.out)
        self.assertEqual(files, ["2026-01-10_aaaaaaaa_sourdough-starter.md"])
        with open(os.path.join(self.out, files[0]), encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(text.startswith(
            "# Sourdough starter\n\nFonte: claude.ai | conversa aaaaaaaa-1111 | "
            "criada 2026-01-10 | atualizada 2026-01-10 | 2 mensagens"
        ))
        self.assertIn("> question 0 about Sourdough starter\nanswer 0\n", text)

        res = nz.normalize_export(self.convs(c1), self.out, state)
        self.assertEqual((len(res.new), len(res.updated), res.unchanged), (0, 0, 1))

        # Renamed and continued: same file name, rewritten.
        c1b = claude_conv("aaaaaaaa-1111", "Renamed title", "2026-01-12T08:00:00Z", n_pairs=2)
        res = nz.normalize_export(self.convs(c1b), self.out, state)
        self.assertEqual([c.title for c in res.updated], ["Renamed title"])
        self.assertEqual(os.listdir(self.out), ["2026-01-10_aaaaaaaa_sourdough-starter.md"])
        self.assertEqual(state["aaaaaaaa-1111"]["updated_at"], "2026-01-12T08:00:00Z")

    def test_unchanged_file_keeps_mtime(self):
        c1 = claude_conv("bbbbbbbb-2222", "Rye", "2026-01-10T10:00:00Z")
        nz.normalize_export(self.convs(c1), self.out, {})
        path = os.path.join(self.out, os.listdir(self.out)[0])
        os.utime(path, (1000, 1000))
        res = nz.normalize_export(self.convs(c1), self.out, {})  # no state: header/content compare
        self.assertEqual(res.adopted + res.unchanged, 1)
        self.assertEqual(os.path.getmtime(path), 1000)

    def test_adopts_existing_file_without_rewriting(self):
        os.makedirs(self.out)
        name = "2026-01-10_cccccccc_old-name.md"
        with open(os.path.join(self.out, name), "w", encoding="utf-8") as f:
            f.write(
                "# Old\n\nFonte: claude.ai | conversa cccccccc-3333 | criada 2026-01-10 | "
                "atualizada 2026-01-11 | 2 mensagens\n\n> legacy\n"
            )
        state = {}
        c = claude_conv("cccccccc-3333", "New name", "2026-01-11T23:59:00Z")
        res = nz.normalize_export(self.convs(c), self.out, state)
        self.assertEqual((res.adopted, len(res.new), len(res.updated)), (1, 0, 0))
        self.assertEqual(state["cccccccc-3333"]["file"], name)
        with open(os.path.join(self.out, name), encoding="utf-8") as f:
            self.assertIn("legacy", f.read())

    def test_skips_conversations_without_text_and_dry_run_writes_nothing(self):
        empty = {"uuid": "dddddddd-4444", "name": "x", "created_at": "2026-01-01",
                 "updated_at": "2026-01-01", "chat_messages": []}
        c = claude_conv("eeeeeeee-5555", "Bread", "2026-01-10T10:00:00Z")
        state = {}
        res = nz.normalize_export(self.convs(empty, c), self.out, state, dry_run=True)
        self.assertEqual((res.skipped_empty, len(res.new)), (1, 1))
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(state, {})


class LoadingTest(unittest.TestCase):
    def test_zip_detects_provider_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            z = write_zip(os.path.join(tmp, "export.zip"),
                          [claude_conv("ffffffff-6666", "A", "2026-01-01T00:00:00Z")])
            with nz.ExtractedExport(z) as root:
                provider, raw = nz.load_conversations(root)
            self.assertEqual((provider, len(raw)), ("claude_ai", 1))
            self.assertFalse(os.path.exists(root))

    def test_zip_slip_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            z = os.path.join(tmp, "evil.zip")
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("../escape.json", "[]")
            with self.assertRaises(ValueError):
                with nz.ExtractedExport(z):
                    pass

    def test_chatgpt_follows_current_branch(self):
        convs = nz.to_conversations("chatgpt", [chatgpt_conv("gg-1", "Bread", 1767312000.0)])
        self.assertEqual(nz.detect_provider([chatgpt_conv("gg-1", "Bread", 1.0)]), "chatgpt")
        self.assertEqual(convs[0].messages, [("user", "how do I bake bread?"), ("assistant", "final answer")])
        self.assertEqual(convs[0].created, "2026-01-01")
        self.assertIn("Fonte: chatgpt | conversa gg-1", convs[0].render())

    def test_cli_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "conversations.json")
            with open(src, "w", encoding="utf-8") as f:
                json.dump([claude_conv("hhhhhhhh-7777", "Cli", "2026-01-01T00:00:00Z")], f)
            out = os.path.join(tmp, "out")
            self.assertEqual(nz.main([src, out]), 0)
            self.assertEqual(len(os.listdir(out)), 1)


if __name__ == "__main__":
    unittest.main()
