# Changelog

All notable changes to this repo are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- CI workflow: `actions/checkout` v4 → v7 and `actions/setup-python` v5 → v7 (`@v7`), both running on Node.js 24. GitHub has deprecated Node.js 20 on Actions runners and was forcing the old versions onto Node.js 24 with a warning. No change to what CI runs (tests on Python 3.9 and 3.12).

## [1.0.0] - 2026-10-15

First "ready to use" release: on top of the one-time setup, a scheduled sync keeps the palace fed.

### Added
- `scripts/mempalace_sync.py` + `scripts/mpsync/`: idempotent capture into MemPalace (Python 3.9+, stdlib only plus `tomli` below 3.11). MemPalace is always driven through its CLI, never imported.
  - **Agent sessions** (`mode = "convos"`): Claude Code (same `sessions` wing as the hooks), Codex, pi and Gemini CLI folders; missing folders are skipped.
  - **Folders** (`mode = "projects"`): mined in place, or — when `include`/`exclude`/`convert` are set — from a staging copy outside the source, rewritten only when content changes so MemPalace's mtime-based idempotency holds. HTML and Jupyter notebooks are converted to markdown (no markup, CSS, JS, outputs or base64); UTF-16 text (with BOM, or a UTF-8 head with an appended UTF-16LE tail) is decoded instead of skipped. Always excluded: VCS/venv/cache folders, binaries, `.env` files, keys and credential-looking files; in-place folders containing such files are refused.
  - **Export inbox**: claude.ai and ChatGPT data-export `.zip` files are extracted (zip-slip safe), normalized to one transcript `.md` per conversation, mined, then moved to the processed folder only if the mine succeeded. State keyed by conversation id + `updated_at`; existing transcripts are adopted without being rewritten.
  - **One writer per palace**: probes MemPalace's own palace lock before each mine; `lock_policy = "wait"` (with timeout) or `"skip"`, and contention detected during a mine is logged as a skip.
  - **Report** per run (`<date>.md`, then `<date>-2.md`... on the same day; `<date>-dry-run.md`): palace status before/after per wing, what was mined, staging summary (10 largest files, duplicates by content), and which `wiki/sources/` pages may need curation. The wiki is only read.
  - `--dry-run`, `--verbose`, `--only`, a log file per day.
  - `task install|remove|show|run`: Windows Task Scheduler entry, daily, only while logged on, runs a missed start as soon as possible, calls the venv's `pythonw.exe` directly (no `.bat`/`.ps1`/`.vbs`, works with Smart App Control).
  - `normalize`: the claude.ai/ChatGPT export normalizer on its own.
- `config.example.toml`; the real config lives in `~/.config/mempalace-sync/config.toml`, outside the repo.
- Tests (`unittest`, fictitious data, a fake MemPalace CLI) and a GitHub Actions workflow running them on Python 3.9 and 3.12.
- `CHANGELOG.md`, `.gitattributes` (LF line endings).

### Changed
- README (pt/en) reorganized around the two scripts: one-time setup and scheduled sync.

### Not included (yet)
- PDF/DOCX/PPTX and zipped projects inside folders (would need `mempalace[extract]`).
- OpenCode and Cursor sessions (no MemPalace parser for their storage as of 3.10).

## Before 1.0.0 (untagged, 2026-10-12)

- `scripts/setup_mempalace.py`: finds a working MemPalace command, configures the Claude Code hooks and the recall note in `~/.claude/CLAUDE.md`.
