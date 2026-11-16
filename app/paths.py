"""State paths without loading credentials or creating directories at import time."""

import os
import sys
from pathlib import Path


def state_dir() -> Path:
    """Preserve checkout storage; installed wheels use a per-user directory."""
    configured = os.getenv("NOTION2API_HOME")
    if configured:
        return Path(configured).expanduser().absolute()
    checkout = Path(__file__).resolve().parent.parent
    if (checkout / "pyproject.toml").is_file() and (checkout / "ask_notion.py").is_file():
        return checkout
    if sys.platform == "win32":
        base = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        base = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "notion2api"
