#!/usr/bin/env python3
"""mempalace-sync entry point.

Run it with MemPalace's own venv interpreter (or any Python 3.9+; MemPalace is
only called through the command configured in config.toml):

    <python> scripts/mempalace_sync.py --dry-run --verbose
    <python> scripts/mempalace_sync.py
    <python> scripts/mempalace_sync.py normalize <export.zip> <out_dir>
    <python> scripts/mempalace_sync.py task install --at 21:00

See README.md for the config file and the scheduled task.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mpsync.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
