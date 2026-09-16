"""Smoke-test the Alliad data sources: Track3 units, Track3 behaviour, MiX behaviour.

  python scripts/test_sources.py            # everything
  python scripts/test_sources.py track3     # Track3 only
  python scripts/test_sources.py mix        # MiX only
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from env_file import load_project_env  # noqa: E402

load_project_env()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def test_track3() -> None:
    import track3_client as t3
    import track3_events

    print(f"Track3 enabled: {t3.track3_enabled()} group={t3.group_id()} resource={t3.resource_id()}")
    units = t3.fetch_units_dataframe()
    print(f"units: {len(units)}")
    print(units.head(5).to_string(index=False))
    print(units["Status"].value_counts().to_string())

    behaviour = track3_events.build_behaviour_dataframe()
    print(f"\nTrack3 behaviour rows: {len(behaviour)}")
    if not behaviour.empty:
        print(behaviour.groupby("Behaviour")["Count"].sum().to_string())
        print(behaviour.head(5).to_string(index=False))


def test_mix() -> None:
    import mix_behaviour

    types = mix_behaviour.resolve_behaviour_event_types()
    print(f"MiX behaviour event types: {len(types)}")
    for eid, (behaviour, desc) in list(types.items())[:12]:
        print(f"  {eid} {behaviour} <- {desc!r}")
    df = mix_behaviour.build_behaviour_dataframe()
    print(f"MiX behaviour rows: {len(df)}")
    if not df.empty:
        print(df.groupby("Behaviour")["Count"].sum().to_string())
        print(df.head(5).to_string(index=False))


def main() -> int:
    which = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    if which in ("all", "track3"):
        print("=== TRACK3 ===")
        test_track3()
    if which in ("all", "mix"):
        print("\n=== MIX ===")
        test_mix()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
