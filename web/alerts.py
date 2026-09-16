"""High / Critical severity for the five watchlist alerts.

A vehicle is High on the first *current* trigger of power loss, video loss,
offline, SD card missing, or storage error. A second trigger of any of those
five on the same vehicle becomes Critical.

Video-loss events from the last 24 hours do not keep a vehicle Critical after
VSS shows the cameras recording again.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

WATCHLIST_KIND_BY_LABEL = {
    "power down during driving": "Power loss",
    "power loss": "Power loss",
    "power off": "Power loss",
    "video lost": "Video loss",
    "video loss": "Video loss",
    "vehicle offline for a long time": "Offline",
    "offline": "Offline",
    "offline long time": "Offline",
    "disk loss": "SD card missing",
    "sd card missing": "SD card missing",
    "storage error": "Storage error",
    "storage abnormal": "Storage error",
    "disk failure": "Storage error",
}

SEVERITY_HIGH = "High"
SEVERITY_CRITICAL = "Critical"


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).lower()


def watchlist_kind(name: object) -> str:
    return WATCHLIST_KIND_BY_LABEL.get(_norm(name), "")


def _live_video_lost(row: pd.Series, *, age_hours: float) -> bool:
    """True when cameras are actually down now — not a recovered Video Lost alarm.

    VSS ``recordstateFormatter`` is the recording-status column (green icons).
    A channel listed there is recording, even if ``videoloststateFormatter`` still
    carries a stale lost flag from an earlier glitch.
    """
    age = pd.to_numeric(row.get("AgeHours"), errors="coerce")
    ign_on = _norm(row.get("Ignition", "")) == "on"
    online = pd.notna(age) and float(age) <= float(age_hours)
    if not ign_on or not online:
        return False
    from data import parse_channels

    lost = parse_channels(str(row.get("videoloststateFormatter") or ""))
    recording = parse_channels(str(row.get("recordstateFormatter") or ""))
    if recording:
        return any(ch not in recording for ch in lost)
    if lost:
        return True
    return str(row.get("NotRecordingFlag") or "") == "Not Working"


def _live_kinds(row: pd.Series, *, age_hours: float) -> set[str]:
    kinds: set[str] = set()
    status = _norm(row.get("StatusType", ""))
    if status in WATCHLIST_KIND_BY_LABEL:
        kinds.add(WATCHLIST_KIND_BY_LABEL[status])
    age = pd.to_numeric(row.get("AgeHours"), errors="coerce")
    if pd.notna(age) and float(age) > float(age_hours):
        kinds.add("Offline")
    if str(row.get("DiskLossFlag") or "") == "Not Working":
        kinds.add("SD card missing")
    if _live_video_lost(row, age_hours=age_hours):
        kinds.add("Video loss")
    return kinds


def build_device_severity(
    alarms: pd.DataFrame | None,
    realtime: pd.DataFrame | None = None,
    *,
    age_hours: float = 6.0,
) -> dict[str, dict[str, Any]]:
    """Map DeviceID → severity, kinds, and watchlist event count."""
    out: dict[str, dict[str, Any]] = {}

    def _bucket(device_id: str) -> dict[str, Any]:
        key = str(device_id or "").strip()
        if not key:
            return {"severity": "", "kinds": set(), "event_count": 0}
        rec = out.setdefault(key, {"severity": "", "kinds": set(), "event_count": 0})
        return rec

    live_video_loss: set[str] = set()
    if realtime is not None and not realtime.empty and "DeviceID" in realtime.columns:
        for _, row in realtime.iterrows():
            rec = _bucket(row.get("DeviceID", ""))
            live = _live_kinds(row, age_hours=age_hours)
            rec["kinds"].update(live)
            did = str(row.get("DeviceID", "")).strip()
            if did and "Video loss" in live:
                live_video_loss.add(did)

    if alarms is not None and not alarms.empty and "DeviceID" in alarms.columns:
        ids = alarms["DeviceID"].astype(str).str.strip()
        names = alarms["AlarmName"] if "AlarmName" in alarms.columns else pd.Series("", index=alarms.index)
        kinds = names.map(watchlist_kind)
        watch = kinds.astype(bool) & ids.ne("")
        if bool(watch.any()):
            grouped = pd.DataFrame({"DeviceID": ids[watch], "kind": kinds[watch]}).groupby("DeviceID", sort=False)["kind"]
            for did, series in grouped:
                rec = _bucket(did)
                counted = [
                    kind
                    for kind in series.tolist()
                    if kind != "Video loss" or str(did).strip() in live_video_loss
                ]
                rec["event_count"] = int(rec.get("event_count") or 0) + len(counted)
                rec["kinds"].update(counted)

    for rec in out.values():
        kinds = rec["kinds"]
        events = int(rec["event_count"] or 0)
        if events >= 2 or len(kinds) >= 2:
            rec["severity"] = SEVERITY_CRITICAL
        elif events >= 1 or len(kinds) >= 1:
            rec["severity"] = SEVERITY_HIGH
        else:
            rec["severity"] = ""
        rec["kinds"] = sorted(kinds)
    return out


def annotate_alarms(df: pd.DataFrame, severity_by_device: dict[str, dict[str, Any]]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    ids = out["DeviceID"].astype(str) if "DeviceID" in out.columns else pd.Series("", index=out.index)
    names = out["AlarmName"].astype(str) if "AlarmName" in out.columns else pd.Series("", index=out.index)
    alerts = names.map(watchlist_kind)
    out["Alert"] = alerts
    statuses: list[str] = []
    sevs: list[str] = []
    for did, alert in zip(ids, alerts):
        rec = severity_by_device.get(str(did).strip(), {})
        kinds = rec.get("kinds") or []
        if not alert:
            statuses.append("")
            sevs.append("")
            continue
        active = alert in kinds
        statuses.append("Active" if active else "Cleared")
        sevs.append(str(rec.get("severity") or "") if active else "")
    out["Status"] = statuses
    out["Severity"] = sevs
    return out


def annotate_realtime(df: pd.DataFrame, severity_by_device: dict[str, dict[str, Any]]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    out["Severity"] = [
        severity_by_device.get(str(did).strip(), {}).get("severity", "")
        for did in out["DeviceID"].astype(str)
    ]
    out["AlertKinds"] = [
        ", ".join(severity_by_device.get(str(did).strip(), {}).get("kinds") or [])
        for did in out["DeviceID"].astype(str)
    ]
    return out


def severity_counts(severity_by_device: dict[str, dict[str, Any]]) -> tuple[int, int]:
    high = sum(1 for rec in severity_by_device.values() if rec.get("severity") == SEVERITY_HIGH)
    critical = sum(1 for rec in severity_by_device.values() if rec.get("severity") == SEVERITY_CRITICAL)
    return high, critical
