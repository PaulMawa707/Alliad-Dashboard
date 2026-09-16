"""Print the KPI labels/values a page renders, so numbers can be sanity-checked.

  python scripts/probe_kpis.py /dashboard/behaviour
"""

from __future__ import annotations

import html
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
    base = "http://127.0.0.1:8060"
    paths = sys.argv[1:] or ["/dashboard/behaviour", "/dashboard/track3", "/dashboard/alarms?chart=type_pie"]
    s = requests.Session()
    s.post(
        f"{base}/login",
        data={
            "username": os.environ.get("DHL_DASH_USERNAME", "admin"),
            "password": os.environ.get("DHL_DASH_PASSWORD", "alliad"),
        },
        timeout=60,
    )
    for path in paths:
        body = s.get(f"{base}{path}", timeout=240).text
        labels = [html.unescape(x).strip() for x in re.findall(r'class="kpi-title"[^>]*>(.*?)<', body, re.S)]
        values = [html.unescape(x).strip() for x in re.findall(r'class="kpi-value"[^>]*>(.*?)<', body, re.S)]
        print(f"\n== {path}  (plots={len(re.findall(r'Plotly.newPlot', body))})")
        for label, value in zip(labels, values):
            print(f"   {label:34s} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
