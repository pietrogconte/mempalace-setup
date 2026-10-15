"""Load and validate ~/.config/mempalace-sync/config.toml."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

DEFAULT_CONFIG_PATH = "~/.config/mempalace-sync/config.toml"
MODES = ("projects", "convos")
LOCK_POLICIES = ("wait", "skip")
EXPORT_PROVIDERS = ("claude_ai", "chatgpt")


class ConfigError(ValueError):
    pass


def expand(path: str) -> str:
    if not path:
        return ""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(path)))


def is_inside(child: str, parent: str) -> bool:
    child = os.path.normcase(os.path.realpath(child))
    parent = os.path.normcase(os.path.realpath(parent))
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:  # different drives on Windows
        return False


@dataclass
class Source:
    name: str
    path: str
    wing: str
    mode: str = "projects"
    include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    convert: List[str] = field(default_factory=list)
    enabled: bool = True

    @property
    def staged(self) -> bool:
        """Filtered or converted sources are mined from a staging copy."""
        return bool(self.include or self.exclude or self.convert)


@dataclass
class ExportTarget:
    provider: str
    wing: str
    normalized_dir: str


@dataclass
class Config:
    path: str
    mempalace_cmd: List[str]
    palace: str
    lock_policy: str
    lock_wait_seconds: int
    lock_poll_seconds: int
    mine_timeout_seconds: int
    agent: str
    report_language: str
    inbox: str
    processed: str
    reports: str
    staging: str
    state_dir: str
    wiki_sources: str
    sources: List[Source]
    exports: Dict[str, ExportTarget]

    @property
    def state_file(self) -> str:
        return os.path.join(self.state_dir, "state.json")

    @property
    def log_dir(self) -> str:
        return os.path.join(self.state_dir, "logs")


def default_palace_path() -> str:
    """Palace path the way MemPalace resolves it by default."""
    cfg = os.path.join(os.path.expanduser("~"), ".config", "mempalace", "config.json")
    try:
        with open(cfg, encoding="utf-8") as f:
            value = json.load(f).get("palace_path")
        if value:
            return expand(value)
    except (OSError, ValueError, AttributeError):
        pass
    return expand("~/.config/mempalace/palace")


def _str_list(value, where: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: expected a list of strings")
    return list(value)


def load_config(path: str = DEFAULT_CONFIG_PATH) -> Config:
    path = expand(path)
    if not os.path.isfile(path):
        raise ConfigError(
            f"config not found: {path} (copy config.example.toml there and edit it)"
        )
    with open(path, "rb") as f:
        try:
            data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: {exc}") from exc
    return parse_config(data, path)


def parse_config(data: dict, path: str = "<memory>") -> Config:
    mp = data.get("mempalace", {})
    cmd = _str_list(mp.get("command"), "mempalace.command")
    if not cmd:
        raise ConfigError("mempalace.command is required, e.g. [\"<python>\", \"-m\", \"mempalace\"]")
    lock_policy = mp.get("lock_policy", "wait")
    if lock_policy not in LOCK_POLICIES:
        raise ConfigError(f"mempalace.lock_policy must be one of {LOCK_POLICIES}")

    paths = data.get("paths", {})
    exports_root = expand(paths.get("exports", "~/exports"))
    inbox = expand(paths.get("inbox", "")) or os.path.join(exports_root, "inbox")
    cfg = Config(
        path=path,
        mempalace_cmd=cmd,
        palace=expand(mp.get("palace", "")) or default_palace_path(),
        lock_policy=lock_policy,
        lock_wait_seconds=int(mp.get("lock_wait_seconds", 600)),
        lock_poll_seconds=max(1, int(mp.get("lock_poll_seconds", 15))),
        mine_timeout_seconds=int(mp.get("mine_timeout_seconds", 3600)),
        agent=str(mp.get("agent", "mempalace-sync")),
        report_language=str(data.get("report_language", "en")),
        inbox=inbox,
        processed=expand(paths.get("processed", "")) or os.path.join(inbox, "processed"),
        reports=expand(paths.get("reports", "")) or os.path.join(exports_root, "reports"),
        staging=expand(paths.get("staging", "")) or os.path.join(exports_root, "staging"),
        state_dir=expand(paths.get("state_dir", "")) or os.path.dirname(expand(path)),
        wiki_sources=expand(paths.get("wiki_sources", "")),
        sources=[],
        exports={},
    )

    names = set()
    for i, raw in enumerate(data.get("source", [])):
        where = f"source[{i}]"
        for key in ("name", "path", "wing"):
            if not raw.get(key):
                raise ConfigError(f"{where}: '{key}' is required")
        src = Source(
            name=raw["name"],
            path=expand(raw["path"]),
            wing=raw["wing"],
            mode=raw.get("mode", "projects"),
            include=_str_list(raw.get("include"), f"{where}.include"),
            exclude=_str_list(raw.get("exclude"), f"{where}.exclude"),
            convert=_str_list(raw.get("convert"), f"{where}.convert"),
            enabled=bool(raw.get("enabled", True)),
        )
        if src.mode not in MODES:
            raise ConfigError(f"{where}: mode must be one of {MODES}")
        bad = set(src.convert) - {"html", "ipynb"}
        if bad:
            raise ConfigError(f"{where}: unknown convert {sorted(bad)} (use html, ipynb)")
        if src.staged and src.mode != "projects":
            raise ConfigError(f"{where}: include/exclude/convert only apply to mode = \"projects\"")
        if src.name in names:
            raise ConfigError(f"{where}: duplicate name '{src.name}'")
        if src.staged and is_inside(cfg.staging, src.path):
            raise ConfigError(f"{where}: paths.staging must be outside the source folder")
        names.add(src.name)
        cfg.sources.append(src)

    for provider, raw in data.get("exports", {}).items():
        if provider not in EXPORT_PROVIDERS:
            raise ConfigError(f"exports.{provider}: unknown provider (use {EXPORT_PROVIDERS})")
        if not raw.get("wing") or not raw.get("normalized_dir"):
            raise ConfigError(f"exports.{provider}: 'wing' and 'normalized_dir' are required")
        cfg.exports[provider] = ExportTarget(provider, raw["wing"], expand(raw["normalized_dir"]))
    return cfg
