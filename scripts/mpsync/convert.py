"""Convert HTML and Jupyter notebooks to plain markdown before mining.

HTML: keeps headings, paragraphs, lists, tables, code and link text; drops
<script>/<style>/<svg>/<noscript>/<template>, comments, attributes and any
embedded data: URIs (base64 images, fonts). Notebooks: markdown cells as-is,
code cells fenced, outputs dropped.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import List, Optional

_DROP = {"script", "style", "noscript", "svg", "template", "head", "iframe", "object", "canvas", "math"}
_BLOCK = {
    "p", "div", "section", "article", "main", "header", "footer", "aside", "nav",
    "blockquote", "figure", "figcaption", "form", "fieldset", "details", "summary",
    "dl", "dt", "dd", "ul", "ol", "table", "thead", "tbody", "tfoot", "hr", "br",
}
_DATA_URI = re.compile(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=\s]{16,}")
_LONG_B64 = re.compile(r"[A-Za-z0-9+/=]{200,}")


def strip_embedded(text: str) -> str:
    text = _DATA_URI.sub("", text)
    return _LONG_B64.sub("", text)


class _HTMLToMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self.drop_depth = 0
        self.pre_depth = 0
        self.title: Optional[str] = None
        self._in_title = False
        self._list_stack: List[str] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None

    # -- helpers ---------------------------------------------------------
    def _emit(self, s: str) -> None:
        if self._cell is not None:
            self._cell.append(s)
        else:
            self.out.append(s)

    def _newline(self, n: int = 1) -> None:
        if self._cell is not None:
            self._cell.append(" ")
        else:
            self.out.append("\n" * n)

    # -- parser callbacks ------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
            return
        if tag in _DROP:
            self.drop_depth += 1
            return
        if self.drop_depth:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._newline(2)
            self._emit("#" * int(tag[1]) + " ")
        elif tag == "pre":
            self.pre_depth += 1
            self._newline(2)
            self._emit("```\n")
        elif tag == "code" and not self.pre_depth:
            self._emit("`")
        elif tag in ("ul", "ol"):
            self._list_stack.append(tag)
            self._newline()
        elif tag == "li":
            self._newline()
            indent = "  " * max(0, len(self._list_stack) - 1)
            self._emit(indent + ("1. " if self._list_stack[-1:] == ["ol"] else "- "))
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag in _BLOCK:
            self._newline(2 if tag in ("p", "blockquote", "table", "hr") else 1)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            return
        if tag in _DROP:
            self.drop_depth = max(0, self.drop_depth - 1)
            return
        if self.drop_depth:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._newline(2)
        elif tag == "pre":
            self.pre_depth = max(0, self.pre_depth - 1)
            self._emit("\n```")
            self._newline(2)
        elif tag == "code" and not self.pre_depth:
            self._emit("`")
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self._newline()
        elif tag in ("td", "th") and self._cell is not None:
            cell = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self._cell = None
            if self._row is not None:
                self._row.append(cell)
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.out.append("\n| " + " | ".join(self._row) + " |")
            self._row = None
        elif tag in _BLOCK:
            self._newline()

    def handle_startendtag(self, tag, attrs):
        if tag in ("br", "hr") and not self.drop_depth:
            self._newline()

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data
            return
        if self.drop_depth:
            return
        if self.pre_depth:
            self._emit(data)
        else:
            self._emit(re.sub(r"\s+", " ", data))

    def handle_comment(self, data):
        pass


def html_to_markdown(source: str) -> str:
    parser = _HTMLToMarkdown()
    parser.feed(source)
    parser.close()
    body = "".join(parser.out)
    body = strip_embedded(body)  # charrefs already decoded by the parser
    lines = [line.rstrip() for line in body.splitlines()]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    title = re.sub(r"\s+", " ", parser.title or "").strip()
    first = text.split("\n", 1)[0].lstrip("# ").strip()
    if title and title != first:
        text = f"# {title}\n\n{text}"
    return text + "\n" if text else ""


def ipynb_to_markdown(source: str) -> str:
    nb = json.loads(source)
    lang = (
        ((nb.get("metadata") or {}).get("kernelspec") or {}).get("language")
        or ((nb.get("metadata") or {}).get("language_info") or {}).get("name")
        or "python"
    )
    parts: List[str] = []
    for cell in nb.get("cells") or []:
        src = cell.get("source", "")
        if isinstance(src, list):
            src = "".join(src)
        src = strip_embedded(src).strip()
        if not src:
            continue
        kind = cell.get("cell_type")
        if kind == "markdown":
            parts.append(src)
        elif kind == "code":
            parts.append(f"```{lang}\n{src}\n```")
        else:
            parts.append(src)
    return ("\n\n".join(parts) + "\n") if parts else ""


CONVERTERS = {
    "html": ((".html", ".htm"), html_to_markdown),
    "ipynb": ((".ipynb",), ipynb_to_markdown),
}


def converter_for(filename: str, enabled: List[str]):
    low = filename.lower()
    for name in enabled:
        exts, fn = CONVERTERS[name]
        if low.endswith(exts):
            return fn
    return None
