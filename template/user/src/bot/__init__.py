from __future__ import annotations

import sys
from pathlib import Path

_BOT_DIR = str(Path(__file__).resolve().parent)
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)
