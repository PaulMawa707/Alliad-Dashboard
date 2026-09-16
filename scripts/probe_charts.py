"""Count rendered Plotly figures per page (chart cards are easy to break silently).

  python scripts/probe_charts.py [http://127.0.0.1:8060]
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

PATHS = [
    "/dashboard",
    "/dashboard/behaviour",
    "/dashboard/behaviour?chart=trend",
    "/dashboard/behaviour?chart=mix",
    "/dashboard/behaviour?chart=source",
    "/dashboard/behaviour?chart=map",
    "/dashboard/track3",
    "/dashboard/mix",
    "/dashboard/realtime",
    "/dashboard/alarms",
]


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8060").rstrip("/")
    s = requests.Session()
    s.post(
        f"{base}/login",
        data={
            "username": os.environ.get("DHL_DASH_USERNAME", "admin"),
            "password": os.environ.get("DHL_DASH_PASSWORD", "alliad"),
        },
        timeout=60,
    )
    for path in PATHS:
        body = s.get(f"{base}{path}", timeout=240).text
        divs = len(re.findall(r'class="plotly-graph-div', body))
        plots = len(re.findall(r"Plotly\.newPlot", body))
        cards = len(re.findall(r'class="chart-card', body))
        nodata = len(re.findall(r"No data", body, re.I))
        print(f"{path:44s} cards={cards} divs={divs} newPlot={plots} 'No data'={nodata}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
