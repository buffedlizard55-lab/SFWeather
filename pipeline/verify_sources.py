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
# Keep this list exact.  A broad suffix check such as ``endswith('census.gov')``
# would also accept look-alike domains such as ``evilcensus.gov``; an official
# hostname must be reviewed and added deliberately.
ALLOWED_HOSTS = frozenset({
    "api.weather.gov",
    "www.weather.gov",
    "forecast.weather.gov",
    "api.nws.noaa.gov",
    "www.nws.noaa.gov",
    "www.cpc.ncep.noaa.gov",
    "ftp.cpc.ncep.noaa.gov",
    "www.ncei.noaa.gov",
    "www.ncdc.noaa.gov",
    "nomads.ncep.noaa.gov",
    "www2.census.gov",
    "geocoding.geo.census.gov",
})

# Hosts that are known-good but require a note in the docs.
NOTED = {
    "www2.census.gov": "U.S. Census Bureau - official Gazetteer files",
}


def host_allowed(host: str) -> bool:
    return host.lower().rstrip(".") in ALLOWED_HOSTS


def main() -> int:
    prov = ROOT / "data" / "provenance.json"
    if not prov.exists():
        print("  provenance.json missing - nothing to verify")
        return 1

    data = json.loads(prov.read_text())
    entries = data.get("entries", [])

    hosts = {}
    bad = []
    malformed = []
    for e in entries:
        url = e.get("url")
        if not url:
            malformed.append(("missing URL", e))
            continue
        parsed = urlparse(url)
        h = (parsed.hostname or "").lower().rstrip(".")
        hosts[h] = hosts.get(h, 0) + 1
        if parsed.scheme != "https":
            malformed.append(("URL is not HTTPS", e))
        if not host_allowed(h):
            bad.append((url, h, e.get("http_status")))
        # A successful fetch must carry enough evidence to be rechecked.  A
        # failed optional fetch is reported in the manifest and handled by the
        # quality gate; it is not silently treated as a verified source.
        if e.get("ok"):
            status = e.get("http_status")
            if not (isinstance(status, int) and 200 <= status < 300
                    and isinstance(e.get("bytes"), int) and e.get("bytes") > 0
                    and e.get("sha256")):
                malformed.append(("successful fetch lacks HTTP/size/hash evidence", e))

    print(f"  verified {len(entries)} fetch records across {len(hosts)} hosts")
    for h, n in sorted(hosts.items(), key=lambda kv: -kv[1]):
        flag = "" if host_allowed(h) else "  <-- NOT ON THE VETTED LIST"
        note = f" ({NOTED[h]})" if h in NOTED else ""
        print(f"    {n:4d}  {h}{note}{flag}")

    if bad:
        print("\n  NON-VETTED HOSTS DETECTED:")
        for url, h, st in bad:
            print(f"    - {h}  (status {st})  {url}")
    if malformed:
        print("\n  MALFORMED PROVENANCE RECORDS DETECTED:")
        for reason, entry in malformed:
            print(f"    - {reason}: {entry.get('url')}")
    if bad or malformed:
        return 1

    print("\n  All fetches resolved to vetted official HTTPS hosts with evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
