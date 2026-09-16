"""Print VSS token + PID for Postman (one login attempt).

  python scripts/vss_login_print_session.py

Uses VSS_USERNAME / VSS_PASSWORD from .env or environment.
Default base URL: http://40.76.130.233:9966

Wait ~10 min after 10082 before running again.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_dotenv() -> None:
    for name in (".env", ".env.vercel.local"):
        path = ROOT / name
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if not key or os.environ.get(key):
                continue
            val = val.strip().strip("\"'")
            if val:
                os.environ[key] = val


def main() -> int:
    _load_dotenv()
    import requests

    base = (os.environ.get("VSS_BASE_URL") or "http://40.76.130.233:9966").rstrip("/")
    user = (os.environ.get("VSS_USERNAME") or "musyoka@controltech-ea.com").strip()
    password = (os.environ.get("VSS_PASSWORD") or "").strip()
    if not password:
        print("Set VSS_PASSWORD in .env or environment.", file=sys.stderr)
        return 1

    md5 = hashlib.md5(password.encode()).hexdigest()
    url = f"{base}/vss/user/apiLogin.action"
    r = requests.post(url, json={"username": user, "password": md5}, timeout=30)
    j = r.json()
    status = j.get("status")
    if status != 10000:
        print(json.dumps(j, indent=2), file=sys.stderr)
        if status == 10082:
            print("\nRate-limited — wait ~10 minutes, then run this script ONCE.", file=sys.stderr)
        return 1

    data = j.get("data") or {}
    token = str(data.get("token") or "")
    pid = str(data.get("pid") or "")
    print("VSS_BASE_URL:", base)
    print("VSS_TOKEN:", token)
    print("VSS_PID:", pid)
    print("\nPostman JSON:")
    print(json.dumps({"VSS_BASE_URL": base, "VSS_TOKEN": token, "VSS_PID": pid}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
