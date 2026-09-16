"""Validate MiX OAuth credentials from .env / accounts.json."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from scripts.push_vss_token_vercel import _load_dotenv  # noqa: E402

_load_dotenv(ROOT / ".env")

from mix_client import _load_server_creds, _server_key, ensure_bearer_token  # noqa: E402


def main() -> int:
    try:
        creds = _load_server_creds()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: could not load MiX credentials: {exc}", file=sys.stderr)
        return 1

    user = creds.get("IdentityUsername", "")
    api = creds.get("ApiUrl", "")
    print(f"Server: {_server_key()}")
    print(f"User:   {user}")
    print(f"API:    {api}")
    if not user or not creds.get("IdentityPassword"):
        print("FAIL: IdentityUsername or IdentityPassword is empty", file=sys.stderr)
        return 1

    try:
        token = ensure_bearer_token()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: OAuth error: {exc}", file=sys.stderr)
        return 1

    print(f"OK: MiX token acquired ({len(token)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
