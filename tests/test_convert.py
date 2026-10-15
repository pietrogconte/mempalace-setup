import json
import unittest

from tests import helpers  # noqa: F401  (sys.path)
from mpsync.convert import converter_for, html_to_markdown, ipynb_to_markdown

B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==" * 4


class HtmlTest(unittest.TestCase):
    def test_strips_markup_css_js_and_base64(self):
        page = (
            "<!doctype html><html><head><title>Aula 1</title>"
            "<style>body { color: red }</style><script>var secret = 1;</script></head>"
            "<body><h1>Pandas</h1><p>Read a <b>CSV</b> with <code>pd.read_csv</code>.</p>"
            f'<img src="data:image/png;base64,{B64}">'
            "<ul><li>one</li><li>two</li></ul>"
            "<table><tr><th>col</th><th>type</th></tr><tr><td>a</td><td>int</td></tr></table>"
            '<pre>df = pd.read_csv("x.csv")\nprint(df)</pre><!-- comment --></body></html>'
        )
        md = html_to_markdown(page)
        for gone in ("<", "color: red", "secret", "base64", "iVBOR", "comment"):
            self.assertNotIn(gone, md)
        self.assertTrue(md.startswith("# Aula 1"))
        self.assertIn("# Pandas", md)
        self.assertIn("Read a CSV with `pd.read_csv`.", md)
        self.assertIn("- one", md)
        self.assertIn("| col | type |", md)
        self.assertIn('```\ndf = pd.read_csv("x.csv")\nprint(df)\n```', md)

    def test_entities_unescaped(self):
        self.assertIn("a < b & c", html_to_markdown("<p>a &lt; b &amp; c</p>"))

    def test_inline_base64_text_removed(self):
        self.assertNotIn("iVBOR", html_to_markdown(f"<p>x {B64} y</p>"))


class NotebookTest(unittest.TestCase):
    def test_keeps_cells_drops_outputs(self):
        nb = {
            "metadata": {"kernelspec": {"language": "python"}},
            "cells": [
                {"cell_type": "markdown", "source": ["# Title\n", "text"]},
                {"cell_type": "code", "source": "print(1)", "outputs": [{"data": {"image/png": B64}}]},
                {"cell_type": "code", "source": "", "outputs": []},
            ],
        }
        self.assertEqual(ipynb_to_markdown(json.dumps(nb)), "# Title\ntext\n\n```python\nprint(1)\n```\n")

    def test_converter_for(self):
        self.assertIsNotNone(converter_for("A.HTML", ["html"]))
        self.assertIsNone(converter_for("a.html", ["ipynb"]))
        self.assertIsNone(converter_for("a.md", ["html", "ipynb"]))


if __name__ == "__main__":
    unittest.main()
