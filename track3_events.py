"""Track3 (Wialon) eco-driving violations -> driver-behaviour rows.

Wialon exposes driving faults through the ``unit_group_ecodriving`` report table.
The report is executed against the group with an inline template (so no saved
template is required), then read back as JSON: top-level rows are one per
vehicle, and their sub-rows are the individual violations.

Environment:

  TRACK3_BEHAVIOUR_HOURS=24        window length for the pull
  TRACK3_REPORT_MAX_UNITS=0        0 = no cap, otherwise trim parent rows
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

import track3_client as t3
from behaviour import (
    SOURCE_TRACK3,
    canonical_behaviour,
    normalize_behaviour_frame,
)

log = logging.getLogger("track3_events")

# Inline report template: grouped per vehicle so parents carry the vehicle name
# and each sub-row is one violation with its own name, time, and speeds.
ECO_TEMPLATE: dict[str, Any] = {
    "id": 0,
    "n": "Driver Behaviour (dashboard)",
    "ct": "avl_unit_group",
    "p": "{}",
    "tbl": [
        {
            "n": "unit_group_ecodriving",
            "l": "Eco driving",
            "c": (
                '["violation_name","violations_count","violation_rating","time_begin","time_end",'
                '"violation_duration","mileage","location","avg_speed","max_speed",'
                '"violation_value","driver"]'
            ),
            "cl": (
                '["Violation","Count","Rating","Beginning","End","Violation duration","Mileage",'
                '"Location","Avg speed","Max speed","Value","Driver"]'
            ),
            "cp": "[{},{},{},{},{},{},{},{},{},{},{},{}]",
            "s": "",
            "sl": "",
            "filter_order": ["violation_group_name"],
            "p": '{"grouping":"{\\"type\\":\\"unit\\"}","violation_group_name":"*"}',
            "sch": {"f1": 0, "f2": 0, "t1": 0, "t2": 0, "m": 0, "y": 0, "w": 0, "fl": 0},
            "f": 4368,
        }
    ],
}

# Cell index -> meaning for the template above (index 0 is the row number,
# index 1 is the grouping column Wialon injects).
IDX_UNIT = 1
IDX_VIOLATION = 2
IDX_COUNT = 3
IDX_BEGIN = 5
IDX_END = 6
IDX_DURATION = 7
IDX_MILEAGE = 8
IDX_LOCATION = 9
IDX_AVG_SPEED = 10
IDX_MAX_SPEED = 11
IDX_VALUE = 12
IDX_DRIVER = 13

_BLANK = {"", "-----", "----", "-", "n/a"}


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def behaviour_hours() -> int:
    return max(1, _env_int("TRACK3_BEHAVIOUR_HOURS", 24))


def _cell(cells: list[Any], idx: int) -> Any:
    return cells[idx] if 0 <= idx < len(cells) else None


def _text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("t")
    text = str(value if value is not None else "").strip()
    return "" if text.lower() in _BLANK else text


def _number(value: Any) -> float | None:
    text = _text(value)
    if not text:
        return None
    match = re.search(r"-?\d+(?:[.,]\d+)?", text.replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _duration_seconds(value: Any) -> int | None:
    text = _text(value)
    if not text:
        return None
    days = 0
    day_match = re.match(r"(\d+)\s*days?\s+(.*)", text, re.I)
    if day_match:
        days = int(day_match.group(1))
        text = day_match.group(2).strip()
    parts = text.split(":")
    try:
        nums = [int(float(p)) for p in parts]
    except ValueError:
        return None
    while len(nums) < 3:
        nums.insert(0, 0)
    hours, minutes, seconds = nums[-3], nums[-2], nums[-1]
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _timestamp(value: Any) -> str | None:
    """Prefer the unix value Wialon ships alongside the rendered text."""
    if isinstance(value, dict):
        raw = value.get("v")
        try:
            ts = float(raw)
        except (TypeError, ValueError):
            ts = 0.0
        if ts > 0:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        text = _text(value)
        return text or None
    text = _text(value)
    return text or None


def _coords(value: Any) -> tuple[float | None, float | None]:
    if isinstance(value, dict):
        lat, lon = value.get("y"), value.get("x")
        try:
            return (float(lat), float(lon))
        except (TypeError, ValueError):
            return (None, None)
    return (None, None)


def _exec_report(from_dt: datetime, to_dt: datetime) -> int:
    """Run the eco-driving report; returns the row count of the first table."""
    t3.call("report/cleanup_result", {}, timeout=60)
    out = t3.call(
        "report/exec_report",
        {
            "reportResourceId": t3.resource_id(),
            "reportTemplateId": 0,
            "reportObjectId": t3.group_id(),
            "reportObjectSecId": 0,
            "reportTemplate": ECO_TEMPLATE,
            "interval": {
                "from": int(from_dt.timestamp()),
                "to": int(to_dt.timestamp()),
                "flags": 0,
            },
        },
        timeout=280,
    )
    tables = ((out or {}).get("reportResult") or {}).get("tables") or []
    if not tables:
        return 0
    return int(tables[0].get("rows") or 0)


def _parent_rows(total: int) -> list[dict[str, Any]]:
    rows = t3.call(
        "report/get_result_rows",
        {"tableIndex": 0, "indexFrom": 0, "indexTo": max(0, total - 1)},
        timeout=240,
    )
    return rows if isinstance(rows, list) else []


def _attach_subrows(parents: list[dict[str, Any]], *, chunk: int = 20) -> None:
    """Fill each parent's ``r`` list with its violation sub-rows (batched)."""
    missing = [idx for idx, parent in enumerate(parents) if not parent.get("r")]
    for start in range(0, len(missing), max(1, chunk)):
        part = missing[start : start + max(1, chunk)]
        results = t3.batch(
            [("report/get_result_subrows", {"tableIndex": 0, "rowIndex": idx}) for idx in part],
            timeout=240,
        )
        for idx, res in zip(part, results):
            if isinstance(res, list):
                parents[idx]["r"] = res


def fetch_behaviour_rows(hours: int | None = None) -> list[dict[str, Any]]:
    """Violation rows for the Track3 group over the trailing window."""
    window = int(hours or behaviour_hours())
    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(hours=window)

    total = _exec_report(from_dt, to_dt)
    if not total:
        log.info("Track3 eco-driving: no rows in the last %sh", window)
        t3.call("report/cleanup_result", {}, timeout=60)
        return []

    cap = _env_int("TRACK3_REPORT_MAX_UNITS", 0)
    parents = _parent_rows(total)
    if cap > 0:
        parents = parents[:cap]
    _attach_subrows(parents)

    rows: list[dict[str, Any]] = []
    for parent in parents:
        p_cells = parent.get("c") or []
        unit_name = " ".join(_text(_cell(p_cells, IDX_UNIT)).replace("\t", " ").split())
        for child in parent.get("r") or []:
            cells = child.get("c") or []
            raw_name = _text(_cell(cells, IDX_VIOLATION))
            behaviour = canonical_behaviour(raw_name)
            if behaviour is None:
                continue
            lat, lon = _coords(_cell(cells, IDX_LOCATION))
            rows.append(
                {
                    "Source": SOURCE_TRACK3,
                    "Asset": unit_name,
                    "Registration": t3.registration_from_unit_name(unit_name),
                    "Behaviour": behaviour,
                    "RawEvent": raw_name,
                    "Count": int(_number(_cell(cells, IDX_COUNT)) or 1),
                    "Start": _timestamp(_cell(cells, IDX_BEGIN)),
                    "End": _timestamp(_cell(cells, IDX_END)),
                    "DurationSeconds": _duration_seconds(_cell(cells, IDX_DURATION)),
                    "MaxSpeedKph": _number(_cell(cells, IDX_MAX_SPEED)),
                    "AvgSpeedKph": _number(_cell(cells, IDX_AVG_SPEED)),
                    "Value": _text(_cell(cells, IDX_VALUE)) or None,
                    "MileageKm": _number(_cell(cells, IDX_MILEAGE)),
                    "Driver": _text(_cell(cells, IDX_DRIVER)) or None,
                    "Latitude": lat,
                    "Longitude": lon,
                    "Location": _text(_cell(cells, IDX_LOCATION)) or None,
                }
            )

    t3.call("report/cleanup_result", {}, timeout=60)
    log.info("Track3 eco-driving: %s violation rows in the last %sh", len(rows), window)
    return rows


def build_behaviour_dataframe(hours: int | None = None) -> pd.DataFrame:
    """Track3 half of the driver-behaviour dataset."""
    if not t3.track3_enabled():
        raise t3.Track3Error("Track3 is not configured (TRACK3_TOKEN missing)")
    return normalize_behaviour_frame(fetch_behaviour_rows(hours))
