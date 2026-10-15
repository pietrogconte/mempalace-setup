# mempalace-setup

[Português](README.md) | **English**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![CI](https://github.com/pietrogconte/mempalace-setup/actions/workflows/ci.yml/badge.svg)](https://github.com/pietrogconte/mempalace-setup/actions/workflows/ci.yml)

**Machine-wide** setup of [MemPalace](https://github.com/MemPalace/mempalace) for Claude Code, in two independent pieces:

1. **`setup_mempalace.py`** — run once: configures the hooks that auto-save your conversation history, plus a minimal recall note in your global `~/.claude/CLAUDE.md`.
2. **`mempalace_sync.py`** — run daily (scheduled task): a safety net for the hooks and capture of what they don't see — other agent tools, study/project folders and claude.ai/ChatGPT exports — always idempotent, with a report.

It doesn't belong to any specific project. Works on Windows with Smart App Control turned on.

## Quickstart

1. **One-time setup:** `python scripts/setup_mempalace.py --dry-run` to see the diff, then without `--dry-run`. Restart Claude Code.
2. **Sync config:** copy [`config.example.toml`](config.example.toml) to `~/.config/mempalace-sync/config.toml` and adjust `mempalace.command`, the paths and the `[[source]]` entries.
3. **Simulate:** `<python> scripts/mempalace_sync.py --dry-run` and read `~/exports/reports/<date>-dry-run.md`.
4. **Run it for real:** `<python> scripts/mempalace_sync.py`.
5. **Schedule it:** `<python> scripts/mempalace_sync.py task install --at 21:00`.

`<python>` = the tool venv's python (see [Windows](#windows-smart-app-control--application-control)), e.g. `C:/Users/<you>/AppData/Roaming/uv/tools/mempalace/Scripts/python.exe`.

### Layout

```
.
├── scripts/
│   ├── setup_mempalace.py   # one-time setup (hooks + recall note)
│   ├── mempalace_sync.py    # daily sync (CLI entry point)
│   └── mpsync/              # config, lock, staging, conversion, normalizer, report, task
├── config.example.toml      # template for ~/.config/mempalace-sync/config.toml
├── tests/                   # unittest with fictitious data and a fake MemPalace
└── .github/workflows/ci.yml # tests on Python 3.9 and 3.12
```

## One-time setup (`setup_mempalace.py`)

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

It doesn't register the `mempalace rules` block (the full multi-agent coordination protocol, MCP with 45 tools) — that's a much bigger scope than "memory across sessions" (`mempalace rules --help`).

## Daily sync (`mempalace_sync.py`)

```
<python> scripts/mempalace_sync.py --dry-run --verbose   # simulate: nothing reaches the palace
<python> scripts/mempalace_sync.py                       # run
<python> scripts/mempalace_sync.py --only ia-notes       # one source only ("inbox" = just the inbox)
<python> scripts/mempalace_sync.py normalize export.zip out/     # just the normalizer
```

Each run, in this order:

1. **`[[source]]` entries** from the config:
   - `mode = "convos"` — agent session folders. The example lists Claude Code (wing `sessions`, the same one the hooks use, so nothing is duplicated), Codex, pi and Gemini CLI; missing folders are skipped. OpenCode and Cursor are left out: MemPalace 3.10 has no parser for their storage.
   - `mode = "projects"` — file folders. With no filters, mined in place. With `include`/`exclude`/`convert`, mined from a **staging** copy outside the original folder (`paths.staging`): HTML and notebooks become markdown (no markup, CSS, JS, outputs or base64), UTF-16 text is decoded, and each file is only rewritten when its content changed — MemPalace uses the mtime to know what it already mined.
   - Always excluded: `.git`, `.venv`, `node_modules`, `__pycache__` and friends, binaries, `.env`, keys and credential-looking files. A folder mined in place that contains such files is refused (give it `include`/`exclude` so it goes through staging).
2. **Export inbox** (`paths.inbox`): each claude.ai or ChatGPT `.zip` is extracted into a temporary folder, normalized into one `.md` per conversation (only new conversations, or ones with a newer `updated_at`, are written), mined, and moved to `paths.processed` — only if the mine succeeded. Transcripts already present in the output folder are adopted without being rewritten.
3. **Report** at `paths.reports/<date>.md` (extra runs on the same day get `<date>-2.md`, ...): palace status before/after per wing, what was mined, a staging summary (10 largest files, duplicates by content) and which `paths.wiki_sources` pages may need curation (new/updated conversations that already have a page) or have no page yet. **The wiki is only read, never written.**

**One writer per palace:** before each mine the script probes the same lock MemPalace uses (`~/.mempalace/locks/mine_palace_*.lock`). With `lock_policy = "wait"` it waits up to `lock_wait_seconds`, then skips; with `"skip"` it skips right away. If another writer grabs the lock during the mine, that also counts as a skip. Skips go to the log and the report, and the next run catches up.

Daily log in `~/.config/mempalace-sync/logs/`; state (conversations already seen) in `~/.config/mempalace-sync/state.json`.

> **`--dry-run` in projects mode:** MemPalace's `mine --dry-run` doesn't check what is already mined in this mode, so the numbers are an upper bound; in a real run, files with an unchanged mtime are skipped. Convos mode checks as usual.

### Scheduled task (Windows)

```
<python> scripts/mempalace_sync.py task install --at 21:00   # register (or update)
<python> scripts/mempalace_sync.py task show                 # details / last run
<python> scripts/mempalace_sync.py task run                  # trigger now
<python> scripts/mempalace_sync.py task remove               # remove
```

The `mempalace-sync` task runs daily, **only while the user is logged on** (no stored password), **starts as soon as possible after a missed start** (PC was off), never runs two instances at once and has a 4 h limit. It calls the `pythonw.exe` next to the python that ran `task install` (no console window) directly with the script path — no `.bat`, `.ps1` or `.vbs`. Before registering, check that this `pythonw.exe` runs on your PC:

```
C:/Users/<you>/AppData/Roaming/uv/tools/mempalace/Scripts/pythonw.exe -c "open('pyw-ok.txt','w').write('ok')"
```

Manual equivalent: `schtasks /Query /TN mempalace-sync /V /FO LIST` and `schtasks /Delete /TN mempalace-sync /F`.

## Where the palace lives (and how to check)

- **Palace (the data):** `~/.config/mempalace/palace` — on Windows, `%USERPROFILE%\.config\mempalace\palace`. The path comes from `palace_path` in `~/.config/mempalace/config.json`.
- **`~/.mempalace`:** only hook state and locks (`hook_state/`, `locks/`). It is not a second palace.

There is **one palace per machine**, shared by all your projects: a search from one project can surface conversations from another. If you need real isolation, point `palace_path` at different locations or use separate profiles/machines.

```
<python> -m mempalace status    # drawer counts per wing/room
```

## Windows: Smart App Control / Application Control

The `.exe` launchers `uv`/`pipx` create (e.g. `~/.local/bin/mempalace.exe`) are unsigned, and Smart App Control (or another Application Control policy) may block them — sometimes intermittently. The tool venv's `python.exe` is signed, so the reliable route is to call the module:

```
C:/Users/<you>/AppData/Roaming/uv/tools/mempalace/Scripts/python.exe -m mempalace status
```

Both scripts follow this rule: the hooks and the config's `mempalace.command` use this form, and the scheduled task calls the same venv's `pythonw.exe`. Blocks show up in Event Viewer under *Microsoft-Windows-CodeIntegrity/Operational*.

## Tests

```
python -m unittest discover -s tests -t . -v
```

CI runs these tests on Python 3.9 and 3.12 (Ubuntu) **without MemPalace installed**: the sync is exercised end to end against a fake CLI (`tests/fake_mempalace.py`), with fictitious exports, folders and wiki. They cover: the claude.ai/ChatGPT normalizer (including adoption, renames and zip-slip), HTML/notebook conversion, staging (filters, sensitive files, UTF-16, preserved mtimes, stale removal, duplicates), config, the cross-process lock, parsing of MemPalace's output, dry-run, the inbox and the scheduled task's XML. They do **not** cover `setup_mempalace.py`, real MemPalace or registering the task on Windows.

## Using it with an LLM Wiki

It pairs well with [llm-wiki-template](https://github.com/pietrogconte/llm-wiki-template), but the two are independent: the wiki is a per-project template; this setup is per machine.

| | LLM Wiki (`wiki/`) | MemPalace |
|---|---|---|
| What it holds | **Curated** synthesis — only what the agent decided was worth turning into a page | **Verbatim** history of everything — every conversation, unfiltered |
| Where it lives | Inside the wiki's repository, versioned in git | Outside any repo, in a single per-machine palace (`~/.config/mempalace/palace`), **shared across all your projects** |
| Do you read it directly? | Yes — it's markdown, opens in Obsidian, it's the actual deliverable | No — it's a search (`mempalace search`), not a place you browse |
| When the agent uses it | Always, to answer anything **already** documented in the wiki (`wiki/index.md`) | Only when context is missing that never made it into a page yet — e.g. "what did we discuss about X last week?" |

In practice: the wiki is the "finished version" you cultivate; MemPalace is a safety net that keeps you from losing what hasn't been promoted to a page yet. The sync report bridges the two: it points at `wiki/sources/` pages that may have gone stale — curation stays with you (or the wiki's agent).

## Credits

- MemPalace: [MemPalace/mempalace](https://github.com/MemPalace/mempalace) (MIT).
- These scripts were put together with [Claude Code](https://claude.com/claude-code).

## License

MIT — see [LICENSE](LICENSE).
