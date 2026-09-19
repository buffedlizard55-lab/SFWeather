#!/usr/bin/env python3
"""Guardrail: confirm every URL used by the pipeline belongs to an official
government / public-agency host that this project has vetted.

If a request to any other host ever appears in a provenance manifest, this script
fails the workflow so it cannot be silently shipped to GitHub Pages.

Every manifest is checked, not only the nightly one.  Auxiliary scripts (the CPC
back-test, the NCEI archive probe, the model-guidance tier, the AFD history) each
write ``data/<area>_provenance.json``; a new script that fetched from an unvetted
host is caught here on its first run, exactly as the nightly pipeline is.  Each
auxiliary manifest must also name its area and say what it fetched, so an
anonymous pile of URLs cannot appear in the record.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import lib_provenance as provlib  # noqa: E402

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
    "geocoding.geo.census.gov": ("U.S. Census Bureau - Geocoder reverse lookup, used to "
                                 "name the geography that contains the published centroid"),
}


def host_allowed(host: str) -> bool:
    return host.lower().rstrip(".") in ALLOWED_HOSTS


def main() -> int:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data"
    paths = provlib.manifest_paths(data_dir)
    if not paths:
        print(f"  no provenance manifest in {data_dir} - nothing to verify")
        return 1

    hosts = {}
    bad = []
    malformed = []
    per_manifest = []
    total = 0

    for path in paths:
        try:
            doc = json.loads(path.read_text())
        except Exception as exc:  # noqa: BLE001
            malformed.append((f"{path.name}: not valid JSON ({exc})", {}))
            continue
        entries = [e for e in (doc.get("entries") or []) if isinstance(e, dict)]
        total += len(entries)
        if path.name != provlib.PRIMARY:
            expected_area = path.name[: -len(provlib.SUFFIX)]
            if doc.get("area") != expected_area:
                malformed.append((f"{path.name}: area is {doc.get('area')!r}, the filename "
                                  f"says {expected_area!r}", {}))
            if not doc.get("note"):
                malformed.append((f"{path.name}: no note saying what the script fetched", {}))
            if not doc.get("generated_utc"):
                malformed.append((f"{path.name}: no generated_utc", {}))
        per_manifest.append((path.name, len(entries),
                             sum(1 for e in entries if e.get("ok"))))

        for e in entries:
            url = e.get("url")
            if not url:
                malformed.append((f"{path.name}: entry with no URL", e))
                continue
            parsed = urlparse(url)
            h = (parsed.hostname or "").lower().rstrip(".")
            hosts[h] = hosts.get(h, 0) + 1
            if parsed.scheme != "https":
                malformed.append((f"{path.name}: URL is not HTTPS", e))
            if not host_allowed(h):
                bad.append((url, h, e.get("http_status"), path.name))
            # A successful fetch must carry enough evidence to be rechecked.  A
            # failed optional fetch is reported in the manifest and handled by the
            # quality gate; it is not silently treated as a verified source.
            if e.get("ok"):
                status = e.get("http_status")
                if not (isinstance(status, int) and 200 <= status < 300
                        and isinstance(e.get("bytes"), int) and e.get("bytes") > 0
                        and e.get("sha256")):
                    malformed.append((f"{path.name}: successful fetch lacks HTTP/size/hash "
                                      f"evidence", e))

    print(f"  verified {total} fetch records in {len(paths)} manifest file(s) "
          f"across {len(hosts)} hosts")
    for name, n, ok in per_manifest:
        print(f"    {name}: {n} record(s), {ok} successful")
    for h, n in sorted(hosts.items(), key=lambda kv: -kv[1]):
        flag = "" if host_allowed(h) else "  <-- NOT ON THE VETTED LIST"
        note = f" ({NOTED[h]})" if h in NOTED else ""
        print(f"    {n:4d}  {h}{note}{flag}")

    if bad:
        print("\n  NON-VETTED HOSTS DETECTED:")
        for url, h, st, where in bad:
            print(f"    - {h}  (status {st}, {where})  {url}")
    if malformed:
        print("\n  MALFORMED PROVENANCE RECORDS DETECTED:")
        for reason, entry in malformed:
            suffix = f": {entry.get('url')}" if entry.get("url") else ""
            print(f"    - {reason}{suffix}")
    if bad or malformed:
        return 1

    print("\n  All fetches resolved to vetted official HTTPS hosts with evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
