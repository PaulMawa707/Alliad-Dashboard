"""Load ``.env`` into ``os.environ`` for both the Flask app and helper scripts."""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("env_file")

REPO_DIR = Path(__file__).resolve().parent


def load_env_file(path: str | os.PathLike[str], *, overwrite: bool = True) -> int:
    """Read ``KEY=value`` lines; returns how many variables were applied."""
    p = Path(path)
    if not p.is_file():
        log.warning("No .env file at %s — using process environment / defaults only", p)
        return 0
    if p.stat().st_size == 0:
        log.warning(".env exists but is empty (0 bytes) — save your credentials and restart")
        return 0
    loaded = 0
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if not overwrite and os.environ.get(key):
            continue
        os.environ[key] = val
        loaded += 1
    return loaded


def load_project_env() -> None:
    """Load the repo ``.env`` plus the aliases the app expects."""
    loaded = load_env_file(REPO_DIR / ".env")
    if loaded:
        log.info("Loaded %s variables from .env", loaded)
    apply_env_aliases()


def apply_env_aliases() -> None:
    """Accept friendlier names alongside the historical ones.

    ``FLEET_*`` is the customer-facing spelling; the internal code still reads
    the original ``DHL_*`` / ``VSS_*`` names, so copy across whatever is set.
    """
    aliases = {
        "VSS_BASE_URL": ("BASE_URL",),
        "VSS_USERNAME": ("USERNAME",),
        "VSS_PASSWORD": ("PASSWORD",),
        "DHL_DASH_USERNAME": ("FLEET_DASH_USERNAME", "DASH_USERNAME"),
        "DHL_DASH_PASSWORD": ("FLEET_DASH_PASSWORD", "DASH_PASSWORD"),
        "DHL_DASH_PORT": ("FLEET_DASH_PORT",),
        "DHL_AUTO_REFRESH_MINUTES": ("FLEET_AUTO_REFRESH_MINUTES",),
        "DHL_REALTIME_AUTO_REFRESH_MINUTES": ("FLEET_REALTIME_AUTO_REFRESH_MINUTES",),
        "DHL_FLEET_IDS": ("FLEET_VSS_FLEET_IDS",),
        "DHL_ROOT_FLEET_ID": ("FLEET_VSS_ROOT_FLEET_ID",),
    }
    for target, sources in aliases.items():
        if os.environ.get(target):
            continue
        for src in sources:
            val = (os.environ.get(src) or "").strip()
            if val:
                os.environ[target] = val
                break
