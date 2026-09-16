"""Print recent runtime logs for the linked Vercel deployment.

  python scripts/vercel_logs.py                      # latest production deployment
  python scripts/vercel_logs.py dpl_xxx              # a specific deployment

Requires ``VERCEL_TOKEN`` and ``.vercel/project.json``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from env_file import load_env_file  # noqa: E402

API = "https://api.vercel.com"


def main() -> int:
    load_env_file(ROOT / ".env", overwrite=True)
    token = (os.environ.get("VERCEL_TOKEN") or "").strip()
    if not token:
        raise SystemExit("VERCEL_TOKEN is not set")
    link = json.loads((ROOT / ".vercel" / "project.json").read_text(encoding="utf-8"))
    team = link.get("orgId")
    headers = {"Authorization": f"Bearer {token}"}
    params = {"teamId": team} if team else {}

    dep_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not dep_id:
        resp = requests.get(
            f"{API}/v6/deployments",
            headers=headers,
            params={**params, "projectId": link["projectId"], "limit": 1, "target": "production"},
            timeout=60,
        )
        resp.raise_for_status()
        deployments = resp.json().get("deployments") or []
        if not deployments:
            raise SystemExit("No deployments found")
        dep_id = deployments[0]["uid"]
        print(f"deployment {dep_id} ({deployments[0].get('url')})\n")

    # The log API has moved around; try the known routes until one answers.
    routes = (
        (f"{API}/v1/deployments/{dep_id}/runtime-logs", {}),
        (f"{API}/v3/deployments/{dep_id}/events", {"direction": "backward", "limit": 200}),
        (f"{API}/v2/deployments/{dep_id}/events", {"direction": "backward", "limit": 200}),
    )
    resp = None
    for url, extra in routes:
        attempt = requests.get(url, headers=headers, params={**params, **extra}, timeout=120)
        if attempt.status_code < 400:
            print(f"(log source: {url.rsplit('/', 2)[-2]}/{url.rsplit('/', 1)[-1]})\n")
            resp = attempt
            break
    if resp is None:
        raise SystemExit("No log endpoint answered — check the deployment id and token scope")

    lines = 0
    body = resp.text.lstrip()
    if body.startswith("["):  # /events answers with one JSON array
        for entry in resp.json():
            payload = entry.get("payload") or {}
            message = (entry.get("text") or payload.get("text") or "").rstrip()
            if not message:
                continue
            path = (payload.get("path") or payload.get("requestPath") or "")[:50]
            print(f"[{entry.get('type', ''):>9}] {path:<50} {message[:600]}")
            lines += 1
        if not lines:
            print("no log lines in this window (Vercel keeps runtime logs briefly)")
        return 0

    for raw in resp.text.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith(":"):
            continue
        if raw.startswith("data:"):
            raw = raw[5:].strip()
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            print(raw[:500])
            lines += 1
            continue
        level = entry.get("level") or ""
        path = (entry.get("requestPath") or entry.get("path") or "")[:60]
        message = (entry.get("message") or "").rstrip()
        if not message:
            continue
        print(f"[{level:>7}] {path:<60} {message[:600]}")
        lines += 1
    if not lines:
        print("no runtime log lines returned (logs are retained for a short window)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
