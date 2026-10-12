# mempalace-setup

[Português](README.md) | **English**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)

**Machine-wide** setup of [MemPalace](https://github.com/MemPalace/mempalace) for Claude Code: a script that configures the hooks that auto-save your conversation history, plus a minimal recall note in your global `~/.claude/CLAUDE.md`. Run it once per machine — it doesn't belong to any specific project or repository. Works on Windows with Smart App Control turned on.

## Setup

```
python scripts/setup_mempalace.py --dry-run   # preview changes (prints a diff, writes nothing)
python scripts/setup_mempalace.py             # apply
```

After applying, restart Claude Code — hooks are only loaded at session start.

The script:
- Looks for a `mempalace` command that **actually runs**, by executing `--version`: first `<tool venv python> -m mempalace`, then the `mempalace` launcher on PATH. It only installs (`uv` → `pipx` → `pip`) if none works.
- Configures global Claude Code hooks (`Stop`/`SessionEnd`/`PreCompact`, timeout 30) with the command that worked + `hook run` — no `.sh` scripts involved, so it works the same on Windows/Linux/macOS. Existing MemPalace hooks are updated, not duplicated. Backs up `settings.json` first.
- Ensures a minimal recall note in your global `~/.claude/CLAUDE.md`. If a MemPalace note already exists without the marker (hand-written, any language), it gets wrapped with the marker instead of duplicated.
- Prints where the palace lives.
- Exits with code 1 if any step fails (e.g. `settings.json` with invalid JSON — it leaves the file untouched).

What it deliberately does **not** do automatically (your call, whenever you want it):
```
mempalace mine ~/.claude/projects/ --mode convos   # mine past conversations
mempalace mine <project-dir>                        # mine a project's source/docs
```

It also doesn't register the `mempalace rules` block (the full multi-agent coordination protocol, MCP with 45 tools) — that's a much bigger scope than "memory across sessions." If you want that, it's a separate decision (`mempalace rules --help`).

## Where the palace lives (and how to check)

- **Palace (the data):** `~/.config/mempalace/palace` — on Windows, `%USERPROFILE%\.config\mempalace\palace`. The path comes from `palace_path` in `~/.config/mempalace/config.json`.
- **`~/.mempalace`:** only hook state and locks (`hook_state/`, `locks/`). It is not a second palace.

There is **one palace per machine**, shared by all your projects: a search from one project can surface conversations from another. If you need real isolation, point `palace_path` at different locations or use separate profiles/machines.

To check (use the tool's venv python — see the Windows section below):
```
<python> -m mempalace status    # drawer counts per wing/room
<python> -c "from mempalace.config import MempalaceConfig; print(MempalaceConfig().palace_path)"
```
`setup_mempalace.py` also prints the real path at the end.

## Windows: Smart App Control / Application Control

The `.exe` launchers `uv`/`pipx` create (e.g. `~/.local/bin/mempalace.exe`) are unsigned, and Smart App Control (or another Application Control policy) may block them — sometimes intermittently. The tool venv's `python.exe` is signed, so the reliable route is to call the module:

```
C:/Users/<you>/AppData/Roaming/uv/tools/mempalace/Scripts/python.exe -m mempalace status
```

The script already prefers this form and writes it into the hooks with `/` separators (hooks run in Git Bash). Use the same prefix in place of `mempalace` in the commands in this README. Blocks show up in Event Viewer under *Microsoft-Windows-CodeIntegrity/Operational*.

## Using it with an LLM Wiki

It pairs well with [llm-wiki-template](https://github.com/pietrogconte/llm-wiki-template), but the two are independent: the wiki is a per-project template; this setup is per machine.

| | LLM Wiki (`wiki/`) | MemPalace |
|---|---|---|
| What it holds | **Curated** synthesis — only what the agent decided was worth turning into a page | **Verbatim** history of everything — every conversation, unfiltered |
| Where it lives | Inside the wiki's repository, versioned in git | Outside any repo, in a single per-machine palace (`~/.config/mempalace/palace`), **shared across all your projects** |
| Do you read it directly? | Yes — it's markdown, opens in Obsidian, it's the actual deliverable | No — it's a search (`mempalace search`), not a place you browse |
| When the agent uses it | Always, to answer anything **already** documented in the wiki (`wiki/index.md`) | Only when context is missing that never made it into a page yet — e.g. "what did we discuss about X last week?" |

In practice: the wiki is the "finished version" you cultivate; MemPalace is a safety net that keeps you from losing what hasn't been promoted to a page yet.

## Credits

- MemPalace: [MemPalace/mempalace](https://github.com/MemPalace/mempalace) (MIT).
- This script was put together with [Claude Code](https://claude.com/claude-code).

## License

MIT — see [LICENSE](LICENSE).
