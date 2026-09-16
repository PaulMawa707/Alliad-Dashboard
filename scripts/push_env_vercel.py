"""Push this deployment's environment from local ``.env`` to Vercel production.

Everything the dashboard needs at runtime — branding, VSS, Postgres, MiX, Track3 —
is pushed as an encrypted Vercel environment variable. Keys missing from ``.env``
are skipped and listed at the end, so a fresh customer deployment can be set up in
one run and audited afterwards.

  python scripts/push_env_vercel.py            # push everything present in .env
  python scripts/push_env_vercel.py --dry-run   # list what would be pushed
  python scripts/push_env_vercel.py MIX_PASSWORD TRACK3_TOKEN   # only these keys

Requires ``VERCEL_TOKEN`` (https://vercel.com/account/tokens) plus
``VERCEL_PROJECT_ID`` / ``VERCEL_ORG_ID``, or a linked ``.vercel/project.json``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(ROOT)

from env_file import load_env_file  # noqa: E402
from push_vss_token_vercel import upsert_vercel_env  # noqa: E402

# Order is documentation: it mirrors the sections in .env / .env.example.
KEYS = (
    # Branding and fleet scope
    "FLEET_BRAND_NAME",
    "FLEET_BRAND_TAGLINE",
    "FLEET_BRAND_SUBTITLE",
    "FLEET_VSS_CONTAINS",
    "FLEET_LOGO_FILE",
    "FLEET_MARK_FILE",
    # VSS (Howen cameras)
    "VSS_BASE_URL",
    "VSS_USERNAME",
    "VSS_PASSWORD",
    "VSS_BASE_URL_N",
    "VSS_USERNAME_N",
    "VSS_PASSWORD_N",
    "VSS_SSL_VERIFY",
    "VSS_TOKEN_TTL_HOURS",
    # Postgres storage (per-customer tables, shared token row)
    "NEON_DB_URL",
    "NEON_SNAPSHOT_TABLE",
    "NEON_META_TABLE",
    "NEON_OPERATION_LOG_TABLE",
    "NEON_OPERATION_SESSIONS_TABLE",
    "NEON_VSS_TOKEN_TABLE",
    "NEON_VSS_TOKEN_ID",
    # Dashboard sign-in and cron
    "FLASK_SECRET_KEY",
    "DHL_DASH_USERNAME",
    "DHL_DASH_PASSWORD",
    "DHL_REALTIME_AUTO_REFRESH_MINUTES",
    "CRON_SECRET",
    # MiX Telematics
    "MIX_ENABLED",
    "MIX_API_URL",
    "MIX_IDENTITY_URL",
    "MIX_CLIENT_ID",
    "MIX_CLIENT_SECRET",
    "MIX_USERNAME",
    "MIX_PASSWORD",
    "MIX_GROUP_IDS",
    "MIX_ORGANISATION_ID",
    "MIX_SITE_PREFIX",
    "MIX_BEHAVIOUR_HOURS",
    "MIX_BEHAVIOUR_EVENT_TYPE_IDS",
    # Track3 (Wialon Hosting)
    "TRACK3_ENABLED",
    "TRACK3_TOKEN",
    "TRACK3_BASE_URL",
    "TRACK3_GROUP_ID",
    "TRACK3_GROUP_NAME",
    "TRACK3_RESOURCE_ID",
    "TRACK3_ONLINE_MINUTES",
    "TRACK3_BEHAVIOUR_HOURS",
    "TRACK3_REPORT_MAX_UNITS",
)

SECRET_HINTS = ("PASSWORD", "SECRET", "TOKEN", "DB_URL")


def _masked(key: str, value: str) -> str:
    if any(hint in key for hint in SECRET_HINTS):
        return f"<{len(value)} chars hidden>"
    return value


def push(keys: tuple[str, ...] | None = None, *, dry_run: bool = False) -> int:
    # ``.env`` wins over whatever the shell already exported, so a stale variable
    # from an earlier probe cannot leak into the deployment.
    load_env_file(ROOT / ".env", overwrite=True)
    wanted = keys or KEYS

    pushed: list[str] = []
    skipped: list[str] = []
    for key in wanted:
        value = (os.environ.get(key) or "").strip()
        if not value:
            skipped.append(key)
            continue
        print(f"{'would push' if dry_run else 'pushing'} {key} = {_masked(key, value)}")
        if not dry_run:
            upsert_vercel_env(key=key, value=value)
        pushed.append(key)

    print(f"\n{len(pushed)} variable(s) {'listed' if dry_run else 'pushed to Vercel production'}")
    if skipped:
        print(f"not set in .env, skipped: {', '.join(skipped)}")
    if not dry_run and "CRON_SECRET" in skipped:
        print("WARNING: CRON_SECRET is unset — /api/cron/realtime will reject scheduled pings.")
    return 0


def main() -> int:
    """Command-line entry point. Importers should call :func:`push` instead."""
    keys = tuple(a for a in sys.argv[1:] if not a.startswith("-"))
    return push(keys or None, dry_run="--dry-run" in sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
