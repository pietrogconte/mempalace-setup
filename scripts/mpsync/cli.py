"""Command line: run (default), normalize, task."""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from typing import List, Optional

from . import __version__
from .config import DEFAULT_CONFIG_PATH, ConfigError, load_config


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="mempalace_sync.py",
        description="Idempotent capture of agent sessions, folders and chat exports into MemPalace.",
    )
    ap.add_argument("--version", action="version", version=f"mempalace-sync {__version__}")
    sub = ap.add_subparsers(dest="command")

    run = sub.add_parser("run", help="sync everything (default)")
    run.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    run.add_argument("--dry-run", action="store_true", help="show what would be mined; write nothing to the palace")
    run.add_argument("--verbose", "-v", action="store_true", help="debug log, including MemPalace output")
    run.add_argument("--only", action="append", metavar="NAME",
                     help="only this source name (repeatable); 'inbox' for the export inbox")
    run.add_argument("--lang", choices=("pt", "en"), default=None, help="report language (default: config report_language)")

    norm = sub.add_parser("normalize", help="normalize a claude.ai/ChatGPT export into .md transcripts", add_help=False)
    norm.add_argument("rest", nargs=argparse.REMAINDER)

    task = sub.add_parser("task", help="manage the Windows scheduled task")
    task.add_argument("action", choices=("install", "remove", "show", "run"))
    task.add_argument("--at", default="21:00", help="daily time HH:MM (default 21:00)")
    task.add_argument("--config", default=None, help="config path passed to the task (default: standard path)")
    task.add_argument("--python", default=None, help="interpreter for the task (default: this one, as pythonw.exe)")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version"):
        argv.insert(0, "run")
    args = _build_parser().parse_args(argv)

    if args.command == "normalize":
        from .normalize import main as normalize_main

        return normalize_main(args.rest)

    if args.command == "task":
        from . import task

        if args.action == "install":
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", args.at):
                print("--at must be HH:MM")
                return 2
            return task.install(args.at, args.config, args.python)
        return {"remove": task.remove, "show": task.show, "run": task.run_now}[args.action]()

    from .runner import Runner
    from .sync import run, setup_logging

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    lang = args.lang or cfg.report_language
    setup_logging(cfg.log_dir, args.verbose, _dt.date.today().isoformat())
    runner = Runner(cfg.mempalace_cmd, cfg.palace, cfg.agent, cfg.mine_timeout_seconds)
    return run(cfg, runner, dry_run=args.dry_run, only=args.only, lang=lang)

