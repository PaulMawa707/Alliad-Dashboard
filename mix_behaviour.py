"""MiX driver-behaviour events -> driver-behaviour rows.

MiX names the same fault several ways per organisation ("Harsh braking",
"Harsh Braking - Excessive", "Harsh Braking at speed > 50km/h"), so the library
event catalogue is scanned once and every matching EventTypeId is pulled for the
configured site group(s).

Environment:

  MIX_BEHAVIOUR_HOURS=24                  window length for the pull
  MIX_BEHAVIOUR_EVENT_TYPE_IDS=...        explicit ids, skips catalogue matching
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from behaviour import SOURCE_MIX, canonical_behaviour, normalize_behaviour_frame
from mix_client import (
    _api_headers,
    api_base_url,
    ensure_bearer_token,
    fetch_assets_for_groups_batched,
    group_ids,
    resolve_organisation_id,
)
from mix_events import fetch_group_asset_events, fetch_library_events

log = logging.getLogger("mix_behaviour")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name, default) or "").strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def behaviour_hours() -> int:
    return max(1, min(_env_int("MIX_BEHAVIOUR_HOURS", 24), 24 * 28))


def resolve_behaviour_event_types() -> dict[int, tuple[str, str]]:
    """EventTypeId -> (canonical behaviour, MiX description)."""
    explicit = _env("MIX_BEHAVIOUR_EVENT_TYPE_IDS")
    library = fetch_library_events()
    by_id: dict[int, tuple[str, str]] = {}

    if explicit:
        wanted = {int(p) for p in (x.strip() for x in explicit.split(",")) if p.lstrip("-").isdigit()}
        lib_by_id = {
            int(r["EventTypeId"]): r for r in library if r.get("EventTypeId") is not None
        }
        for eid in wanted:
            row = lib_by_id.get(eid, {})
            desc = str(row.get("Description") or row.get("EventType") or f"Event {eid}")
            behaviour = canonical_behaviour(desc) or canonical_behaviour(str(row.get("EventType") or ""))
            if behaviour:
                by_id[eid] = (behaviour, desc)
        if by_id:
            return by_id

    for row in library:
        eid = row.get("EventTypeId")
        if eid is None:
            continue
        desc = str(row.get("Description") or row.get("EventType") or "")
        behaviour = canonical_behaviour(desc)
        if behaviour:
            by_id[int(eid)] = (behaviour, desc)

    if not by_id:
        log.warning("MiX: no driver-behaviour event types matched the library catalogue")
    else:
        log.info("MiX: %s driver-behaviour event type(s) resolved", len(by_id))
    return by_id


def _asset_lookup() -> dict[str, dict[str, Any]]:
    """AssetId -> asset record, used to label events with name and registration."""
    try:
        token = ensure_bearer_token()
        api = api_base_url()
        sites = group_ids()
        assets = fetch_assets_for_groups_batched(api, token, sites)
    except Exception as exc:  # noqa: BLE001
        log.warning("MiX: asset lookup unavailable (%s) — events will show ids", exc)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for asset in assets or []:
        aid = str(asset.get("AssetId") or asset.get("assetId") or "")
        if aid:
            out[aid] = asset
    return out


def fetch_behaviour_rows(hours: int | None = None) -> list[dict[str, Any]]:
    window = int(hours or behaviour_hours())
    event_types = resolve_behaviour_event_types()
    if not event_types:
        return []

    sites = group_ids()
    if not sites:
        log.warning("MiX: no group ids configured — set MIX_GROUP_IDS")
        return []

    to_dt = datetime.now(timezone.utc)
    fr_dt = to_dt - timedelta(hours=window)
    events: list[dict[str, Any]] = []
    chunk_end = to_dt
    while chunk_end > fr_dt:
        # The MiX events API accepts at most 7 days per request.
        chunk_start = max(fr_dt, chunk_end - timedelta(days=7))
        events.extend(
            fetch_group_asset_events(
                sites,
                from_dt=chunk_start,
                to_dt=chunk_end,
                event_type_ids=list(event_types.keys()),
            )
        )
        chunk_end = chunk_start

    if not events:
        log.info("MiX: no driver-behaviour events in the last %sh", window)
        return []

    assets = _asset_lookup()
    rows: list[dict[str, Any]] = []
    for ev in events:
        etid = ev.get("EventTypeId")
        if etid is None:
            continue
        mapping = event_types.get(int(etid))
        if not mapping:
            continue
        behaviour, description = mapping
        asset = assets.get(str(ev.get("AssetId") or ""), {})
        start_pos = ev.get("StartPosition") if isinstance(ev.get("StartPosition"), dict) else {}
        name = str(asset.get("Description") or asset.get("description") or "")
        registration = str(
            asset.get("RegistrationNumber") or asset.get("registrationNumber") or ""
        )
        rows.append(
            {
                "Source": SOURCE_MIX,
                "Asset": name or registration or f"Asset {ev.get('AssetId')}",
                "Registration": registration,
                "Behaviour": behaviour,
                "RawEvent": description,
                "Count": int(ev.get("TotalOccurances") or 1),
                "Start": ev.get("StartDateTime"),
                "End": ev.get("EndDateTime"),
                "DurationSeconds": ev.get("TotalTimeSeconds"),
                "MaxSpeedKph": start_pos.get("SpeedKilometresPerHour"),
                "AvgSpeedKph": None,
                "Value": ev.get("Value"),
                "MileageKm": None,
                "Driver": str(ev.get("DriverId") or "") or None,
                "Latitude": start_pos.get("Latitude"),
                "Longitude": start_pos.get("Longitude"),
                "Location": start_pos.get("FormattedAddress"),
            }
        )

    log.info("MiX: %s driver-behaviour event row(s) in the last %sh", len(rows), window)
    return rows


def build_behaviour_dataframe(hours: int | None = None) -> pd.DataFrame:
    """MiX half of the driver-behaviour dataset."""
    try:
        resolve_organisation_id()
    except Exception as exc:  # noqa: BLE001
        log.warning("MiX: organisation id unresolved (%s)", exc)
    return normalize_behaviour_frame(fetch_behaviour_rows(hours))
