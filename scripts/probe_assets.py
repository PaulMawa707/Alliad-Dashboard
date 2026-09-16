"""Check that every asset the login/dashboard pages reference actually serves.

  python scripts/probe_assets.py
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

BASE = "http://127.0.0.1:8060"


def main() -> int:
    s = requests.Session()
    login = s.get(f"{BASE}/login", timeout=60).text
    s.post(
        f"{BASE}/login",
        data={
            "username": os.environ.get("DHL_DASH_USERNAME", "admin"),
            "password": os.environ.get("DHL_DASH_PASSWORD", "alliad"),
        },
        timeout=60,
    )
    dash = s.get(f"{BASE}/dashboard", timeout=240).text

    failures = 0
    for page, body in (("/login", login), ("/dashboard", dash)):
        refs = sorted(set(re.findall(r'(?:src|href)="(/assets/[^"]+)"', body)))
        print(f"\n{page}: {len(refs)} local asset(s)")
        for ref in refs:
            r = s.get(f"{BASE}{ref}", timeout=60)
            ok = r.status_code == 200 and len(r.content) > 0
            failures += 0 if ok else 1
            print(f"   {'OK  ' if ok else 'FAIL'} {r.status_code} {len(r.content):>7}B {ref}")

    theme = s.get(f"{BASE}/assets/flask-theme.css", timeout=60).text
    for token in ("#0C112B", "#00CD8C"):
        print(f"\ntheme contains {token}: {token in theme}")
        failures += 0 if token in theme else 1
    stale = [t for t in ("#0F4C81", "#F4A81D") if t in theme]
    if stale:
        print(f"stale palette values still in theme: {stale}")
        failures += len(stale)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
