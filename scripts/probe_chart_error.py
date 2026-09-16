"""Show the chart-failure message a page rendered (see views.safe_figure_html).

  python scripts/probe_chart_error.py https://alliad-fleet.vercel.app "/dashboard/behaviour?chart=map"
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from env_file import load_project_env  # noqa: E402

load_project_env()


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8060").rstrip("/")
    path = sys.argv[2] if len(sys.argv) > 2 else "/dashboard/behaviour?chart=map"
    s = requests.Session()
    s.post(
        f"{base}/login",
        data={
            "username": os.environ.get("DHL_DASH_USERNAME", "admin"),
            "password": os.environ.get("DHL_DASH_PASSWORD", "alliad"),
        },
        timeout=120,
    )
    r = s.get(f"{base}{path}", timeout=300)
    print(f"HTTP {r.status_code}  len={len(r.text)}")
    found = re.findall(r"Chart unavailable[^<\"\\]{0,300}", r.text)
    for hit in found[:3]:
        print("  " + hit)
    if not found:
        print("  (no chart-failure marker in the page)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
