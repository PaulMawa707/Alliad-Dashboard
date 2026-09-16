"""One-off: pull the customer's public site and report its logo assets and palette.

  python scripts/probe_brand_site.py https://alliad.com/
"""

from __future__ import annotations

import collections
import re
import sys
from urllib.parse import urljoin

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) brand-probe/1.0"}


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://alliad.com/"
    html = requests.get(url, headers=UA, timeout=60).text
    print(f"{len(html)} bytes from {url}\n")

    imgs = {
        urljoin(url, m)
        for m in re.findall(r'(?:src|href|content)="([^"]+\.(?:svg|png|webp|jpg|jpeg))"', html, re.I)
    }
    logos = sorted(i for i in imgs if re.search(r"logo|icon|favicon|brand|mark", i, re.I))
    print("logo-ish assets:")
    for i in logos[:20]:
        print("  ", i)

    css = sorted({urljoin(url, m) for m in re.findall(r'href="([^"]+\.css[^"]*)"', html, re.I)})
    print(f"\nstylesheets: {len(css)}")

    counter: collections.Counter[str] = collections.Counter()
    text = html
    for sheet in css[:12]:
        try:
            text += requests.get(sheet, headers=UA, timeout=60).text
        except requests.RequestException as exc:
            print(f"  skip {sheet}: {exc}")
    for hexcode in re.findall(r"#([0-9a-fA-F]{6})\b", text):
        counter[hexcode.lower()] += 1
    print("\nmost used hex colours:")
    for code, n in counter.most_common(25):
        print(f"   #{code}  x{n}")

    for name in ("theme-color", "og:site_name", "description"):
        m = re.search(rf'name="{name}"[^>]*content="([^"]*)"', html, re.I) or re.search(
            rf'property="{name}"[^>]*content="([^"]*)"', html, re.I
        )
        if m:
            print(f"\n{name}: {m.group(1)[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
