"""Viewer settings: the [viewer] table of ~/.config/mempalace-sync/config.toml."""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

from mpsync.config import Config, ConfigError, expand, is_inside, load_config

DEFAULT_PORT = 8501


def default_snapshot_dir() -> str:
    """A local, never-synced cache folder: %LOCALAPPDATA% on Windows, ~/.cache elsewhere."""
    local = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local:
        return os.path.join(local, "mempalace-viewer", "snapshot")
    return expand("~/.cache/mempalace-viewer/snapshot")


def is_loopback(address: str) -> bool:
    if address == "localhost":
        return True
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


@dataclass
class ExtraPattern:
    name: str
    regex: str


@dataclass
class ViewerSettings:
    sync: Config
    snapshot_dir: str
    port: int
    language: str
    mempalace_python: str
    collection_name: str
    extra_patterns: List[ExtraPattern] = field(default_factory=list)

    @property
    def palace(self) -> str:
        return self.sync.palace

    @property
    def reports(self) -> str:
        return self.sync.reports


def bridge_python(cmd: List[str], override: str = "") -> str:
    """The python of MemPalace's venv, taken from mempalace.command = [python, -m, mempalace]."""
    if override:
        return expand(override)
    if len(cmd) >= 3 and cmd[1] == "-m" and cmd[2] == "mempalace":
        return cmd[0]
    raise ConfigError(
        "viewer: cannot derive MemPalace's python from mempalace.command; "
        "set [viewer] mempalace_python"
    )


def collection_name(home: Optional[str] = None) -> str:
    """Drawers collection name, the way MemPalace reads it from its config.json."""
    home = home or os.path.expanduser("~")
    try:
        with open(os.path.join(home, ".config", "mempalace", "config.json"), encoding="utf-8") as f:
            return json.load(f).get("collection_name") or "mempalace_drawers"
    except (OSError, ValueError, AttributeError):
        return "mempalace_drawers"


def parse_viewer(cfg: Config) -> ViewerSettings:
    raw = cfg.viewer
    snapshot_dir = expand(raw.get("snapshot_dir", "")) or default_snapshot_dir()
    if is_inside(snapshot_dir, cfg.palace) or is_inside(cfg.palace, snapshot_dir):
        raise ConfigError("viewer.snapshot_dir must be outside the palace (and not contain it)")
    port = int(raw.get("port", DEFAULT_PORT))
    if not 1024 <= port <= 65535:
        raise ConfigError("viewer.port must be between 1024 and 65535")
    extras = []
    for i, item in enumerate(raw.get("audit_extra_patterns", [])):
        if not isinstance(item, dict) or not item.get("name") or not item.get("regex"):
            raise ConfigError(f"viewer.audit_extra_patterns[{i}]: 'name' and 'regex' are required")
        extras.append(ExtraPattern(str(item["name"]), str(item["regex"])))
    return ViewerSettings(
        sync=cfg,
        snapshot_dir=snapshot_dir,
        port=port,
        language=str(raw.get("language", cfg.report_language)),
        mempalace_python=bridge_python(cfg.mempalace_cmd, raw.get("mempalace_python", "")),
        collection_name=str(raw.get("collection_name", "")) or collection_name(),
        extra_patterns=extras,
    )


def load_settings(path: str) -> ViewerSettings:
    return parse_viewer(load_config(path))
