"""Print recent error events from the operation log (works for local or live runs).

  python scripts/tail_errors.py            # last 20 error events
  python scripts/tail_errors.py chart      # only steps containing "chart"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from env_file import load_project_env  # noqa: E402

load_project_env()

import operation_log  # noqa: E402


def main() -> int:
    needle = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    events = operation_log.fetch_events(limit=400)
    errors = [
        e
        for e in events
        if str(e.get("status")) == "error" and (not needle or needle in str(e.get("step", "")).lower())
    ]
    if not errors:
        print("no matching error events")
        return 0
    for event in errors[-20:]:
        print(f"\n{event.get('ts')}  {event.get('category')}/{event.get('step')}")
        print(f"  {event.get('message')}")
        detail = event.get("detail") or {}
        tb = detail.get("traceback") if isinstance(detail, dict) else None
        if tb:
            for line in str(tb).strip().splitlines()[-14:]:
                print(f"  | {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
