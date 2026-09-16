"""Track3 (Wialon Hosting) API client — session, units, and live status.

Track3 is a Wialon Hosting deployment. Auth is a long-lived API token exchanged
for a session id (``eid``) that Wialon expires after a few minutes of inactivity,
so the session is cached in-process only and re-created on demand.

Environment:

  TRACK3_ENABLED=1
  TRACK3_TOKEN=<wialon api token>
  TRACK3_BASE_URL=https://hst-api.wialon.com      (default)
  TRACK3_GROUP_ID=28475360                        (Alliad unit group)
  TRACK3_GROUP_NAME=Alliad
  TRACK3_RESOURCE_ID=28462319                     (resource that owns reports)
  TRACK3_ONLINE_MINUTES=30
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

log = logging.getLogger("track3_client")

DEFAULT_BASE_URL = "https://hst-api.wialon.com"
DEFAULT_GROUP_ID = 28475360
DEFAULT_RESOURCE_ID = 28462319
DEFAULT_GROUP_NAME = "Alliad"

# Wialon error codes we care about.
ERR_INVALID_SESSION = 1
ERR_INVALID_INPUT = 4
ERR_ACCESS_DENIED = 7

_SESSION_TTL_SECONDS = 240.0

_sid: str | None = None
_sid_at: float = 0.0
_sid_lock = threading.Lock()
_last_error: str | None = None

UNIT_COLUMNS = [
    "UnitId",
    "Unit",
    "Registration",
    "LastMessage",
    "LastPosition",
    "AgeMinutes",
    "Status",
    "SpeedKph",
    "Moving",
    "Latitude",
    "Longitude",
]


class Track3Error(RuntimeError):
    """Wialon returned an error or the call could not be completed."""


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name, default)
    return val.strip() if isinstance(val, str) else default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def base_url() -> str:
    return (_env("TRACK3_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def api_url() -> str:
    return f"{base_url()}/wialon/ajax.html"


def access_token() -> str:
    return _env("TRACK3_TOKEN")


def group_id() -> int:
    return _env_int("TRACK3_GROUP_ID", DEFAULT_GROUP_ID)


def group_name() -> str:
    return _env("TRACK3_GROUP_NAME") or DEFAULT_GROUP_NAME


def resource_id() -> int:
    return _env_int("TRACK3_RESOURCE_ID", DEFAULT_RESOURCE_ID)


def online_minutes() -> int:
    return max(1, _env_int("TRACK3_ONLINE_MINUTES", 30))


def track3_enabled() -> bool:
    """Track3 is on when a token is configured (unless explicitly disabled)."""
    if _env_truthy("TRACK3_DISABLED"):
        return False
    if _env("TRACK3_ENABLED") and not _env_truthy("TRACK3_ENABLED", True):
        return False
    return bool(access_token())


def last_track3_error() -> str | None:
    return _last_error


def _set_error(msg: str | None) -> None:
    global _last_error
    _last_error = msg


def _post(payload: dict[str, str], *, timeout: int) -> Any:
    resp = requests.post(api_url(), data=payload, timeout=timeout)
    if resp.status_code != 200:
        raise Track3Error(f"Track3 HTTP {resp.status_code}: {resp.text[:160]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise Track3Error(f"Track3 returned non-JSON: {resp.text[:160]}") from exc


def _login() -> str:
    token = access_token()
    if not token:
        raise Track3Error("TRACK3_TOKEN is not set")
    out = _post(
        {"svc": "token/login", "params": json.dumps({"token": token}, separators=(",", ":"))},
        timeout=45,
    )
    if not isinstance(out, dict) or not out.get("eid"):
        raise Track3Error(f"Track3 token/login failed: {str(out)[:160]}")
    sid = str(out["eid"])
    user = (out.get("user") or {}).get("nm") if isinstance(out.get("user"), dict) else None
    log.info("Track3 session created for %s", user or "unknown user")
    # Report cell timestamps are rendered server-side, so pin the locale.
    try:
        _post(
            {
                "svc": "render/set_locale",
                "params": json.dumps(
                    {
                        "tzOffset": _env_int("TRACK3_TZ_OFFSET", 134228528),
                        "language": "en",
                        "formatDate": "%Y-%m-%d %H:%M:%S",
                    },
                    separators=(",", ":"),
                ),
                "sid": sid,
            },
            timeout=45,
        )
    except Track3Error as exc:  # locale is cosmetic — never fail the pull for it
        log.debug("Track3 set_locale skipped: %s", exc)
    return sid


def ensure_sid(*, force: bool = False) -> str:
    """Return a live Wialon session id, logging in when the cached one is stale."""
    global _sid, _sid_at
    with _sid_lock:
        fresh = _sid and (time.monotonic() - _sid_at) < _SESSION_TTL_SECONDS
        if fresh and not force:
            return str(_sid)
        _sid = _login()
        _sid_at = time.monotonic()
        return str(_sid)


def reset_session() -> None:
    global _sid, _sid_at
    with _sid_lock:
        _sid = None
        _sid_at = 0.0


def call(svc: str, params: dict | list, *, timeout: int = 120, retry: bool = True) -> Any:
    """One Wialon service call. Re-logs in once when the session is rejected."""
    sid = ensure_sid()
    payload = {
        "svc": svc,
        "params": json.dumps(params, separators=(",", ":")),
        "sid": sid,
    }
    out = _post(payload, timeout=timeout)
    err = out.get("error") if isinstance(out, dict) else None
    if err in (ERR_INVALID_SESSION, ERR_ACCESS_DENIED) and retry:
        log.info("Track3 session rejected (error %s) — re-authenticating", err)
        reset_session()
        ensure_sid(force=True)
        return call(svc, params, timeout=timeout, retry=False)
    if err:
        raise Track3Error(f"Track3 {svc} failed (error {err})")
    return out


def batch(calls: list[tuple[str, dict]], *, timeout: int = 180, flags: int = 0) -> list[Any]:
    """Run several calls in one HTTP request (Wialon ``core/batch``)."""
    if not calls:
        return []
    params = {
        "params": [
            {"svc": svc, "params": svc_params} for svc, svc_params in calls
        ],
        "flags": flags,
    }
    out = call("core/batch", params, timeout=timeout)
    return out if isinstance(out, list) else []


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #


def fetch_group_unit_ids() -> list[int]:
    """Member unit ids of the configured Track3 group."""
    out = call("core/search_item", {"id": group_id(), "flags": 8193})
    item = (out or {}).get("item") or {}
    if not item:
        raise Track3Error(f"Track3 group {group_id()} not visible to this token")
    return [int(u) for u in (item.get("u") or []) if str(u).strip()]


def fetch_units(unit_ids: list[int] | None = None, *, chunk: int = 40) -> list[dict[str, Any]]:
    """Full unit records (base + last message + last position) for the group."""
    ids = unit_ids if unit_ids is not None else fetch_group_unit_ids()
    units: list[dict[str, Any]] = []
    for start in range(0, len(ids), max(1, chunk)):
        part = ids[start : start + max(1, chunk)]
        results = batch([("core/search_item", {"id": int(uid), "flags": 0xFFFFFFFF}) for uid in part])
        for res in results:
            if isinstance(res, dict) and isinstance(res.get("item"), dict):
                units.append(res["item"])
    return units


def registration_from_unit_name(name: str) -> str:
    """'Alliad  -  KDV 233Q' -> 'KDV 233Q' (Track3 names are '<customer> - <plate>')."""
    text = " ".join(str(name or "").replace("\t", " ").split())
    if "-" in text:
        tail = text.rsplit("-", 1)[-1].strip()
        if tail:
            return tail
    return text


def build_units_dataframe(units: list[dict[str, Any]] | None = None) -> pd.DataFrame:
    """One row per Track3 unit with online/offline derived from last message age."""
    rows_in = units if units is not None else fetch_units()
    now = datetime.now(timezone.utc)
    limit_minutes = float(online_minutes())
    rows: list[dict[str, Any]] = []
    for unit in rows_in:
        pos = unit.get("pos") if isinstance(unit.get("pos"), dict) else {}
        lmsg = unit.get("lmsg") if isinstance(unit.get("lmsg"), dict) else {}
        last_msg_ts = lmsg.get("t") or pos.get("t")
        pos_ts = pos.get("t")
        age_minutes: float | None = None
        if last_msg_ts:
            age_minutes = max(0.0, (now.timestamp() - float(last_msg_ts)) / 60.0)
        speed = pos.get("s")
        try:
            speed_val = float(speed) if speed is not None else None
        except (TypeError, ValueError):
            speed_val = None
        name = str(unit.get("nm") or "")
        rows.append(
            {
                "UnitId": int(unit.get("id") or 0),
                "Unit": " ".join(name.replace("\t", " ").split()),
                "Registration": registration_from_unit_name(name),
                "LastMessage": _iso_from_unix(last_msg_ts),
                "LastPosition": _iso_from_unix(pos_ts),
                "AgeMinutes": round(age_minutes, 1) if age_minutes is not None else None,
                "Status": (
                    "Unknown"
                    if age_minutes is None
                    else ("Online" if age_minutes <= limit_minutes else "Offline")
                ),
                "SpeedKph": speed_val,
                "Moving": bool(speed_val and speed_val > 3),
                "Latitude": pos.get("y"),
                "Longitude": pos.get("x"),
            }
        )
    df = pd.DataFrame(rows, columns=UNIT_COLUMNS)
    if not df.empty:
        df = df.sort_values(["Status", "Unit"], ascending=[True, True]).reset_index(drop=True)
    return df


def _iso_from_unix(value: Any) -> str | None:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def fetch_units_dataframe() -> pd.DataFrame:
    """Entry point used by the data layer; records the error for the UI banner."""
    if not track3_enabled():
        raise Track3Error("Track3 is not configured (TRACK3_TOKEN missing)")
    try:
        df = build_units_dataframe()
    except Track3Error as exc:
        _set_error(str(exc))
        raise
    except requests.RequestException as exc:
        _set_error(f"Track3 network error: {exc}")
        raise Track3Error(str(exc)) from exc
    _set_error(None)
    log.info("Track3: %s units in group %s", len(df), group_id())
    return df
