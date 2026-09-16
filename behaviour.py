"""Shared driver-behaviour vocabulary for Track3 and MiX.

Both platforms name the same driving faults differently ("Over Speeding" on
Track3, "Pre-Warning Over Speeding at 75km/hr" on MiX), so every source maps its
raw event name onto the four behaviours the dashboard reports on.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

OVER_SPEEDING = "Over Speeding"
HARSH_ACCELERATION = "Harsh Acceleration"
HARSH_BRAKING = "Harsh Braking"
HARSH_CORNERING = "Harsh Cornering"

# Order drives KPI cards, chart legends, and table sorting.
BEHAVIOURS = [OVER_SPEEDING, HARSH_ACCELERATION, HARSH_BRAKING, HARSH_CORNERING]

BEHAVIOUR_COLORS = {
    OVER_SPEEDING: "#DC2626",
    HARSH_ACCELERATION: "#F59E0B",
    HARSH_BRAKING: "#2563EB",
    HARSH_CORNERING: "#7C3AED",
}

SOURCE_TRACK3 = "Track3"
SOURCE_MIX = "MiX"

BEHAVIOUR_COLUMNS = [
    "Source",
    "Asset",
    "Registration",
    "Behaviour",
    "RawEvent",
    "Count",
    "Start",
    "End",
    "DurationSeconds",
    "MaxSpeedKph",
    "AvgSpeedKph",
    "Value",
    "MileageKm",
    "Driver",
    "Latitude",
    "Longitude",
    "Location",
]

# Names that mention speed but are diagnostics or geofence traffic, not driving faults.
_NOT_A_VIOLATION = re.compile(
    r"sender|calibrat|spike|signal failure|loss detected|fallback|zone|disconnect|"
    r"velocity as speed|can speed",
    re.I,
)

_HARSH_ACCEL = re.compile(r"harsh\s*accel|aggressive\s*accel|\bacceleration\b", re.I)
_HARSH_BRAKE = re.compile(r"harsh\s*brak|heavy\s*brak|\bbraking\b|\bbrake\b", re.I)
_HARSH_CORNER = re.compile(r"harsh\s*corner|cornering|sharp\s*turn|harsh\s*turn", re.I)
_OVER_SPEED = re.compile(r"over\s*speed|overspeed|speeding", re.I)


def canonical_behaviour(raw_name: str | None) -> str | None:
    """Map a platform event name onto one of :data:`BEHAVIOURS` (or ``None``)."""
    text = str(raw_name or "").strip()
    if not text:
        return None
    if _HARSH_CORNER.search(text):
        return HARSH_CORNERING
    if _HARSH_BRAKE.search(text):
        return HARSH_BRAKING
    if _HARSH_ACCEL.search(text):
        return HARSH_ACCELERATION
    if _OVER_SPEED.search(text) and not _NOT_A_VIOLATION.search(text):
        return OVER_SPEEDING
    return None


def empty_behaviour_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=BEHAVIOUR_COLUMNS)


def normalize_behaviour_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Build the shared schema from source rows, dropping unmapped events."""
    df = pd.DataFrame(rows)
    if df.empty:
        return empty_behaviour_frame()
    for col in BEHAVIOUR_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df.loc[:, BEHAVIOUR_COLUMNS]
    df["Count"] = pd.to_numeric(df["Count"], errors="coerce").fillna(1).astype(int)
    df = df[df["Behaviour"].isin(BEHAVIOURS)]
    return df.reset_index(drop=True)


def combine_behaviour_frames(*frames: pd.DataFrame | None) -> pd.DataFrame:
    parts = [f for f in frames if f is not None and not f.empty]
    if not parts:
        return empty_behaviour_frame()
    df = pd.concat(parts, ignore_index=True, sort=False)
    for col in BEHAVIOUR_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df.loc[:, BEHAVIOUR_COLUMNS]
    df["Start"] = pd.to_datetime(df["Start"], errors="coerce", utc=True)
    df = df.sort_values("Start", ascending=False, na_position="last")
    return df.reset_index(drop=True)


def behaviour_counts(df: pd.DataFrame | None) -> dict[str, int]:
    """Total occurrences per behaviour (always includes all four keys)."""
    out = {b: 0 for b in BEHAVIOURS}
    if df is None or df.empty or "Behaviour" not in df.columns:
        return out
    grouped = df.groupby("Behaviour")["Count"].sum()
    for name, total in grouped.items():
        if name in out:
            out[str(name)] = int(total)
    return out


def per_asset_counts(df: pd.DataFrame | None) -> pd.DataFrame:
    """Wide table: one row per asset, one column per behaviour, plus a total."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["Asset", *BEHAVIOURS, "Total"])
    pivot = (
        df.pivot_table(
            index="Asset",
            columns="Behaviour",
            values="Count",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
    )
    for behaviour in BEHAVIOURS:
        if behaviour not in pivot.columns:
            pivot[behaviour] = 0
    pivot = pivot.loc[:, ["Asset", *BEHAVIOURS]]
    pivot["Total"] = pivot[BEHAVIOURS].sum(axis=1)
    pivot = pivot.sort_values("Total", ascending=False).reset_index(drop=True)
    return pivot
