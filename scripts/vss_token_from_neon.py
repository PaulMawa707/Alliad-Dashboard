"""Print the active VSS token from Neon (for Postman / API testing).

  python scripts/vss_token_from_neon.py
  python scripts/vss_token_from_neon.py --postman

Loads NEON_DB_URL from .env (same connection string as production/Vercel).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, _, val = line.partition("=")
        key = key.strip()
        if not key or os.environ.get(key):
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if val:
            os.environ[key] = val


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--postman",
        action="store_true",
        help="Print JSON snippet for Postman environment variables",
    )
    args = parser.parse_args()

    for name in (".env", ".env.vercel.local"):
        _load_dotenv(ROOT / name)

    import neon_token_store

    if not neon_token_store.configured():
        print(
            "Set NEON_DB_URL in .env (copy from Neon dashboard / Vercel production settings).",
            file=sys.stderr,
        )
        return 1

    row = neon_token_store.load_vss_token()
    if not row:
        print("No token row in Neon vss_tokens table.", file=sys.stderr)
        return 1

    token = str(row.get("token") or "")
    pid = str(row.get("pid") or "")
    base = str(row.get("base_url") or os.environ.get("VSS_BASE_URL") or "")
    issued = row.get("issued_at")

    if args.postman:
        payload = {
            "VSS_TOKEN": token,
            "VSS_PID": pid,
            "VSS_BASE_URL": base,
        }
        print(json.dumps(payload, indent=2))
        return 0

    print("base_url:", base)
    print("issued_at:", issued)
    print("token:", token)
    print("pid:", pid)
    print("\nPaste token into Postman collection variable VSS_TOKEN.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
