"""Print the most recent pipeline log rows from the dashboard database."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

sys.path.insert(0, str(ROOT / "scripts"))
from push_vss_token_vercel import _load_dotenv  # noqa: E402

_load_dotenv(ROOT / ".env")

import db_url  # noqa: E402


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    import psycopg2

    with psycopg2.connect(db_url.postgres_url()) as conn, conn.cursor() as cur:
        cur.execute(
            "select ts, category, step, status, left(message, 300) "
            "from operation_logs order by id desc limit %s",
            (limit,),
        )
        rows = cur.fetchall()

    for ts, category, step, status, message in reversed(rows):
        print(f"{ts:%Y-%m-%d %H:%M:%S} | {category:10} | {step:22} | {status:7} | {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
