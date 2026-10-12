#!/usr/bin/env python3
"""
Wire up MemPalace (https://github.com/MemPalace/mempalace) as an optional
cross-session memory layer for Claude Code. This is a one-time, machine-wide
setup, independent of any project.

What this does:
  1. Finds a mempalace command that ACTUALLY runs, by executing
     `<candidate> --version` (not just checking that a file exists):
       a. the tool's own venv python, `<venv python> -m mempalace`
          (uv tool dir, then pipx venvs);
       b. the `mempalace` launcher on PATH;
       c. this interpreter, `python -m mempalace`.
     The venv python goes first because on Windows with Smart App Control /
     Application Control the unsigned .exe launchers uv/pipx create can be
     blocked - intermittently, so passing --version once proves little.
     Only if nothing runs does it install the `mempalace` CLI
     (uv > pipx > pip) and try again.
  2. Merges Stop / SessionEnd / PreCompact hooks into your GLOBAL Claude Code
     settings (~/.claude/settings.json), using the command that worked plus
     `hook run --hook <name> --harness claude-code`, all with timeout 30.
     Existing MemPalace hooks are updated in place, not duplicated. On
     Windows the command uses "/" separators (hooks run in Git Bash).
  3. Ensures a short recall note in your GLOBAL ~/.claude/CLAUDE.md. If a
     note about MemPalace already exists without the marker (e.g. one you
     wrote by hand, in any language), it is wrapped with the marker instead
     of appending a duplicate.
  4. Prints where the palace actually lives (as resolved by MemPalace's own
     config).

Both files are backed up before being changed. With --dry-run, nothing is
written or installed: the script prints a unified diff of what would change.

What this deliberately does NOT do:
  - Mine any conversation history or project source files. That's a separate,
    explicit choice - run it yourself once you're happy with the setup:
        mempalace mine ~/.claude/projects/ --mode convos   # past conversations
        mempalace mine <some/project/dir>                  # project source files
  - Touch any project/repo. MemPalace's palace lives at your
    OS-standard config path (~/.config/mempalace/palace, i.e.
    %USERPROFILE%\\.config\\mempalace\\palace on Windows), never inside a git
    repo. ~/.mempalace only holds hook state and locks.
  - Register the full MemPalace multi-agent "shared brain" rules block
    (MCP tools, task delegation, logstream watchers). That's a much bigger
    coordination protocol than "don't lose context between sessions" calls
    for - add it yourself later (`mempalace rules --help`) if you actually
    want multi-agent coordination.

Usage:
    python scripts/setup_mempalace.py            # do it
    python scripts/setup_mempalace.py --dry-run   # show what would change
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

IS_WINDOWS = os.name == "nt"

HOOK_TIMEOUT = 30
HOOK_NAMES = {
    "Stop": "stop",
    "SessionEnd": "session-end",
    "PreCompact": "precompact",
}

RECALL_NOTE_MARKER = "<!-- llm-wiki-mempalace:mempalace-recall -->"
RECALL_NOTE_BODY = """## Cross-session memory (MemPalace)

This machine has MemPalace installed (`mempalace` on PATH) for continuity
across long/restarted Claude Code sessions. Global hooks (Stop / SessionEnd /
PreCompact, in `~/.claude/settings.json`) already auto-save conversation
history — no manual action needed for that.

Use recall only when useful:
- If the user asks about something discussed in another session/project, or
  a decision/context you don't have in this conversation, run
  `mempalace search "<query>"` before saying you don't know.
- `mempalace wake-up` gives a broad summary of what's already been recorded.

Don't use this for anything beyond point-in-time recall — no multi-agent
coordination protocol is configured here.
"""

PALACE_PATH_SNIPPET = "from mempalace.config import MempalaceConfig; print(MempalaceConfig().palace_path)"


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


# ---------------------------------------------------------------- 1. command


def venv_python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def tool_venv_pythons() -> list[Path]:
    """Python interpreters of venvs where uv/pipx would have installed mempalace."""
    venv_roots: list[Path] = []

    for tool, cmd in (
        ("uv", ["uv", "tool", "dir"]),
        ("pipx", ["pipx", "environment", "--value", "PIPX_LOCAL_VENVS"]),
    ):
        if shutil.which(tool) is None:
            continue
        try:
            result = run(cmd, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue  # the uv/pipx launcher itself may be blocked too
        if result.returncode == 0 and result.stdout.strip():
            venv_roots.append(Path(result.stdout.strip()))

    # Default locations, in case the uv/pipx launchers can't run.
    home = Path.home()
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA")
        if appdata:
            venv_roots.append(Path(appdata) / "uv" / "tools")
        venv_roots.append(home / "pipx" / "venvs")
    else:
        data_home = os.environ.get("XDG_DATA_HOME") or str(home / ".local" / "share")
        venv_roots.append(Path(data_home) / "uv" / "tools")
    venv_roots.append(home / ".local" / "pipx" / "venvs")

    pythons: list[Path] = []
    for root in venv_roots:
        py = venv_python(root / "mempalace")
        if py.exists() and py not in pythons:
            pythons.append(py)
    return pythons


def candidate_commands() -> list[list[str]]:
    # The venv python comes first: it's a signed python.exe on Windows, whereas the
    # uv/pipx launcher .exe is unsigned and Smart App Control may block it only
    # intermittently - so a launcher that passes --version now can still fail later.
    candidates = [[str(py), "-m", "mempalace"] for py in tool_venv_pythons()]
    launcher = shutil.which("mempalace")
    if launcher:
        candidates.append([launcher])
    candidates.append([sys.executable, "-m", "mempalace"])

    unique: list[list[str]] = []
    for cmd in candidates:
        if cmd not in unique:
            unique.append(cmd)
    return unique


def try_command(cmd: list[str]) -> tuple[bool, str]:
    try:
        result = run([*cmd, "--version"], timeout=60)
    except OSError as e:
        # e.g. Windows Smart App Control / Application Control blocking an unsigned .exe
        return False, f"could not execute ({e})"
    except subprocess.TimeoutExpired:
        return False, "timed out"
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip().splitlines()
        return False, f"exit code {result.returncode}" + (f": {output[-1]}" if output else "")
    return True, result.stdout.strip()


def resolve_mempalace_command() -> list[str] | None:
    for cmd in candidate_commands():
        label = " ".join(cmd)
        ok, info = try_command(cmd)
        if ok:
            print(f"[ok] `{label} --version` -> {info}")
            return cmd
        print(f"[!!] `{label} --version` failed: {info}")
    return None


def install_mempalace() -> bool:
    candidates = [
        ("uv", ["uv", "tool", "install", "mempalace"]),
        ("pipx", ["pipx", "install", "mempalace"]),
        ("pip", [sys.executable, "-m", "pip", "install", "--user", "mempalace"]),
    ]
    for name, cmd in candidates:
        if shutil.which(name) is None and name != "pip":
            continue
        print(f"[..] trying install via {name}: {' '.join(cmd)}")
        try:
            result = run(cmd)
        except OSError as e:
            print(f"[!!] {name} could not execute ({e})")
            continue
        if result.returncode == 0:
            print(f"[ok] installed via {name}.")
            return True
        print(f"[!!] {name} install failed:\n{result.stderr.strip()}")
    return False


def shell_command(cmd: list[str]) -> str:
    """Render tokens as a Git Bash / POSIX shell command line."""
    if IS_WINDOWS:
        cmd = [token.replace("\\", "/") for token in cmd]
    return " ".join(shlex.quote(token) for token in cmd)


# ---------------------------------------------------------------- file writes


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = path.with_suffix(path.suffix + f".bak.{stamp}")
    shutil.copy2(path, backup_path)
    return backup_path


def read_text(path: Path) -> str | None:
    """File contents ("" if it doesn't exist), or None if it can't be read."""
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except (OSError, UnicodeDecodeError) as e:
        print(f"[!!] could not read {path} ({e}) - not touching it.")
        return None


def apply_change(path: Path, old: str, new: str, dry_run: bool) -> bool:
    if dry_run:
        diff = difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"{path} (current)",
            tofile=f"{path} (after setup)",
        )
        print(f"[..] dry-run - would write {path}:")
        sys.stdout.writelines(line if line.endswith("\n") else line + "\n" for line in diff)
        return True

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the file's existing line endings (text mode would turn \n into \r\n on Windows).
        newline = "\r\n" if path.exists() and b"\r\n" in path.read_bytes() else "\n"
        bak = backup(path)
        if bak:
            print(f"[ok] backed up {path} to {bak}")
        with path.open("w", encoding="utf-8", newline=newline) as f:
            f.write(new)
    except OSError as e:
        print(f"[!!] could not write {path} ({e})")
        return False
    print(f"[ok] wrote {path}")
    return True


# ---------------------------------------------------------------- 2. hooks


def merge_hooks(settings_path: Path, mempalace_cmd: list[str], dry_run: bool) -> bool:
    old_text = read_text(settings_path)
    if old_text is None:
        return False
    settings: dict = {}
    if old_text.strip():
        try:
            settings = json.loads(old_text)
        except json.JSONDecodeError as e:
            print(f"[!!] {settings_path} is not valid JSON ({e}) - not touching it. Fix it by hand first.")
            return False
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
        print(f"[!!] {settings_path} has an unexpected structure - not touching it. Fix it by hand first.")
        return False

    hooks = settings.setdefault("hooks", {})
    changed = False

    for event, hook_name in HOOK_NAMES.items():
        command = shell_command([*mempalace_cmd, "hook", "run", "--hook", hook_name, "--harness", "claude-code"])
        entries = hooks.setdefault(event, [])
        existing = [
            h
            for entry in entries
            for h in entry.get("hooks", [])
            if h.get("type") == "command" and f"hook run --hook {hook_name}" in h.get("command", "")
        ]

        if not existing:
            hook_def = {"type": "command", "command": command, "timeout": HOOK_TIMEOUT}
            if event == "Stop":
                entries.append({"matcher": "*", "hooks": [hook_def]})
            else:
                entries.append({"hooks": [hook_def]})
            print(f"[+ ] adding {event} hook: {command}")
            changed = True
            continue

        for h in existing:
            if h.get("command") == command and h.get("timeout") == HOOK_TIMEOUT:
                print(f"[ok] {event} hook already configured - leaving as is.")
                continue
            if h.get("command") != command:
                print(f"[~ ] updating {event} hook command: {h.get('command')} -> {command}")
                h["command"] = command
            if h.get("timeout") != HOOK_TIMEOUT:
                print(f"[~ ] updating {event} hook timeout: {h.get('timeout')} -> {HOOK_TIMEOUT}")
                h["timeout"] = HOOK_TIMEOUT
            changed = True

    if not changed:
        print("[ok] no changes needed in settings.json.")
        return True

    return apply_change(settings_path, old_text, json.dumps(settings, indent=2) + "\n", dry_run)


# ---------------------------------------------------------------- 3. recall note


def find_mempalace_section(lines: list[str]) -> tuple[int, int] | None:
    """(start, end) line range of the first markdown section whose heading mentions MemPalace."""
    heading = re.compile(r"^(#{1,6})\s+(.*)$")
    in_fence = False
    start = level = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = heading.match(line)
        if not m:
            continue
        if start is None:
            if "mempalace" in m.group(2).lower():
                start, level = i, len(m.group(1))
        elif len(m.group(1)) <= level:
            return start, i
    return (start, len(lines)) if start is not None else None


def ensure_recall_note(claude_md_path: Path, dry_run: bool) -> bool:
    existing = read_text(claude_md_path)
    if existing is None:
        return False
    if RECALL_NOTE_MARKER in existing:
        print(f"[ok] recall note already present in {claude_md_path} - leaving as is.")
        return True

    lines = existing.splitlines(keepends=True)
    section = find_mempalace_section(lines)

    if section:
        start, end = section
        body = lines[start:end]
        trailing: list[str] = []
        while body and not body[-1].strip():
            trailing.insert(0, body.pop())
        if body and not body[-1].endswith("\n"):
            body[-1] += "\n"
        new = "".join(
            lines[:start] + [RECALL_NOTE_MARKER + "\n"] + body + [RECALL_NOTE_MARKER + "\n"] + trailing + lines[end:]
        )
        print(f"[~ ] found an existing MemPalace note without the marker ({lines[start].strip()!r}) - wrapping it.")
    else:
        new = existing
        if new and not new.endswith("\n"):
            new += "\n"
        if new:
            new += "\n"
        new += f"{RECALL_NOTE_MARKER}\n{RECALL_NOTE_BODY}{RECALL_NOTE_MARKER}\n"
        print("[+ ] appending recall note.")

    return apply_change(claude_md_path, existing, new, dry_run)


# ---------------------------------------------------------------- 4. palace path


def palace_path(mempalace_cmd: list[str]) -> str | None:
    pythons = [mempalace_cmd[0]] if mempalace_cmd[1:2] == ["-m"] else []
    pythons += [str(p) for p in tool_venv_pythons() if str(p) not in pythons]
    for py in pythons:
        try:
            result = run([py, "-c", PALACE_PATH_SNIPPET], timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

    config = Path.home() / ".config" / "mempalace" / "config.json"
    try:
        return json.loads(config.read_text(encoding="utf-8")).get("palace_path")
    except (OSError, json.JSONDecodeError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing anything.")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        # Diffs may contain characters the console codepage (e.g. cp1252) can't encode.
        sys.stdout.reconfigure(errors="replace")

    home = Path.home()
    settings_path = home / ".claude" / "settings.json"
    claude_md_path = home / ".claude" / "CLAUDE.md"

    print("== 1. mempalace command ==")
    mempalace_cmd = resolve_mempalace_command()
    if mempalace_cmd is None:
        if args.dry_run:
            print("[..] dry-run - would try to install mempalace (uv > pipx > pip) and check again.")
        elif install_mempalace():
            mempalace_cmd = resolve_mempalace_command()
    if mempalace_cmd is None:
        print(
            "[!!] No working mempalace command. Install it manually, e.g.:\n"
            "     uv tool install mempalace\n"
            "     (see https://github.com/MemPalace/mempalace for other options)\n"
            "     If the launcher is blocked (Windows Smart App Control), run it as\n"
            "     <tool venv python> -m mempalace - this script tries that automatically."
        )
        sys.exit(1)
    print(f"[ok] hooks will use: {shell_command(mempalace_cmd)}")

    print("\n== 2. Claude Code hooks (global) ==")
    hooks_ok = merge_hooks(settings_path, mempalace_cmd, args.dry_run)

    print("\n== 3. Recall note (global CLAUDE.md) ==")
    note_ok = ensure_recall_note(claude_md_path, args.dry_run)

    print("\n== 4. Palace location ==")
    path = palace_path(mempalace_cmd)
    print(f"[ok] palace: {path}" if path else "[!!] could not determine the palace path.")
    print(f"     (~/.mempalace = {home / '.mempalace'} only holds hook state and locks)")

    if not (hooks_ok and note_ok):
        failed = [name for name, ok in (("hooks", hooks_ok), ("recall note", note_ok)) if not ok]
        print(f"\n== Failed: {', '.join(failed)} - see [!!] messages above ==")
        sys.exit(1)

    print("\n== Done ==")
    if args.dry_run:
        print("This was a dry run - nothing was written. Re-run without --dry-run to apply.")
    else:
        mp = shell_command(mempalace_cmd)
        print(
            "Restart Claude Code for the hooks to take effect (hooks load once, at session "
            "start - this is a Claude Code limitation, not this script's).\n"
            "Optional next steps, run yourself when ready:\n"
            f"  {mp} mine ~/.claude/projects/ --mode convos   # backfill past conversations\n"
            f"  {mp} mine <project-dir>                       # index a project's source files\n"
        )


if __name__ == "__main__":
    main()
