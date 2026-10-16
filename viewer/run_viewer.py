"""Start the read-only MemPalace viewer on 127.0.0.1.

Run it with the python of the venv that has Streamlit (never streamlit.exe —
Smart App Control blocks unsigned launchers):

    <streamlit python> viewer/run_viewer.py [--config PATH] [--no-browser]
"""

import argparse
import importlib.util
import os
import subprocess
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mpview.settings import load_settings  # noqa: E402
from mpsync.config import DEFAULT_CONFIG_PATH, ConfigError  # noqa: E402

ADDRESS = "127.0.0.1"


def streamlit_argv(port: int, config: str):
    return [
        sys.executable, "-m", "streamlit", "run", os.path.join(HERE, "app.py"),
        "--server.address", ADDRESS,
        "--server.port", str(port),
        "--server.headless", "true",
        "--browser.serverAddress", ADDRESS,
        "--browser.gatherUsageStats", "false",
        "--global.developmentMode", "false",
        "--", "--config", config,
    ]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args(argv)
    if importlib.util.find_spec("streamlit") is None:
        print("Streamlit is not installed for this python. Install it in its own venv:\n"
              "  uv tool install streamlit\n"
              "and run this script with that venv's python.exe.", file=sys.stderr)
        return 1
    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1
    url = f"http://{ADDRESS}:{settings.port}"
    print(f"MemPalace viewer: {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(3.0, webbrowser.open, (url,)).start()
    try:
        # cwd = viewer/ so viewer/.streamlit/config.toml is picked up as well.
        return subprocess.call(streamlit_argv(settings.port, args.config), cwd=HERE)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
