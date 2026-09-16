"""Compare the MiX identity stored in MIX_ACCOUNTS_JSON with the MIX_USERNAME override.

Prints only masked identifiers — enough to tell whether the override replaced a
different MiX user, which changes which groups the dashboard is allowed to read.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

sys.path.insert(0, str(ROOT / "scripts"))
from push_vss_token_vercel import _load_dotenv  # noqa: E402


def mask(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "<empty>"
    name, _, domain = value.partition("@")
    head = name[:2]
    return f"{head}{'*' * max(len(name) - 2, 0)}@{domain}" if domain else f"{head}{'*' * max(len(value) - 2, 0)}"


def main() -> int:
    for candidate in (".env.vercel.prod", ".env.vercel.pull", ".env.vercel.local"):
        path = ROOT / candidate
        if path.is_file():
            _load_dotenv(path)
            print(f"loaded {candidate}")
    _load_dotenv(ROOT / ".env")

    raw = os.environ.get("MIX_ACCOUNTS_JSON", "").strip()
    if not raw:
        print("MIX_ACCOUNTS_JSON: not available locally")
    else:
        blob = json.loads(raw)
        for server, creds in blob.items():
            print(f"accounts[{server}]:")
            print(f"  user   = {mask(str(creds.get('IdentityUsername', '')))}")
            print(f"  client = {creds.get('IdentityClientId', '')}")
            print(f"  api    = {creds.get('ApiUrl', '')}")

    print("overrides now in .env:")
    print(f"  user   = {mask(os.environ.get('MIX_USERNAME', ''))}")
    print(f"  client = {os.environ.get('MIX_CLIENT_ID', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
