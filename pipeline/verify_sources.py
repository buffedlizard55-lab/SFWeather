#!/usr/bin/env python3
"""Guardrail: confirm every URL used by the pipeline belongs to an official
government / public-agency host that this project has vetted.

If a request to any other host ever appears in ``data/provenance.json``, this
script fails the workflow so it cannot be silently shipped to GitHub Pages.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent

# Hosts that this project has explicitly vetted as official, public and free.
ALLOWED_SUFFIXES = (
    ".noaa.gov",
    ".weather.gov",
    ".ncei.noaa.gov",
    ".cpc.ncep.noaa.gov",
    ".nws.noaa.gov",
    "census.gov",
    ".census.gov",
)

# Hosts that are known-good but require a note in the docs.
NOTED = {
    "www2.census.gov": "U.S. Census Bureau - official Gazetteer files",
}


def host_allowed(host: str) -> bool:
    host = host.lower()
    if host in NOTED:
        return True
    return any(host == sfx.lstrip(".") or host.endswith(sfx) for sfx in ALLOWED_SUFFIXES)


def main() -> int:
    prov = ROOT / "data" / "provenance.json"
    if not prov.exists():
        print("  provenance.json missing - nothing to verify")
        return 1

    data = json.loads(prov.read_text())
    entries = data.get("entries", [])

    hosts = {}
    bad = []
    for e in entries:
        url = e.get("url")
        if not url:
            continue
        h = urlparse(url).netloc.lower()
        hosts[h] = hosts.get(h, 0) + 1
        if not host_allowed(h):
            bad.append((url, h, e.get("http_status")))

    print(f"  verified {len(entries)} fetch records across {len(hosts)} hosts")
    for h, n in sorted(hosts.items(), key=lambda kv: -kv[1]):
        flag = "" if host_allowed(h) else "  <-- NOT ON THE VETTED LIST"
        note = f" ({NOTED[h]})" if h in NOTED else ""
        print(f"    {n:4d}  {h}{note}{flag}")

    if bad:
        print("\n  NON-VETTED HOSTS DETECTED:")
        for url, h, st in bad:
            print(f"    - {h}  (status {st})  {url}")
        return 1

    print("\n  All fetches resolved to vetted official hosts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
