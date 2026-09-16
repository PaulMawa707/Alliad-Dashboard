"""Create DHL dashboard tables on Supabase/Postgres and verify connectivity."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "scripts"))
from push_vss_token_vercel import _load_dotenv  # noqa: E402

_load_dotenv(ROOT / ".env")

import db_url  # noqa: E402
import neon_meta_store  # noqa: E402
import neon_snapshot_store  # noqa: E402
import neon_token_store  # noqa: E402
import operation_log  # noqa: E402


def main() -> int:
    url = db_url.postgres_url()
    if not url:
        print(
            "Set NEON_DB_URL (or DATABASE_URL / SUPABASE_DB_URL) in .env.\n"
            "Supabase → Project Settings → Database → Connection string (URI, mode: Session).",
            file=sys.stderr,
        )
        return 1

    masked = url.split("@")[-1] if "@" in url else "(configured)"
    print(f"Connecting to Postgres @ {masked}")

    neon_token_store.ensure_schema()
    print("OK  vss_tokens")
    neon_snapshot_store.ensure_schema()
    print("OK  dashboard_snapshots")
    neon_meta_store.ensure_schema()
    print("OK  dashboard_meta")
    operation_log.ensure_schema()
    print("OK  operation_sessions + operation_logs")

    row = neon_token_store.load_vss_token()
    if row and row.get("token"):
        print(f"VSS token row present (updated {row.get('updated_at')})")
    else:
        print("No VSS token yet — run scripts/push_vss_token_vercel.py after VSS login")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
