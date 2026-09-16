"""Resolve a VSS fleet by name using the Neon token and print Postman-ready values.

Examples (repo root):

  python scripts/vss_probe_fleet.py --contains "BUILDER DEPOT"
  python scripts/vss_probe_fleet.py --contains "DHL" --print-token

Loads ``NEON_DB_URL`` from ``.env``, ``.env.vercel.pull``, or ``.env.vercel.prod``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _load_dotenv(path: Path, *, overwrite_empty: bool = False) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if not val:
            continue
        if overwrite_empty or not os.environ.get(key):
            os.environ[key] = val


def _bootstrap_env() -> None:
    for name in (".env.vercel.pull", ".env.vercel.prod", ".env.vercel.local", ".env"):
        _load_dotenv(ROOT / name, overwrite_empty=True)


def _apply_env_token() -> tuple[str, str, str]:
    """Use VSS_TOKEN/VSS_PID/VSS_BASE_URL from the environment (e.g. Vercel production)."""
    from vss_client import _TokenRecord, _apply_token_record, active_base_url

    token = (os.environ.get("VSS_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("VSS_TOKEN not in environment")
    pid = (os.environ.get("VSS_PID") or "").strip()
    base = (os.environ.get("VSS_BASE_URL") or "").strip() or None
    rec = _TokenRecord(
        token=token,
        pid=pid,
        issued_at=datetime.now(timezone.utc),
        base_url=base,
        profile="env",
    )
    token, pid = _apply_token_record(rec, source="env")
    return token, pid, active_base_url()


def _apply_neon_token() -> tuple[str, str, str]:
    import neon_token_store
    from vss_client import _TokenRecord, _apply_token_record, active_base_url

    if not neon_token_store.configured():
        raise SystemExit(
            "NEON_DB_URL is not set. Run: vercel env pull .env.vercel.pull --environment=production"
        )
    row = neon_token_store.load_vss_token()
    if not row or not str(row.get("token") or "").strip():
        raise SystemExit("No VSS token row in Neon — refresh token first.")

    issued = row.get("issued_at")
    if isinstance(issued, str):
        try:
            issued = datetime.fromisoformat(issued.replace("Z", "+00:00"))
        except ValueError:
            issued = None
    if issued is None:
        issued = datetime.now(timezone.utc)

    rec = _TokenRecord(
        token=str(row["token"]),
        pid=str(row.get("pid") or ""),
        issued_at=issued,
        base_url=str(row.get("base_url") or "") or None,
        profile=str(row.get("profile") or "") or None,
    )
    token, pid = _apply_token_record(rec, source="neon")
    return token, pid, active_base_url()


def _load_vss_session() -> tuple[str, str, str, str]:
    """Return (token, pid, base_url, source). Neon → VSS_TOKEN env → apiLogin."""
    from vss_client import active_base_url, ensure_token, last_vss_token_source

    if (os.environ.get("NEON_DB_URL") or "").strip():
        try:
            token, pid, base = _apply_neon_token()
            return token, pid, base, "neon"
        except SystemExit:
            raise
        except Exception as exc:
            print(f"Neon token load failed ({exc}); trying other sources…")

    if (os.environ.get("VSS_TOKEN") or "").strip():
        try:
            token, pid, base = _apply_env_token()
            return token, pid, base, "env"
        except RuntimeError as exc:
            print(f"VSS_TOKEN env unusable ({exc}); trying apiLogin…")

    token, pid = ensure_token()
    return token, pid, active_base_url(), last_vss_token_source() or "login"


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe VSS fleet by name via Neon token")
    parser.add_argument(
        "--contains",
        default="DHL",
        help="Fleet name substring (default: DHL)",
    )
    parser.add_argument(
        "--print-token",
        action="store_true",
        help="Print full VSS token (for Postman VSS_TOKEN variable)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Write fleet + device summary JSON to this path",
    )
    parser.add_argument(
        "--token",
        help="Use this VSS token directly (skip Neon/login)",
    )
    parser.add_argument(
        "--base-url",
        help="VSS base URL when using --token (default: VSS_BASE_URL env or Neon row)",
    )
    args = parser.parse_args()

    _bootstrap_env()

    from vss_client import (
        _TokenRecord,
        _apply_token_record,
        active_base_url,
        discover_fleet_devices_by_name,
        discover_fleets_by_name,
        _token_is_live,
    )

    if args.token:
        rec = _TokenRecord(
            token=args.token.strip(),
            pid=(os.environ.get("VSS_PID") or "").strip(),
            issued_at=datetime.now(timezone.utc),
            base_url=(args.base_url or os.environ.get("VSS_BASE_URL") or "").strip() or None,
            profile="cli",
        )
        token, pid = _apply_token_record(rec, source="cli")
        base_url = active_base_url()
        token_source = "cli"
    else:
        token, pid, base_url, token_source = _load_vss_session()
    live = _token_is_live(token)
    print(f"VSS base URL : {base_url}")
    print(f"Token source : {token_source}")
    print(f"Token live   : {live}")
    if args.print_token:
        print(f"VSS_TOKEN    : {token}")
        print(f"VSS_PID      : {pid}")
    else:
        print(f"VSS_TOKEN    : {token[:12]}… (use --print-token for full value)")

    fleets = discover_fleets_by_name(contains=args.contains)
    if not fleets:
        print(f"\nNo fleets matched {args.contains!r}")
        return 1

    print(f"\nFleets matching {args.contains!r}:")
    for fid, name in fleets:
        print(f"  {name}")
        print(f"    fleetid: {fid}")

    primary_fleet_id, primary_fleet_name = fleets[0]
    devices = discover_fleet_devices_by_name(contains=args.contains)
    print(f"\nDevices ({len(devices)}) under {primary_fleet_name!r}:")
    device_ids: list[str] = []
    for d in devices:
        did = str(d.get("deviceno") or "")
        dname = str(d.get("devicename") or d.get("deviceName") or "")
        channels = d.get("videoencodernumber", "")
        device_ids.append(did)
        print(f"  {did} | {dname} | channels: {channels}")

    device_csv = ",".join(device_ids)
    summary = {
        "base_url": base_url,
        "fleet_contains": args.contains,
        "fleets": [{"fleetid": fid, "fleetname": name} for fid, name in fleets],
        "primary_fleet_id": primary_fleet_id,
        "primary_fleet_name": primary_fleet_name,
        "device_ids": device_ids,
        "device_id_csv": device_csv,
        "devices": [
            {
                "deviceno": str(d.get("deviceno") or ""),
                "devicename": str(d.get("devicename") or d.get("deviceName") or ""),
                "fleetid": str(d.get("fleetid") or ""),
                "fleetname": str(d.get("fleetName") or d.get("fleetname") or ""),
                "videoencodernumber": d.get("videoencodernumber"),
            }
            for d in devices
        ],
    }

    if args.json_out:
        args.json_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_out}")

    print("\n--- Postman variables ---")
    print(f"FLEET_ID     = {primary_fleet_id}")
    print(f"DEVICE_ID    = {device_ids[0] if device_ids else ''}")
    print(f"DEVICE_IDS   = {device_csv}")
    print("\nPaste VSS_TOKEN from --print-token into Postman, then run requests 2b, 3, 4a.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
