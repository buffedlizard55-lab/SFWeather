#!/usr/bin/env python3
"""Offline self-test for the NCEI archive probe.

The probe's job is to *classify* why an archive stopped: a successor identifier,
a station-specific gap, or an archive-wide publication lag.  Those three
verdicts lead to three different fixes, so the classification logic is the thing
that has to be right - and it can be checked offline against synthetic NCEI
files whose last dates are set by hand.

Three scenarios are run:

* **station-specific gap with a successor id** - the control stations' 2025
  files run to 31 December while the subject stops on 27 August, and
  ``isd-history.csv`` carries a second row for the same airport whose END date is
  current;
* **archive-wide lag** - every station's 2025 file stops within days of the same
  date and there is no successor row;
* **not determinable** - ``isd-history.csv`` cannot be fetched at all, which must
  be reported as "no verdict" rather than as a guess.

Writes nothing; touches no network.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ncei_archive_probe as probe  # noqa: E402

SUBJECT = "72494023234"
GHCN_ID = "USW00023234"
TODAY = dt.date(2026, 9, 18)
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))


class _Res:
    def __init__(self, url, body=None, status=200):
        self.url = url
        self.body = body
        self.ok = body is not None and 200 <= status < 300
        self.status = status if body is not None else 404
        self.error = None if self.ok else f"HTTP {self.status}"
        self.content_type = None
        self.elapsed = 0.0
        self.retrieved_utc = "2026-09-18T00:00:00Z"

    @property
    def size(self):
        return len(self.body) if self.body else 0

    @property
    def sha256(self):
        import hashlib
        return hashlib.sha256(self.body).hexdigest() if self.body else None

    def text(self, encoding="utf-8", errors="replace"):
        return self.body.decode(encoding, errors) if self.body else ""

    def provenance(self, note=None, **extra):
        rec = {"url": self.url, "http_status": self.status, "ok": self.ok,
               "bytes": self.size, "sha256": self.sha256,
               "retrieved_utc": self.retrieved_utc, "note": note}
        rec.update(extra)
        return rec


# --------------------------------------------------------------------------
# synthetic NCEI files
# --------------------------------------------------------------------------

def isd_history(rows):
    header = ('"USAF","WBAN","STATION NAME","CTRY","ST","ICAO","LAT","LON",'
              '"ELEV(M)","BEGIN","END"')
    lines = [header]
    for usaf, wban, name, icao, lat, lon, begin, end in rows:
        lines.append(f'"{usaf}","{wban}","{name}","US","CA","{icao}","{lat}",'
                     f'"{lon}","3.0","{begin}","{end}"')
    return ("\n".join(lines) + "\n").encode()


def gsod_csv(station_id, name, last_date, start_year_day="01-01"):
    """A GSOD station-year file with one row per day up to *last_date*."""
    header = ("STATION,DATE,LATITUDE,LONGITUDE,NAME,TEMP,TEMP_ATTRIBUTES,WDSP,"
              "WDSP_ATTRIBUTES,MXSPD,GUST,PRCP,PRCP_ATTRIBUTES")
    year = last_date[:4]
    lines = [header]
    d = dt.date.fromisoformat(f"{year}-{start_year_day}")
    end = dt.date.fromisoformat(last_date)
    while d <= end:
        lines.append(f'{station_id},{d.isoformat()},37.619,-122.366,{name},'
                     f'58.3,,6.2,,12.4,15.0,0.00,')
        d += dt.timedelta(days=1)
    return ("\n".join(lines) + "\n").encode()


def ghcn_csv(station_id, wind_elements, last_wind_date, first_year=2020):
    header = ['"STATION"', '"DATE"', '"LATITUDE"', '"LONGITUDE"', '"ELEVATION"',
              '"NAME"', '"PRCP"']
    for e in wind_elements:
        header.append(f'"{e}"')
    lines = [",".join(header)]
    d = dt.date(first_year, 1, 1)
    end = dt.date.fromisoformat(last_wind_date)
    while d <= end:
        row = [f'"{station_id}"', f'"{d.isoformat()}"', '"37.619"', '"-122.366"',
               '"3.2"', '"SYNTHETIC STATION"', '"0"']
        for e in wind_elements:
            row.append('"45"' if e.startswith("W") else '"300"')
        lines.append(",".join(row))
        d += dt.timedelta(days=1)
    return ("\n".join(lines) + "\n").encode()


ALERTS_HTML = b"""<html><body><table>
<tr><td><a href="https://www.ncei.noaa.gov/node/9206">Data Access Delays</a></td>
<td>Wed, 08/05/2026 - 15:02</td><td>Fri, 09/25/2026 - 17:00</td>
<td>NCEI is currently moving its data and applications to the cloud. This upgrade
may result in temporary data access delays.</td><td>severity-medium</td></tr>
</table></body></html>"""


def datadir(tmp, stale_last="2025-08-27"):
    tmp = Path(tmp)
    (tmp / "run.json").write_text(json.dumps({
        "generated_utc": "2026-09-18T00:00:00Z",
        "record_coverage": {"archives": [
            {"area": "rain_temp", "last_date": "2026-09-15"},
            {"area": "wind", "last_date": stale_last},
            {"area": "isd_hourly", "last_date": stale_last}],
            "stale_archives": ["wind", "isd_hourly"]},
    }))
    (tmp / "climatology.json").write_text(json.dumps({
        "meta": {"wind_station": {"id": SUBJECT,
                                  "name": "SAN FRANCISCO INTERNATIONAL AIRPORT (KSFO)"}}}))
    (tmp / "isd_hourly_summary.json").write_text(json.dumps({
        "latest_observation_utc": f"{stale_last}T23:56:00Z"}))
    return tmp


CONTROLS = [
    ("724930", "23232", "SAN FRANCISCO DOWNTOWN", "KSFC", 37.7705, -122.4269),
    ("724935", "23239", "OAKLAND MUSEUM", "KOAK", 37.7216, -122.2207),
    ("745060", "23235", "ALAMEDA NAS", "KNGZ", 37.7850, -122.3100),
]


def scenario_a_files():
    """Station-specific gap + a successor identifier + a current GHCN wind record."""
    rows = [("724940", "23234", "SAN FRANCISCO INTERNATIONAL AIRPORT", "KSFO",
             37.619, -122.366, "19450701", "20250827")]
    rows.append(("724940", "99999", "SAN FRANCISCO INTERNATIONAL AIRPORT", "KSFO",
                 37.619, -122.366, "20250828", "20260918"))
    for usaf, wban, name, icao, lat, lon in CONTROLS:
        rows.append((usaf, wban, name, icao, lat, lon, "19450701", "20260918"))
    files = {probe.ISD_HISTORY_URL: isd_history(rows),
             probe.NCEI_ALERTS_URL: ALERTS_HTML,
             f"{probe.GHCND_BASE}/{GHCN_ID}.csv":
                 ghcn_csv(GHCN_ID, ["AWND", "WSF2", "WSF5"], "2026-09-15")}
    files[f"{probe.GSOD_BASE}2025/{SUBJECT}.csv"] = gsod_csv(
        SUBJECT, "SAN FRANCISCO INTERNATIONAL AIRPORT, CA US", "2025-08-27")
    files[f"{probe.GSOD_BASE}2024/{SUBJECT}.csv"] = gsod_csv(
        SUBJECT, "SAN FRANCISCO INTERNATIONAL AIRPORT, CA US", "2024-12-31")
    for usaf, wban, name, _icao, _lat, _lon in CONTROLS:
        sid = f"{usaf}{wban}"
        files[f"{probe.GSOD_BASE}2025/{sid}.csv"] = gsod_csv(
            sid, f"{name}, CA US", "2025-12-31")
        files[f"{probe.GSOD_BASE}2024/{sid}.csv"] = gsod_csv(
            sid, f"{name}, CA US", "2024-12-31")
    return files


def scenario_b_files():
    """Archive-wide lag: every station's 2025 file stops within days; no successor."""
    rows = [("724940", "23234", "SAN FRANCISCO INTERNATIONAL AIRPORT", "KSFO",
             37.619, -122.366, "19450701", "20260918")]
    for usaf, wban, name, icao, lat, lon in CONTROLS:
        rows.append((usaf, wban, name, icao, lat, lon, "19450701", "20260918"))
    files = {probe.ISD_HISTORY_URL: isd_history(rows),
             probe.NCEI_ALERTS_URL: ALERTS_HTML,
             f"{probe.GHCND_BASE}/{GHCN_ID}.csv":
                 ghcn_csv(GHCN_ID, ["PRCP"], "2026-09-15")}   # no wind elements
    files[f"{probe.GSOD_BASE}2025/{SUBJECT}.csv"] = gsod_csv(
        SUBJECT, "SAN FRANCISCO INTERNATIONAL AIRPORT, CA US", "2025-08-27")
    files[f"{probe.GSOD_BASE}2024/{SUBJECT}.csv"] = gsod_csv(
        SUBJECT, "SAN FRANCISCO INTERNATIONAL AIRPORT, CA US", "2024-12-31")
    for usaf, wban, name, _icao, _lat, _lon in CONTROLS:
        sid = f"{usaf}{wban}"
        files[f"{probe.GSOD_BASE}2025/{sid}.csv"] = gsod_csv(
            sid, f"{name}, CA US", "2025-08-30")
        files[f"{probe.GSOD_BASE}2024/{sid}.csv"] = gsod_csv(
            sid, f"{name}, CA US", "2024-12-31")
    return files


def fetcher(files):
    def fake_fetch(url, timeout=120, **kw):
        body = files.get(url)
        return _Res(url, body, 200 if body is not None else 404)
    return fake_fetch


def run():
    CHECKS.clear()

    # ------------------------------------------------ scenario A
    tmp = datadir(tempfile.mkdtemp(prefix="probe_a_"))
    files = scenario_a_files()
    out, manifest = probe.build(datadir=tmp, fetch=fetcher(files), today=TODAY)
    v = out["verdict"]
    check("A: isd-history parsed every synthetic row",
          out["isd_history"]["stations_parsed"] == 5,
          f"n={out['isd_history']['stations_parsed']}")
    check("A: the subject station's own row was found",
          bool(out["subject_rows"]) and out["subject_rows"][0]["icao"] == "KSFO",
          f"subject={out['subject_rows']}")
    check("A: a successor identifier is reported",
          v.get("successor_found") is True and v.get("successor_ids") == ["72494099999"],
          f"successors={v.get('successor_ids')}")
    check("A: the successor row carries its own BEGIN/END dates as evidence",
          bool(out["successor_candidates"])
          and out["successor_candidates"][0]["begin"] == "2025-08-28"
          and out["successor_candidates"][0]["end"] == "2026-09-18",
          f"cand={out['successor_candidates'][:1]}")
    check("A: three control stations were compared",
          v.get("controls_compared") == 3, f"n={v.get('controls_compared')}")
    check("A: subject 2025 file stops 2025-08-27",
          v.get("subject_last_date") == "2025-08-27",
          f"subject_last={v.get('subject_last_date')}")
    check("A: control 2025 files run to 2025-12-31",
          v.get("control_last_date") == "2025-12-31",
          f"control_last={v.get('control_last_date')}")
    check("A: the gap is 126 days (31 Dec minus 27 Aug 2025)",
          v.get("gap_days") == 126, f"gap={v.get('gap_days')}")
    check("A: classified as a station-specific gap",
          v.get("classification") == "station-specific-gap",
          f"class={v.get('classification')}")
    check("A: the recommendation is to stitch the successor, not to do it silently",
          any(a["action"].startswith("stitch") for a in out["recommended_actions"])
          and any("Not done automatically" in (a.get("note") or "")
                  for a in out["recommended_actions"]),
          f"actions={[a['action'] for a in out['recommended_actions']]}")
    check("A: GHCN-Daily wind elements detected with their own last dates",
          out["ghcn_daily_wind_probe"]["wind_elements_present"] == ["AWND", "WSF2", "WSF5"]
          and out["ghcn_daily_wind_probe"]["most_current_wind_date"] == "2026-09-15",
          f"probe={ {k: out['ghcn_daily_wind_probe'][k] for k in ('wind_elements_present','most_current_wind_date')} }")
    check("A: the NCEI alerts page is parsed and the delay alert is active on the run date",
          out["ncei_alerts"]["n_mentions"] >= 1
          and bool(out["ncei_alerts"]["active_on_run_date"]),
          f"alerts={out['ncei_alerts'].get('n_mentions')}")
    check("A: every fetch is recorded with a hash",
          len(manifest) >= 10 and all(e.get("sha256") for e in manifest if e.get("ok")),
          f"manifest={len(manifest)}")
    check("A: the 2024 files show the subject station was complete the year before",
          any(c["year"] == 2024 and c["is_subject"] and c.get("last_date") == "2024-12-31"
              for c in out["gsod_comparisons"]),
          f"cmp={[(c['year'], c['is_subject'], c.get('last_date')) for c in out['gsod_comparisons']]}")

    # ------------------------------------------------ scenario B
    tmp_b = datadir(tempfile.mkdtemp(prefix="probe_b_"))
    out_b, _ = probe.build(datadir=tmp_b, fetch=fetcher(scenario_b_files()), today=TODAY)
    vb = out_b["verdict"]
    check("B: no successor identifier is reported",
          vb.get("successor_found") is False, f"successors={vb.get('successor_ids')}")
    check("B: the gap is 3 days, inside the 15-day slack",
          vb.get("gap_days") == 3 and vb.get("slack_days_allowed") == 15,
          f"gap={vb.get('gap_days')}")
    check("B: classified as an archive-wide lag",
          vb.get("classification") == "archive-wide-lag", f"class={vb.get('classification')}")
    check("B: the recommendation is to keep the stale flag, not to switch stations",
          any(a["action"].startswith("keep the stale-archive flag")
              for a in out_b["recommended_actions"])
          and not any(a["action"].startswith("stitch")
                      for a in out_b["recommended_actions"]),
          f"actions={[a['action'] for a in out_b['recommended_actions']]}")
    check("B: a station file with no wind element says so plainly",
          out_b["ghcn_daily_wind_probe"]["wind_elements_present"] == []
          and out_b["ghcn_daily_wind_probe"]["most_current_wind_date"] is None
          and any("carries none of the daily wind elements" in i["message"]
                  for i in out_b["irregularities"]),
          f"present={out_b['ghcn_daily_wind_probe']['wind_elements_present']}")

    # ------------------------------------------------ scenario C
    tmp_c = datadir(tempfile.mkdtemp(prefix="probe_c_"))
    files_c = {probe.NCEI_ALERTS_URL: ALERTS_HTML}
    out_c, _ = probe.build(datadir=tmp_c, fetch=fetcher(files_c), today=TODAY)
    vc = out_c["verdict"]
    check("C: with no isd-history and no controls the verdict is 'not determinable'",
          vc.get("classification") == "not-determinable", f"class={vc.get('classification')}")
    check("C: the failure to retrieve isd-history is flagged as a warning",
          any(i["area"] == "ncei_archive_probe" and "isd-history" in i["message"]
              for i in out_c["irregularities"]),
          f"irregularities={[i['message'][:40] for i in out_c['irregularities']]}")
    check("C: no irregularity is raised at 'error' severity for a routine 404",
          not any(i["severity"] == "error" for i in out_c["irregularities"]),
          f"severities={[i['severity'] for i in out_c['irregularities']]}")

    # ------------------------------------------------ pure functions
    check("haversine: SFO to downtown San Francisco is about 11 miles",
          9.0 <= probe.haversine_mi(37.619, -122.366, 37.7705, -122.4269) <= 13.0,
          f"d={probe.haversine_mi(37.619, -122.366, 37.7705, -122.4269)}")
    check("date normalisation: YYYYMMDD becomes ISO, ISO is untouched",
          probe._iso_date("20250827") == "2025-08-27"
          and probe._iso_date("2025-08-27") == "2025-08-27"
          and probe._iso_date(None) is None,
          "")
    last, last_wind, nrows = probe.gsod_last_date(
        gsod_csv(SUBJECT, "SAN FRANCISCO INTERNATIONAL AIRPORT, CA US",
                 "2025-08-27").decode())
    check("gsod_last_date counts 239 days from 1 Jan to 27 Aug 2025",
          nrows == 239 and last == "2025-08-27" and last_wind == "2025-08-27",
          f"nrows={nrows} last={last}")

    failed = [c for c in CHECKS if not c[1]]
    for name, ok, detail in CHECKS:
        print(f"  [{'ok ' if ok else 'FAIL'}] {name}" + (f"  :: {detail}" if not ok else ""))
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} NCEI archive-probe self-checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
