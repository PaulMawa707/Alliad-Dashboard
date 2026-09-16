"""Push Postgres connection string to Vercel as NEON_DB_URL (Supabase-compatible)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from push_vss_token_vercel import _load_dotenv, upsert_vercel_env  # noqa: E402

_load_dotenv(ROOT / ".env")

import db_url  # noqa: E402


def main() -> int:
    url = db_url.postgres_url()
    if not url:
        print(
            "Set NEON_DB_URL or SUPABASE_DB_URL in .env first.",
            file=sys.stderr,
        )
        return 1
    upsert_vercel_env(key="NEON_DB_URL", value=url)
    print("Pushed NEON_DB_URL to Vercel production (Supabase/Postgres URI).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
