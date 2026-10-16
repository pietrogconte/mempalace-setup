"""Read-only MemPalace viewer: everything here works on a snapshot, never on the live palace.

The modules in this package are stdlib-only and UI-free so CI can test them
without Streamlit or MemPalace installed. ``viewer/app.py`` is the Streamlit
front end; ``viewer/mpbridge.py`` runs inside MemPalace's own venv for search.
"""

import os
import sys

# mpsync (config + lock probe) lives in scripts/; reuse it instead of copying it.
_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

__version__ = "1.1.0"
