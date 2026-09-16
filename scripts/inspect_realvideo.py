"""Fetch RealVideo.html and list embedded URLs (debug proxy embed)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_dotenv() -> None:
    for name in (".env", ".env.vercel.local"):
        path = ROOT / name
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if not key or os.environ.get(key):
                continue
            val = val.strip().strip("\"'")
            if val:
                os.environ[key] = val


def main() -> int:
    _load_dotenv()
    import requests

    base = (os.environ.get("VSS_BASE_URL") or "http://40.76.130.233:9966").rstrip("/")
    user = (os.environ.get("VSS_USERNAME") or "musyoka@controltech-ea.com").strip()
    password = (os.environ.get("VSS_PASSWORD") or "").strip()
    device = (sys.argv[1] if len(sys.argv) > 1 else "H03147").strip()

    if not password:
        print("Set VSS_PASSWORD in .env", file=sys.stderr)
        return 1

    md5 = hashlib.md5(password.encode()).hexdigest()
    r = requests.post(
        f"{base}/vss/user/apiLogin.action",
        json={"username": user, "password": md5},
        timeout=30,
    )
    j = r.json()
    print("login status:", j.get("status"))
    if j.get("status") != 10000:
        print(json.dumps(j, indent=2))
        return 1

    token = j["data"]["token"]
    url = (
        f"{base}/vss/apiPage/RealVideo.html?token={token}"
        f"&deviceId={device}&chs=1&stream=0&wnum=1&panel=0&buffer=2000"
    )
    html = requests.get(url, timeout=30).text
    print("HTML length:", len(html))
    out = ROOT / "scripts" / "_realvideo_sample.html"
    out.write_text(html[:50000], encoding="utf-8")
    print("Wrote sample to", out)

    patterns = [
        ("script src", r'src=["\']([^"\']+)["\']'),
        ("http urls", r"https?://[^\s\"'<>]+"),
        ("ws urls", r"wss?://[^\s\"'<>]+"),
        ("vss paths", r"/vss/[^\s\"'<>]+"),
        ("ip:port", r"\d{1,3}(?:\.\d{1,3}){3}:\d+"),
    ]
    for label, pat in patterns:
        hits = sorted(set(re.findall(pat, html, flags=re.I)))
        print(f"\n--- {label} ({len(hits)}) ---")
        for h in hits[:40]:
            print(" ", h[:150])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
