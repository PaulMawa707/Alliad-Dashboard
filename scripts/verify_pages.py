"""Walk every dashboard page against a running server and report what rendered.

  python scripts/verify_pages.py                       # http://127.0.0.1:8060
  python scripts/verify_pages.py https://host --refresh
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

PAGES = [
    ("/dashboard", ["Overview"]),
    ("/dashboard/behaviour", ["Driver Behaviour", "Over speeding", "Harsh cornering"]),
    ("/dashboard/behaviour?chart=trend", ["Driver Behaviour"]),
    ("/dashboard/behaviour?chart=mix", ["Driver Behaviour"]),
    ("/dashboard/behaviour?chart=source", ["Driver Behaviour"]),
    ("/dashboard/behaviour?chart=map", ["Driver Behaviour"]),
    ("/dashboard/behaviour?behaviour=Harsh+Braking", ["Harsh braking"]),
    ("/dashboard/behaviour?source=MiX", ["Driver Behaviour"]),
    ("/dashboard/behaviour?behaviour=Harsh+Cornering&source=MiX", ["Driver Behaviour"]),
    ("/dashboard/track3", ["Track3 Fleet", "Units"]),
    ("/dashboard/track3?status=Offline", ["Track3 Fleet"]),
    ("/dashboard/mix", ["MiX"]),
    ("/dashboard/realtime", ["Real-Time"]),
    ("/dashboard/alarms", ["Alarms"]),
    ("/dashboard/device", ["Device"]),
    ("/dashboard/logs", ["Logs"]),
    ("/api/cache/status", ["freshness"]),
]

ERROR_MARKERS = [
    "Internal Server Error",
    "Traceback (most recent call last)",
    "werkzeug.exceptions",
    "jinja2.exceptions",
]


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("http") else "http://127.0.0.1:8060").rstrip("/")
    do_refresh = "--refresh" in sys.argv

    session = requests.Session()
    user = os.environ.get("DHL_DASH_USERNAME", "admin")
    pwd = os.environ.get("DHL_DASH_PASSWORD", "alliad")
    r = session.post(f"{base}/login", data={"username": user, "password": pwd}, timeout=60, allow_redirects=False)
    if r.status_code not in (301, 302, 303, 307, 308):
        print(f"LOGIN FAILED: HTTP {r.status_code}")
        return 1
    print(f"login OK -> {r.headers.get('Location')}")

    if do_refresh:
        start = session.post(f"{base}/api/refresh", json={"step": "start"}, timeout=120).json()
        print(f"refresh steps: {start.get('steps')}")
        for step in start.get("steps") or []:
            res = session.post(f"{base}/api/refresh", json={"step": step}, timeout=600).json()
            print(f"  {step}: ok={res.get('ok')} err={str(res.get('error'))[:120]} counts={res.get('counts')}")
        fin = session.post(f"{base}/api/refresh", json={"step": "finish"}, timeout=180).json()
        print(f"  finish: ok={fin.get('ok')} msg={str(fin.get('message'))[:200]}")

    failures = 0
    for path, expects in PAGES:
        try:
            resp = session.get(f"{base}{path}", timeout=180)
        except requests.RequestException as exc:
            print(f"FAIL {path}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        body = resp.text
        problems = [m for m in ERROR_MARKERS if m in body]
        missing = [e for e in expects if e.lower() not in body.lower()]
        plots = len(re.findall(r"Plotly\.newPlot", body))
        rows = len(re.findall(r"<tr>", body))
        status = "OK  " if resp.status_code == 200 and not problems and not missing else "FAIL"
        if status == "FAIL":
            failures += 1
        note = ""
        if problems:
            note += f" errors={problems}"
        if missing:
            note += f" missing={missing}"
        print(f"{status} {resp.status_code} {path}  len={len(body):>7}  plots={plots} rows={rows}{note}")

    print(f"\n{'all pages rendered' if not failures else f'{failures} page(s) failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
