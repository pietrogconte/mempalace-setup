import hashlib
import os
import tempfile
import unittest

from tests import viewer_helpers as vh
from mpview import audit, store
from mpview.store import Drawer

# Every secret below is fictitious and built at runtime so no scanner mistakes this file for a leak.
GHP = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
PAT = "github_pat_" + "11ABCDEFG0" + "x" * 50
SK = "sk-" + "proj-" + "abcDEF123456ghiJKL789012mno"
SK_ANT = "sk-ant-" + "api03-" + "Zz9" * 10
AKIA = "AKIA" + "IOSFODNN7EXAMPLE"
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
DOTS = audit.BULLET * 4


def kinds(text):
    return [h.kind for h in audit.scan_text(text, audit.DEFAULT_RULES)]


def one(text):
    found = audit.scan_text(text, audit.DEFAULT_RULES)
    assert len(found) == 1, found
    return found[0]


class PatternTest(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual(kinds(f"token {GHP} here"), ["github-token"])
        self.assertEqual(kinds(f"pat={PAT}"), ["github-token"])
        self.assertEqual(kinds(f"OPENAI {SK}"), ["sk-key"])
        self.assertEqual(kinds(f"key: {SK_ANT}"), ["sk-key"])
        self.assertEqual(kinds(f"aws {AKIA} ok"), ["aws-key"])
        self.assertEqual(kinds(PEM), ["private-key"])

    def test_token_false_positives(self):
        self.assertEqual(kinds("use scikit-learn and sk-learn-style-names-without-digits"), [])
        self.assertEqual(kinds("the task-abcdefghijklmnopqrstuv123 id"), [])
        self.assertEqual(kinds("ghp_short"), [])

    def test_ipv4(self):
        self.assertEqual(kinds("server at 192.168.10.20:8080"), ["ipv4"])
        self.assertEqual(kinds("ip 10.0.0.5."), ["ipv4"])
        for text in ("bind 127.0.0.1", "listen 0.0.0.0", "mask 255.255.255.0", "version 1.2.3.4",
                     "v10.2.3.4", "pkg-1.5.9.0", "1.2.3.4.5", "999.1.1.1",
                     "mdns 224.0.0.251", "ssdp 239.255.255.250", "apipa 169.254.10.3",
                     "dns 8.8.8.8", "dns 8.8.4.4", "dns 1.1.1.1", "dns 9.9.9.9"):
            self.assertEqual(kinds(text), [], text)

    def test_env(self):
        self.assertEqual(kinds("OPENAI_API_KEY=abc123xyz"), ["env-secret"])
        self.assertEqual(kinds("export DB_PASSWORD = hunter22"), ["env-secret"])
        for text in ("API_KEY=", "API_KEY=<your key>", "API_KEY=${API_KEY}", "SECRET_KEY=changeme",
                     "OPENAI_API_KEY=sua_chave_aqui", "TOKEN=os.environ['X']", "PASSWORD=xxxx",
                     'API_KEY=""', "api_key=abc123"):
            self.assertEqual(kinds(text), [], text)

    def test_ranks(self):
        cases = [
            ("o Cap Silva disse", "Cap", "Silva"),
            ("falar com o 2º Sgt Souza", "2º Sgt", "Souza"),
            ("o 1o Ten. Rocha", "1o Ten", "Rocha"),
            ("Ten Cel Ávila assinou", "Ten Cel", "Ávila"),
            ("o CMG Pereira", "CMG", "Pereira"),
            ("Capitão de Corveta Lima", "Capitão de Corveta", "Lima"),
            ("Brig Ar Costa", "Brig Ar", "Costa"),
            ("o Maj Brig Ramos", "Maj Brig", "Ramos"),
            ("1S Almeida", "1S", "Almeida"),
            ("Sd Ferreira", "Sd", "Ferreira"),
        ]
        for text, rank, name in cases:
            h = one(text)
            self.assertEqual((h.kind, h.confidence), ("rank-name", "high"), text)
            self.assertEqual(h.masked, f"{rank} {name[0]}{DOTS}", text)
            self.assertNotIn(name, h.snippet)

    def test_rank_confidence(self):
        for text in ("o General Lima", "Major Tom", "Cabo Verde", "Soldado Ryan", "para TC Zhang"):
            self.assertEqual(one(text).confidence, "low", text)
        for text in ("Gen Lima", "Maj Lima", "Cb Lima", "Sd Lima", "Ten Cel Lima", "Capitão Lima"):
            self.assertEqual(one(text).confidence, "high", text)
        self.assertEqual(one(f"tok {GHP}").confidence, "high")

    def test_rank_requires_capitalized_name(self):
        for text in ("o cap silva", "Cap de", "Sgt X", "Cap 3", "o Capitão disse", "SGT SOUZA", "escapitão Silva"):
            self.assertEqual(kinds(text), [], text)


class MaskingTest(unittest.TestCase):
    def test_masked_values(self):
        self.assertEqual(one(f"token {GHP}").masked, f"ghp_{DOTS}(36)")
        self.assertEqual(one("ip 192.168.10.20").masked, f"192.168.{audit.BULLET}.{audit.BULLET}")
        self.assertEqual(one("DB_PASSWORD=hunter22").masked, f"DB_PASSWORD={DOTS}(8)")

    def test_snippet_masks_every_match(self):
        text = f"first {GHP} then 10.1.2.3 and Cap Silva\nand " + "x" * 200
        found = audit.scan_text(text, audit.DEFAULT_RULES)
        self.assertEqual(len(found), 3)
        for h in found:
            for secret in (GHP[4:], "10.1.2.3", "Silva"):
                self.assertNotIn(secret, h.snippet)
            self.assertNotIn("\n", h.snippet)

    def test_no_raw_value_in_findings(self):
        drawers = [Drawer("d1", "w", "r", "C:\\x\\notes.md", "", f"a {SK} b {AKIA} c\n{PEM}")]
        found = audit.scan(drawers)
        self.assertEqual(sorted(f.kind for f in found), ["aws-key", "private-key", "sk-key"])
        for f in found:
            for secret in (SK[8:], AKIA[4:]):
                self.assertNotIn(secret, f"{f.masked} {f.snippet} {f.value_key}")

    def test_extra_pattern(self):
        rules = audit.build_rules([("cpf", r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")])
        found = audit.scan_text("cpf 123.456.789-09 fim", rules)
        self.assertEqual([(h.kind, h.masked) for h in found], [("cpf", f"1{DOTS}(13)")])


class ScanTest(unittest.TestCase):
    def test_scan_and_summary(self):
        drawers = [
            Drawer("d1", "notes", "r", "C:\\n\\a.md", "", f"x {GHP}"),
            Drawer("d2", "notes", "r", "C:\\n\\b.md", "", "Cap Silva e 10.0.0.9"),
            Drawer("d3", "infra", "r", "/srv/app/.env", "", "SECRET=whatever"),
            Drawer("d4", "infra", "r", "/srv/app/prod.env", "", "nothing"),
            Drawer("d5", "notes", "r", "C:\\n\\c.md", "", "clean text"),
        ]
        found = audit.scan(drawers)
        self.assertEqual(sorted((f.drawer_id, f.kind) for f in found), [
            ("d1", "github-token"), ("d2", "ipv4"), ("d2", "rank-name"),
            ("d3", "env-file"), ("d4", "env-file"),
        ])
        env = [f for f in found if f.drawer_id == "d3"][0]
        self.assertNotIn("whatever", env.snippet)
        self.assertEqual(env.source_name, ".env")
        self.assertEqual(audit.summarize(found)[0], ("env-file", "infra", 2))


class GroupTest(unittest.TestCase):
    def test_one_group_per_value(self):
        drawers = [
            Drawer("d1", "net", "r", "a.md", "", "gw 192.168.1.1 and 192.168.1.2"),
            Drawer("d2", "net", "r", "b.md", "", "again 192.168.1.1"),
            Drawer("d3", "chat", "r", "c.md", "", "gw 192.168.1.1, Cap Silva, General Lima"),
            Drawer("d4", "chat", "r", "d.md", "", "Cap  Silva"),
        ]
        groups = audit.group(audit.scan(drawers))
        mask = f"192.168.{audit.BULLET}.{audit.BULLET}"
        self.assertEqual([(g.kind, g.masked, g.count, g.wings, g.confidence) for g in groups], [
            ("ipv4", mask, 3, ["chat", "net"], "high"),
            ("rank-name", f"Cap S{DOTS}", 2, ["chat"], "high"),
            ("ipv4", mask, 1, ["net"], "high"),  # .2: same mask, different value
            ("rank-name", f"General L{DOTS}", 1, ["chat"], "low"),
        ])
        self.assertEqual([f.drawer_id for f in groups[0].findings], ["d1", "d2", "d3"])

    def test_keys_are_not_plain_hashes(self):
        key = audit.value_key("ipv4", "10.0.0.1")
        self.assertEqual(key, audit.value_key("ipv4", "10.0.0.1"))
        self.assertNotEqual(key, audit.value_key("ipv4", "10.0.0.2"))
        for plain in (b"10.0.0.1", b"ipv4|10.0.0.1"):
            self.assertNotIn(key, hashlib.sha256(plain).hexdigest())


class FixtureAuditTest(unittest.TestCase):
    def test_store_to_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            vh.make_palace(tmp, [vh.drawer(1, text=f"leak {GHP}"), vh.drawer(2, text="ok")])
            found = audit.scan(store.iter_drawers(os.path.join(tmp, "chroma.sqlite3")))
            self.assertEqual([(f.drawer_id, f.kind) for f in found], [("drawer_notes_1", "github-token")])


if __name__ == "__main__":
    unittest.main()
