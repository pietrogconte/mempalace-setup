"""Scan drawers for sensitive patterns and report them masked.

Nothing is ever deleted or rewritten here, and raw matches never leave this
module: a Finding only carries the masked match and a snippet whose every
match (not only its own) is masked.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, NamedTuple, Optional, Pattern, Sequence, Tuple

from .store import source_name

BULLET = "•"
CONTEXT = 50  # characters of context on each side of a match

# --- military ranks (Brazilian Army, Navy, Air Force), abbreviated and spelled out ---
_ORD = r"(?:[1-3](?:º|°|ª|o)\s?)"
RANKS = [
    # Exército
    "Gen Ex", "Gen Div", "Gen Bda", "Gen", "General", "Cel", "Coronel", "TC", "Ten Cel",
    "Tenente-Coronel", "Tenente Coronel", "Maj", "Major", "Cap", "Capitão",
    _ORD + "Ten", _ORD + "Tenente", "Ten", "Tenente", "Asp", "Asp Of", "Aspirante",
    "ST", "S Ten", "Subten", "Subtenente", _ORD + "Sgt", _ORD + "Sargento", "Sgt", "Sargento",
    "Cb", "Cabo", "Sd", "Soldado",
    # Marinha
    "Alte Esq", "V Alte", "C Alte", "Almirante", "Vice-Almirante", "Contra-Almirante",
    "CMG", "CF", "CC", "CT", "Capitão de Mar e Guerra", "Capitão de Fragata",
    "Capitão de Corveta", "Capitão-Tenente", "1T", "2T", "GM", "Guarda-Marinha",
    "SO", "Suboficial", "1SG", "2SG", "3SG", "CB", "MN", "Marinheiro", "Fuzileiro",
    # Força Aérea
    "Ten Brig", "Maj Brig", "Brig", "Brigadeiro", "Ten Brig Ar", "Maj Brig Ar", "Brig Ar",
    "Cel Av", "TC Av", "Maj Av", "Cap Av", _ORD + "Ten Av", "Asp Av", "1S", "2S", "3S",
    "S1", "S2", "Taifeiro",
]
# Longest first so "Gen Ex" wins over "Gen"; spaces in abbreviations also match a dot ("Ten. Cel").
_RANK_ALT = "|".join(
    r.replace(" ", r"\.?\s") if r.startswith("(?:") else re.escape(r).replace(r"\ ", r"\.?\s")
    for r in sorted(RANKS, key=len, reverse=True)
)
# Spelled-out ranks that are also everyday (or English) words: matches stay, flagged low confidence.
LOW_CONFIDENCE_RANKS = {"General", "Major", "Cabo", "Soldado", "TC"}
HIGH, LOW = "high", "low"

_UPPER = "A-ZÀ-Þ"
_LOWER = "a-zß-ÿ"
# A proper name: capital initial, then at least two lowercase letters ("Silva", "Ávila").
RANK_NAME = re.compile(
    rf"(?<![\w-])(?P<rank>{_RANK_ALT})\.?\s+(?P<name>[{_UPPER}][{_LOWER}]{{2,}})(?![\w])"
)

IPV4 = re.compile(
    r"(?<![\w.-])((?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})(?!\w|\.\d)"
)
GITHUB = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")
SK = re.compile(r"(?<![\w-])sk-(?:ant-|proj-|live-|test-)?[A-Za-z0-9_-]{20,}")
AWS = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")
ENV_LINE = re.compile(
    r"(?m)^[ \t]*(?:export[ \t]+)?(?P<key>[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|CREDENTIALS?))"
    r"[ \t]*=[ \t]*(?P<value>[^\s#]+)"
)
_PLACEHOLDER = re.compile(
    r"""^(?:["']{2}|["']?(?:<.*|\$\{?.*|%.*%|x+|\*+|\.\.\.|(?:your|my|sua|seu|minha|meu)[_-].*|changeme|none|null|true|false|"""
    r"""example.*|placeholder.*|os\.environ.*|getenv.*|process\.env.*|\[REDACTED\]|redacted)["']?)$""",
    re.IGNORECASE,
)
ENV_FILE = re.compile(r"^\.env(?:\..+)?$|\.env$", re.IGNORECASE)


@dataclass
class Finding:
    kind: str
    drawer_id: str
    wing: str
    room: str
    source_file: str
    masked: str
    snippet: str
    value_key: str = ""     # keyed hash of the raw value: groups equal values, never reveals them
    confidence: str = HIGH

    @property
    def source_name(self) -> str:
        return source_name(self.source_file)


class Hit(NamedTuple):
    kind: str
    masked: str
    snippet: str
    value_key: str
    confidence: str


@dataclass
class Rule:
    kind: str
    pattern: Pattern
    mask: Callable[[re.Match], str]
    accept: Callable[[re.Match], bool] = lambda m: True


def _dots(n: int) -> str:
    return BULLET * 4 + f"({n})"


def mask_token(m: re.Match) -> str:
    tok = m.group(0)
    if tok.startswith("github_pat_"):
        prefix = "github_pat_"
    elif tok.startswith("sk-"):
        prefix = re.match(r"sk-(?:ant-|proj-|live-|test-)?", tok).group(0)
    else:
        prefix = tok[:4]
    return prefix + _dots(len(tok) - len(prefix))


def mask_ip(m: re.Match) -> str:
    a, b, _c, _d = m.group(1).split(".")
    return f"{a}.{b}.{BULLET}.{BULLET}"


def mask_rank(m: re.Match) -> str:
    rank = re.sub(r"\s+", " ", m.group("rank"))
    return f"{rank} {m.group('name')[0]}{BULLET * 4}"


def mask_env(m: re.Match) -> str:
    return f"{m.group('key')}={_dots(len(m.group('value')))}"


def mask_generic(m: re.Match) -> str:
    return m.group(0)[:1] + _dots(len(m.group(0)) - 1)


# Well-known public resolvers: textbook examples, not your infrastructure.
PUBLIC_DNS = {"8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9", "149.112.112.112", "208.67.222.222", "208.67.220.220"}


def _ip_ok(m: re.Match) -> bool:
    ip = m.group(1)
    octets = [int(o) for o in ip.split(".")]
    if ip == "0.0.0.0" or ip in PUBLIC_DNS or octets[0] in (127, 255):
        return False
    if 224 <= octets[0] <= 239 or octets[:2] == [169, 254]:  # multicast, link-local
        return False
    # Version-like strings next to a "v"/"version" ("v1.2.3.4") are not addresses.
    before = m.string[max(0, m.start() - 9):m.start()].lower()
    return not re.search(r"(?:\bv|version\s?)$", before)


def _sk_ok(m: re.Match) -> bool:
    body = m.group(0)[3:]
    return bool(re.search(r"\d", body)) and bool(re.search(r"[A-Za-z]", body))


def _env_ok(m: re.Match) -> bool:
    return not _PLACEHOLDER.match(m.group("value"))


DEFAULT_RULES: List[Rule] = [
    Rule("private-key", PRIVATE_KEY, lambda m: m.group(0)[:-5].rstrip("-") + " " + BULLET * 4),
    Rule("github-token", GITHUB, mask_token),
    Rule("sk-key", SK, mask_token, _sk_ok),
    Rule("aws-key", AWS, mask_token),
    Rule("env-secret", ENV_LINE, mask_env, _env_ok),
    Rule("ipv4", IPV4, mask_ip, _ip_ok),
    Rule("rank-name", RANK_NAME, mask_rank),
]


def build_rules(extra: Sequence[Tuple[str, str]] = ()) -> List[Rule]:
    rules = list(DEFAULT_RULES)
    for name, regex in extra:
        rules.append(Rule(name, re.compile(regex), mask_generic))
    return rules


# Per-process key: equal values get equal keys within a run, but a key cannot be
# brute-forced back to its value (a plain hash of an IPv4 could be, 2^32 is small).
_KEY = secrets.token_bytes(32)


def value_key(kind: str, raw: str) -> str:
    return hmac.new(_KEY, f"{kind}|{raw}".encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def confidence(kind: str, m: re.Match) -> str:
    if kind == "rank-name" and re.sub(r"\s+", " ", m.group("rank")) in LOW_CONFIDENCE_RANKS:
        return LOW
    return HIGH


def _raw(m: re.Match) -> str:
    if "rank" in m.re.groupindex:
        return re.sub(r"\s+", " ", m.group("rank")) + " " + m.group("name")
    if "key" in m.re.groupindex:
        return m.group("key") + "=" + m.group("value")
    return m.group(m.lastindex or 0) if m.re.groups == 1 else m.group(0)


Span = Tuple[int, int, str, str, str, str]  # start, end, kind, masked, value_key, confidence


def find_spans(text: str, rules: Sequence[Rule]) -> List[Span]:
    """Non-overlapping spans; earlier rules win overlaps."""
    spans: List[Span] = []
    for rule in rules:
        for m in rule.pattern.finditer(text):
            if not rule.accept(m):
                continue
            s, e = m.span()
            if any(s < sp[1] and sp[0] < e for sp in spans):
                continue
            spans.append((s, e, rule.kind, rule.mask(m), value_key(rule.kind, _raw(m)), confidence(rule.kind, m)))
    spans.sort()
    return spans


def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def scan_text(text: str, rules: Sequence[Rule]) -> List[Hit]:
    """One Hit per match; every match in the snippet is masked, not only its own."""
    spans = find_spans(text, rules)
    if not spans:
        return []
    masked_parts, positions, cursor, out_len = [], [], 0, 0
    for s, e, _kind, masked, _key, _conf in spans:
        masked_parts.append(text[cursor:s])
        out_len += s - cursor
        positions.append((out_len, out_len + len(masked)))
        masked_parts.append(masked)
        out_len += len(masked)
        cursor = e
    masked_parts.append(text[cursor:])
    masked_text = "".join(masked_parts)
    out = []
    for (_s, _e, kind, masked, key, conf), (ms, me) in zip(spans, positions):
        lo, hi = max(0, ms - CONTEXT), min(len(masked_text), me + CONTEXT)
        snippet = ("…" if lo else "") + _one_line(masked_text[lo:hi]) + ("…" if hi < len(masked_text) else "")
        out.append(Hit(kind, masked, snippet, key, conf))
    return out


def scan(drawers: Iterable, rules: Optional[Sequence[Rule]] = None) -> List[Finding]:
    rules = rules if rules is not None else DEFAULT_RULES
    findings: List[Finding] = []
    for d in drawers:
        name = source_name(d.source_file) if d.source_file else ""
        if name and ENV_FILE.search(name):
            findings.append(Finding("env-file", d.drawer_id, d.wing, d.room, d.source_file,
                                    name, "(drawer mined from a .env file; content hidden)",
                                    value_key("env-file", d.source_file)))
            continue
        for h in scan_text(d.text or "", rules):
            findings.append(Finding(h.kind, d.drawer_id, d.wing, d.room, d.source_file,
                                    h.masked, h.snippet, h.value_key, h.confidence))
    return findings


@dataclass
class Group:
    """All occurrences of one value (one IP, one token, one rank + name)."""

    kind: str
    masked: str
    confidence: str
    findings: List[Finding] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.findings)

    @property
    def wings(self) -> List[str]:
        return sorted({f.wing for f in self.findings})


def group(findings: Iterable[Finding]) -> List[Group]:
    """One Group per distinct value, most frequent first."""
    groups: Dict[Tuple[str, str], Group] = {}
    for f in findings:
        g = groups.get((f.kind, f.value_key))
        if g is None:
            g = groups[(f.kind, f.value_key)] = Group(f.kind, f.masked, f.confidence)
        g.findings.append(f)
    return sorted(groups.values(), key=lambda g: (-g.count, g.kind, g.masked))


def summarize(findings: Iterable[Finding]) -> List[Tuple[str, str, int]]:
    """(kind, wing, count), most frequent first."""
    counts = {}
    for f in findings:
        counts[(f.kind, f.wing)] = counts.get((f.kind, f.wing), 0) + 1
    return sorted(((k, w, n) for (k, w), n in counts.items()), key=lambda t: (-t[2], t[0], t[1]))
