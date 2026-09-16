"""Push the MiX identity overrides from local .env to Vercel production.

Only the credential keys are pushed; MIX_ACCOUNTS_JSON on Vercel keeps supplying
the URLs and any other fields. Use this when the client id/secret or the MiX user
is rotated, instead of re-pushing the whole accounts blob.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

sys.path.insert(0, str(ROOT / "scripts"))
from push_vss_token_vercel import _load_dotenv, upsert_vercel_env  # noqa: E402

CREDENTIAL_KEYS = ("MIX_CLIENT_ID", "MIX_CLIENT_SECRET", "MIX_USERNAME", "MIX_PASSWORD")


def main() -> int:
    _load_dotenv(ROOT / ".env")

    missing = [k for k in CREDENTIAL_KEYS if not os.environ.get(k, "").strip()]
    if missing:
        print(f"ERROR: missing in .env: {', '.join(missing)}", file=sys.stderr)
        return 1

    for key in CREDENTIAL_KEYS:
        upsert_vercel_env(key=key, value=os.environ[key].strip())
        print(f"Pushed {key} to Vercel production")

    print("Done — redeploy for the new MiX credentials to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
