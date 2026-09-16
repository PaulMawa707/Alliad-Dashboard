"""Create (or adopt) the Vercel project for this deployment and load its environment.

Runs entirely against the Vercel REST API, so it works on machines where the
Vercel CLI is blocked. Steps:

  1. find or create the project (optionally linked to a GitHub repository)
  2. write ``.vercel/project.json`` so the other helper scripts can find it
  3. push every variable listed in ``scripts/push_env_vercel.py`` to production

  python scripts/setup_vercel_project.py --name alliad-fleet --repo Owner/ALLIAD-DASHBOARD
  python scripts/setup_vercel_project.py --name alliad-fleet --no-env   # project only

Requires ``VERCEL_TOKEN`` in the environment or ``.env``
(https://vercel.com/account/tokens). Pass ``--team <slug-or-id>`` for a team
account; without it the project is created on the token owner's personal scope.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(ROOT)

from env_file import load_env_file  # noqa: E402

API = "https://api.vercel.com"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _team_id(token: str, team: str | None) -> str | None:
    """Resolve a team slug (or id) to the id the API expects in ``teamId``."""
    if not team:
        return None
    if team.startswith("team_"):
        return team
    resp = requests.get(f"{API}/v2/teams", headers=_headers(token), timeout=30)
    resp.raise_for_status()
    for item in resp.json().get("teams") or []:
        if team in (item.get("slug"), item.get("name"), item.get("id")):
            return str(item["id"])
    raise SystemExit(f"No Vercel team matches {team!r}")


def _find_project(token: str, name: str, team_id: str | None) -> dict | None:
    resp = requests.get(
        f"{API}/v9/projects/{name}",
        headers=_headers(token),
        params={"teamId": team_id} if team_id else {},
        timeout=30,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def _create_project(token: str, name: str, team_id: str | None, repo: str | None) -> dict:
    payload: dict = {"name": name, "framework": None}
    if repo:
        payload["gitRepository"] = {"type": "github", "repo": repo}
    resp = requests.post(
        f"{API}/v10/projects",
        headers=_headers(token),
        params={"teamId": team_id} if team_id else {},
        json=payload,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise SystemExit(f"Create project failed: HTTP {resp.status_code} {resp.text[:400]}")
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="alliad-fleet", help="Vercel project name")
    parser.add_argument("--repo", default=None, help="GitHub repo to link, e.g. Owner/ALLIAD-DASHBOARD")
    parser.add_argument("--team", default=None, help="Vercel team slug or id (omit for personal scope)")
    parser.add_argument("--no-env", action="store_true", help="Skip pushing environment variables")
    args = parser.parse_args()

    load_env_file(ROOT / ".env", overwrite=True)
    token = (os.environ.get("VERCEL_TOKEN") or "").strip()
    if not token:
        raise SystemExit("VERCEL_TOKEN is not set (add it to .env or the environment)")

    team_id = _team_id(token, args.team or os.environ.get("VERCEL_SCOPE"))

    project = _find_project(token, args.name, team_id)
    if project:
        print(f"Project already exists: {project.get('name')} ({project.get('id')})")
    else:
        project = _create_project(token, args.name, team_id, args.repo)
        print(f"Created project {project.get('name')} ({project.get('id')})")
        if args.repo:
            print(f"Linked to GitHub repo {args.repo} — pushes to the default branch will deploy")

    link = ROOT / ".vercel"
    link.mkdir(exist_ok=True)
    (link / "project.json").write_text(
        json.dumps(
            {
                "projectId": project["id"],
                "orgId": team_id or project.get("accountId"),
                "projectName": project.get("name", args.name),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {link / 'project.json'}")

    os.environ["VERCEL_PROJECT_ID"] = project["id"]
    if team_id:
        os.environ["VERCEL_ORG_ID"] = team_id

    if args.no_env:
        print("Skipped env push (--no-env). Run: python scripts/push_env_vercel.py")
        return 0

    import push_env_vercel  # noqa: PLC0415  — imported late so the ids above are set

    return push_env_vercel.main()


if __name__ == "__main__":
    raise SystemExit(main())
