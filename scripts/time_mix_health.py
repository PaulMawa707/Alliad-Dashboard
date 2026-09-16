"""Time a full MiX health fetch so the refresh stage can be sized to the serverless limit."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

sys.path.insert(0, str(ROOT / "scripts"))
from push_vss_token_vercel import _load_dotenv  # noqa: E402

_load_dotenv(ROOT / ".env")


def main() -> int:
    # Optional: scope to explicit group ids instead of scanning the parent org.
    if len(sys.argv) > 1:
        os.environ["MIX_GROUP_IDS"] = sys.argv[1]
        os.environ.pop("MIX_PARENT_ORG_ID", None)
        os.environ.pop("MIX_PARENT_ORG_CONTAINS", None)
        print(f"scoped to MIX_GROUP_IDS={sys.argv[1]}")

    import mix_client

    t = time.time()
    groups = mix_client.resolve_group_targets()
    print(f"groups resolved: {len(groups)} in {time.time() - t:.1f}s", flush=True)
    for g in groups[:10]:
        print(f"  {g['GroupId']} {g.get('Name', '')}")

    import data

    t = time.time()
    df = data.refresh_mix_health()
    print(f"mix_health rows: {len(df)} in {time.time() - t:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
