"""Deploy the working tree to Vercel through the REST API (no CLI needed).

Uploads the git-tracked files, creates a production deployment, and waits for it
to build. Useful when the Vercel CLI is unavailable or the project is not linked
to GitHub yet.

  python scripts/deploy_vercel.py                 # production deploy
  python scripts/deploy_vercel.py --preview       # preview deploy
  python scripts/deploy_vercel.py --no-wait       # queue it and return

Requires ``VERCEL_TOKEN`` and a linked ``.vercel/project.json`` (see
``scripts/setup_vercel_project.py``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from env_file import load_env_file  # noqa: E402

API = "https://api.vercel.com"


def _project() -> tuple[str, str | None, str]:
    link = ROOT / ".vercel" / "project.json"
    if not link.is_file():
        raise SystemExit("No .vercel/project.json — run scripts/setup_vercel_project.py first")
    data = json.loads(link.read_text(encoding="utf-8"))
    return data["projectId"], data.get("orgId"), data.get("projectName", "alliad-fleet")


def _tracked_files() -> list[Path]:
    """Git-tracked files only, so .gitignore keeps .env and caches out of the build."""
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [ROOT / name for name in out.split("\0") if name]


def _upload(token: str, team: str | None, path: Path) -> dict:
    body = path.read_bytes()
    digest = hashlib.sha1(body).hexdigest()
    rel = path.relative_to(ROOT).as_posix()
    resp = requests.post(
        f"{API}/v2/files",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(body)),
            "x-vercel-digest": digest,
        },
        params={"teamId": team} if team else {},
        data=body,
        timeout=180,
    )
    if resp.status_code >= 400:
        raise SystemExit(f"Upload failed for {rel}: HTTP {resp.status_code} {resp.text[:300]}")
    return {"file": rel, "sha": digest, "size": len(body)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="Deploy to preview instead of production")
    parser.add_argument("--no-wait", action="store_true", help="Do not wait for the build to finish")
    args = parser.parse_args()

    load_env_file(ROOT / ".env", overwrite=True)
    token = (os.environ.get("VERCEL_TOKEN") or "").strip()
    if not token:
        raise SystemExit("VERCEL_TOKEN is not set")

    project_id, team, name = _project()
    files = _tracked_files()
    print(f"uploading {len(files)} tracked file(s) to project {name}")
    manifest = [_upload(token, team, f) for f in files]
    total_kb = sum(item["size"] for item in manifest) / 1024
    print(f"uploaded {total_kb:,.0f} KiB")

    payload = {
        "name": name,
        "project": project_id,
        "files": manifest,
        "target": "preview" if args.preview else "production",
        "projectSettings": {"framework": None},
    }
    resp = requests.post(
        f"{API}/v13/deployments",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        params={"teamId": team} if team else {},
        json=payload,
        timeout=300,
    )
    if resp.status_code >= 400:
        raise SystemExit(f"Deployment failed: HTTP {resp.status_code} {resp.text[:600]}")
    dep = resp.json()
    dep_id, url = dep.get("id"), dep.get("url")
    print(f"deployment {dep_id} queued — https://{url}")
    if args.no_wait:
        return 0

    deadline = time.time() + 900
    state = dep.get("readyState") or dep.get("status") or "QUEUED"
    while time.time() < deadline:
        time.sleep(10)
        poll = requests.get(
            f"{API}/v13/deployments/{dep_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"teamId": team} if team else {},
            timeout=60,
        )
        poll.raise_for_status()
        info = poll.json()
        new_state = info.get("readyState") or info.get("status") or state
        if new_state != state:
            state = new_state
            print(f"  {state}")
        if state in ("READY", "ERROR", "CANCELED"):
            aliases = info.get("alias") or []
            for alias in aliases:
                print(f"  alias https://{alias}")
            return 0 if state == "READY" else 1
    print("timed out waiting for the build")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
