"""Probe MiX organisation groups / subgroups for DHL site resolution."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from scripts.push_vss_token_vercel import _load_dotenv  # noqa: E402

_load_dotenv(ROOT / ".env.vercel.local")
_load_dotenv(ROOT / ".env")

from mix_client import (  # noqa: E402
    _api_headers,
    _group_parent_id,
    _mix_http,
    _normalize_mix_id,
    _site_name_has_prefix,
    _sites_under_org_id,
    api_base_url,
    ensure_bearer_token,
    fetch_organisation_groups,
)

ORG_RAW = os.environ.get("MIX_PARENT_ORG_ID", "1058674603567860796")
ORG_ID = _normalize_mix_id(ORG_RAW)
if ORG_ID is None:
    raise SystemExit(f"MIX_PARENT_ORG_ID is not a valid MiX id: {ORG_RAW!r}")


def _probe_subgroups(token: str, api: str, gid: int) -> list[dict]:
    paths = [
        f"{api}/api/organisationgroups/subgroups/{gid}",
        f"{api}/api/organisationgroups/subgroups/A{gid}",
    ]
    headers = _api_headers(token)
    for url in paths:
        resp = _mix_http("get", url, headers=headers, timeout=45)
        if resp.status_code != 200:
            print(f"  {url.split('/api/', 1)[-1]} -> {resp.status_code}")
            continue
        data = resp.json()
        if isinstance(data, list):
            print(f"  OK list {len(data)} via .../{url.split('/api/', 1)[-1]}")
            return data
        if isinstance(data, dict):
            for key in ("Groups", "groups", "SubGroups", "subGroups", "OrganisationGroups", "organisationGroups"):
                val = data.get(key)
                if isinstance(val, list):
                    print(f"  OK {key}={len(val)} via .../{url.split('/api/', 1)[-1]}")
                    return val
            print(f"  OK dict keys={list(data.keys())[:8]} via .../{url.split('/api/', 1)[-1]}")
            return [data]
    return []


def main() -> int:
    token = ensure_bearer_token()
    api = api_base_url().rstrip("/")
    groups = fetch_organisation_groups(force_refresh=True)
    print(f"organisationgroups count: {len(groups)}")
    if groups:
        sample = groups[0]
        print(f"sample keys: {sorted(sample.keys())}")

    org = next((g for g in groups if int(g.get("GroupId", 0)) == ORG_ID), None)
    print(f"org {ORG_ID} found: {bool(org)} name={org.get('Name') if org else '-'}")

    dhl_named = [g for g in groups if _site_name_has_prefix(str(g.get("Name", "")), "DHL")]
    print(f"DHL-named groups (flat): {len(dhl_named)}")
    for g in dhl_named[:5]:
        gid = g.get("GroupId")
        print(
            f"  {gid} {g.get('Name')} parent={_group_parent_id(g)} type={g.get('Type')}"
        )

    matched = _sites_under_org_id(groups, ORG_ID, "DHL")
    print(f"_sites_under_org_id matched: {len(matched)}")
    for g in matched[:5]:
        print(f"  {g['GroupId']} {g['Name']}")

    print("probing subgroups API...")
    subs = _probe_subgroups(token, api, ORG_ID)
    if subs:
        dhl_subs = [s for s in subs if _site_name_has_prefix(str(s.get("Name", s.get("name", ""))), "DHL")]
        print(f"subgroups total={len(subs)} dhl_named={len(dhl_subs)}")
        for s in dhl_subs[:5]:
            print(f"  {s.get('GroupId', s.get('groupId'))} {s.get('Name', s.get('name'))}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
