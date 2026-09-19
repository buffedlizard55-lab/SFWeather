#!/usr/bin/env python3
"""Why did the wind archive for KSFO stop, and can it be made current again?

``data/run.json`` publishes a fact this project cannot explain away: the NCEI
GSOD and ISD hourly files for station ``72494023234`` (San Francisco
International Airport, KSFO) both end on **27 August 2025**, more than a year
before the run date, while the GHCN-Daily rain/temperature record runs to this
month.  Every published statistic is a 1991-2020 statistic and is unaffected, but
nothing may claim to describe *recent* wind from those archives.

Two explanations are possible and they have different fixes:

* **the station identifier changed** - NCEI re-pairs USAF/WBAN ids from time to
  time, and a successor id would simply continue the record; or
* **NCEI stopped advancing the archive** - a processing or publication lag, in
  which case the file ends where it ends and the honest thing is to say so.

This script decides between them with evidence rather than opinion, by running
three tests against official NCEI files:

1.  ``isd-history.csv`` - does any row for the same airport (same ICAO, or the
    same name within a few kilometres of the same coordinates) have an ``END``
    date that is current?  That is a successor id.
2.  *Control stations* - fetch the same year's GSOD file for up to four other
    official stations near San Francisco.  If theirs run to 31 December and
    KSFO's stops in August, the gap is station-specific; if they all stop within
    a fortnight of the same date, the whole archive stopped advancing.
3.  *An independent current wind record* - GHCN-Daily for the same airport
    (``USW00023234``) carries daily wind elements at many US stations and is
    updated daily.  Whether it does here, and how current it is, is measured
    from the file's own header and rows rather than assumed.

It also records any active NCEI service alert about data-access delays, so an
official statement about the archive is published next to this project's own
finding.

Nothing here changes the climatology.  The 1991-2020 statistics stay exactly as
published; this script only explains how current the archives are and names a
successor if one exists.

Run:  ``python3 pipeline/ncei_archive_probe.py [--datadir data] [--outdir data]``
      ``python3 pipeline/ncei_archive_probe.py --selftest``   (offline)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib_fetch as fetchlib      # noqa: E402
import lib_provenance as provlib  # noqa: E402
import climo                      # noqa: E402

#: NCEI's Integrated Surface Database station history.  The authority on which
#: USAF-WBAN pair belongs to which airport, and over what dates.
ISD_HISTORY_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"

GSOD_BASE = "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/"
GHCND_BASE = ("https://www.ncei.noaa.gov/data/global-historical-climatology-"
              "network-daily/access")

#: NCEI's own service-alert page.  A dated official notice about data-access
#: delays is evidence; this project's opinion about a lag is not.
NCEI_ALERTS_URL = "https://www.ncei.noaa.gov/alerts"

#: Daily wind elements GHCN-Daily uses.  Whether a station file carries them is
#: read from that file's header, never assumed.
GHCN_WIND_ELEMENTS = ("AWND", "WDF2", "WDF5", "WSF2", "WSF5", "WDMV", "TSUN")

#: How far from the published wind station a control station may be and still
#: count as "the same archive region" (degrees, roughly 100 km).
CONTROL_RADIUS_DEG = 1.0

#: Control stations whose GSOD file for the same year is compared with the
#: subject station's.  More than enough to tell a station-specific gap from an
#: archive-wide one; each is fetched only for the years being probed.
MAX_CONTROLS = 4

#: Days of slack when deciding whether two stations "stopped at the same time".
SAME_STOP_SLACK_DAYS = 15


def log(msg=""):
    print(msg, flush=True)


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def _iso_date(value):
    """Normalise NCEI's ``YYYYMMDD`` (or already-ISO) dates to ``YYYY-MM-DD``.

    Published so the successor comparison is a date comparison and not a string
    comparison that happens to work for one layout.
    """
    if not value:
        return None
    s = str(value).strip()
    if re.match(r"^\d{8}$", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    return s


def parse_isd_history(text):
    """Parse ``isd-history.csv`` into a list of station dicts.

    The column layout is read from the header rather than assumed, because NCEI
    has shipped both a combined ``LAT(LON)`` column and separate ``LAT``/``LON``
    columns.  Returns ``(rows, header_found)``; ``header_found`` is published so
    a reader can see which layout was actually served.
    """
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return [], []
    h = [c.strip().strip('"').upper().lstrip("\ufeff") for c in header]
    idx = {name: i for i, name in enumerate(h)}

    def get(row, *names):
        for name in names:
            i = idx.get(name)
            if i is not None and i < len(row):
                v = (row[i] or "").strip().strip('"')
                if v:
                    return v
        return None

    def num(row, *names):
        v = get(row, *names)
        if v is None:
            return None
        try:
            return float(v)
        except ValueError:
            return None

    out = []
    for row in reader:
        if not row or len(row) < 4:
            continue
        usaf, wban = get(row, "USAF"), get(row, "WBAN")
        if not usaf or not wban:
            continue
        lat = num(row, "LAT", "LAT(LON)", "LATITUDE")
        lon = num(row, "LON", "LONG", "LON(LAT)", "LONGITUDE")
        if lat is None or lon is None:
            combined = get(row, "LAT(LON)")
            if combined:
                m = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", combined)
                if m:
                    lat, lon = float(m.group(1)), float(m.group(2))
        out.append({
            "usaf": usaf, "wban": wban, "gsod_id": f"{usaf}{wban}",
            "name": get(row, "STATION NAME", "STATION", "NAME"),
            "country": get(row, "CTRY", "COUNTRY"),
            "state": get(row, "ST", "STATE"),
            "icao": get(row, "ICAO"),
            "lat": lat, "lon": lon,
            "elev_m": num(row, "ELEV(M)", "ELEV", "ELEVATION"),
            "begin": _iso_date(get(row, "BEGIN", "BEGIN DATE")),
            "end": _iso_date(get(row, "END", "END DATE")),
        })
    return out, h


def haversine_mi(lat1, lon1, lat2, lon2):
    """Great-circle miles between two points (used to rank control stations)."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


def ghcn_header_elements(text):
    """The element columns a GHCN-Daily station file actually carries."""
    first = text.split("\n", 1)[0]
    header = next(csv.reader([first]), [])
    return [c.strip().strip('"').upper().lstrip("\ufeff") for c in header]


def ghcn_element_last_dates(text, elements):
    """For each element, the last date carrying a usable value."""
    header = ghcn_header_elements(text)
    idx = {name: i for i, name in enumerate(header)}
    i_date = idx.get("DATE")
    last = {e: None for e in elements}
    counts = {e: 0 for e in elements}
    if i_date is None:
        return last, counts
    for row in csv.reader(io.StringIO(text)):
        if not row or i_date >= len(row):
            continue
        date = (row[i_date] or "").strip().strip('"')
        if len(date) != 10:
            continue
        for e in elements:
            i = idx.get(e)
            if i is None or i >= len(row):
                continue
            raw = (row[i] or "").strip().strip('"').strip()
            if raw in ("", "nan"):
                continue
            try:
                v = float(raw)
            except ValueError:
                continue
            if v == climo.GHCN_MISSING:
                continue
            counts[e] += 1
            if last[e] is None or date > last[e]:
                last[e] = date
    return last, counts


TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(html):
    """Crude HTML -> text, enough to read a service-alert table."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    text = TAG_RE.sub(" ", text)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&#039;", "'"), ("&quot;", '"')):
        text = text.replace(a, b)
    return re.sub(r"[ \t]+", " ", text)


def parse_ncei_alerts(text, today):
    """Find active NCEI service alerts that mention data access.

    Only the alert's own words, title and dates are returned; nothing is
    inferred.  An alert whose end date has passed is reported as expired rather
    than dropped, so the reader can see it was considered.
    """
    plain = html_to_text(text)
    found = []
    for m in re.finditer(r"(?i)(data access delays?|cloud migration|processing delay)",
                         plain):
        start = max(0, m.start() - 200)
        snippet = re.sub(r"\s+", " ", plain[start:m.end() + 400]).strip()
        dates = re.findall(r"(\d{2})/(\d{2})/(\d{4})", snippet)
        iso = [f"{y}-{mm}-{dd}" for (mm, dd, y) in dates]
        found.append({"matched": m.group(0), "dates_found": iso[:4],
                      "snippet": snippet[:500]})
    active = []
    for f in found:
        ds = f["dates_found"]
        if len(ds) >= 2:
            try:
                end = dt.date.fromisoformat(ds[-1])
            except ValueError:
                end = None
            if end and end >= today:
                f["active_on_run_date"] = True
                active.append(f)
            else:
                f["active_on_run_date"] = False
                active.append(f)
    return {"url": NCEI_ALERTS_URL, "mentions": found[:5],
            "n_mentions": len(found),
            "active_on_run_date": [a for a in active if a.get("active_on_run_date")]}


# --------------------------------------------------------------------------
# the probe
# --------------------------------------------------------------------------

def gsod_last_date(text):
    """Last date with any row, and last date with a usable wind value."""
    rows = climo.parse_gsod(text)
    if not rows:
        return None, None, 0
    dates = sorted(r["date"] for r in rows)
    wind_dates = sorted(r["date"] for r in rows
                        if r.get("max_wind_kt") is not None or r.get("gust_kt") is not None)
    return dates[-1], (wind_dates[-1] if wind_dates else None), len(rows)


def build(datadir=Path("data"), fetch=fetchlib.get, today=None, max_controls=None):
    """Run the whole probe.  Pure apart from the injected *fetch*."""
    datadir = Path(datadir)
    today = today or dt.datetime.now(dt.timezone.utc).date()
    max_controls = MAX_CONTROLS if max_controls is None else max_controls
    manifest, irregularities = [], []

    def note(severity, area, message, evidence=None):
        irregularities.append({"severity": severity, "area": area,
                               "message": message, "evidence": evidence or {}})

    def load(name):
        p = datadir / name
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            return {}

    run = load("run.json")
    climo_data = load("climatology.json")
    isd_summary = load("isd_hourly_summary.json")
    wind_station = ((climo_data.get("meta") or {}).get("wind_station") or {})
    station_id = wind_station.get("id") or "72494023234"
    station_name = wind_station.get("name")
    coverage = run.get("record_coverage") or {}
    stale_last = None
    for arc in coverage.get("archives") or []:
        if arc.get("area") == "wind":
            stale_last = arc.get("last_date")

    out = {
        "generated_utc": fetchlib.iso_utc(),
        "question": ("Why do NCEI's GSOD and ISD files for this station stop where "
                     "they do, and is there a successor identifier that makes the "
                     "wind archive current again?"),
        "station_id": station_id,
        "station_name": station_name,
        "last_date_published_by_the_site": stale_last,
        "isd_hourly_last_observation_utc": isd_summary.get("latest_observation_utc"),
        "tests": [],
        "verdict": None,
        "irregularities": irregularities,
    }

    # -------------------------------------------------- 1. station history
    res = fetch(ISD_HISTORY_URL, timeout=300)
    manifest.append(res.provenance(note="NCEI ISD station history (isd-history.csv)"))
    stations, header = [], []
    if res.ok and res.body:
        text = fetchlib.decode_text(res.body)[0]
        stations, header = parse_isd_history(text)
    else:
        note("warning", "ncei_archive_probe",
             "isd-history.csv could not be retrieved, so the successor-identifier "
             "test could not be run on this pass.",
             {"url": ISD_HISTORY_URL, "status": res.status})
    out["isd_history"] = {"url": ISD_HISTORY_URL, "http_status": res.status,
                          "sha256": res.sha256, "bytes": res.size,
                          "retrieved_utc": res.retrieved_utc,
                          "header_found": header,
                          "stations_parsed": len(stations)}

    subject = [s for s in stations if s["gsod_id"] == station_id]
    out["subject_rows"] = subject
    same_airport = []
    if subject:
        s0 = subject[0]
        for s in stations:
            if s["gsod_id"] == station_id:
                continue
            same_icao = bool(s0.get("icao")) and s.get("icao") == s0.get("icao")
            near = haversine_mi(s0.get("lat"), s0.get("lon"), s.get("lat"), s.get("lon"))
            same_name = bool(s0.get("name")) and s.get("name") == s0.get("name")
            if same_icao or same_name or (near is not None and near <= 2.0):
                same_airport.append({**s, "distance_mi_from_subject": near,
                                     "same_icao": same_icao, "same_name": same_name})
        same_airport.sort(key=lambda r: (r.get("end") or ""), reverse=True)
    out["stale_last_date_iso"] = _iso_date(stale_last)
    out["same_airport_rows"] = same_airport[:20]

    stale_iso = _iso_date(stale_last) or "0000-00-00"
    successors = [r for r in same_airport if (r.get("end") or "") > stale_iso]
    out["successor_candidates"] = successors[:10]

    # -------------------------------------------------- 2. control stations
    controls = []
    if subject and stations:
        s0 = subject[0]
        # A row for the same airport is a successor candidate, not a control:
        # comparing the subject with itself under a new id would prove nothing.
        same_ids = {r["gsod_id"] for r in same_airport}
        for s in stations:
            if s["gsod_id"] == station_id or s["gsod_id"] in same_ids:
                continue
            if s.get("country") not in (None, "US"):
                continue
            d = haversine_mi(s0.get("lat"), s0.get("lon"), s.get("lat"), s.get("lon"))
            if d is None or d > CONTROL_RADIUS_DEG * 100:      # ~100 miles
                continue
            if not (s.get("end") or "").startswith(str(today.year)):
                # Only stations NCEI itself lists as still reporting are useful
                # controls: a station that also stopped cannot answer the question.
                if (s.get("end") or "") <= stale_iso:
                    continue
            controls.append({**s, "distance_mi_from_subject": d})
        controls.sort(key=lambda r: r["distance_mi_from_subject"])
        controls = controls[:max_controls]
    out["control_stations"] = controls

    # Which year(s) to compare: the year the record stops in, and the one before.
    probe_years = []
    if stale_last:
        y = int(str(stale_last)[:4])
        probe_years = [y - 1, y]
    else:
        probe_years = [today.year - 1]
    out["probe_years"] = probe_years

    comparisons = []
    for year in probe_years:
        for stn in ([{"gsod_id": station_id, "name": station_name,
                      "is_subject": True, "distance_mi_from_subject": 0.0}]
                    + [{**c, "is_subject": False} for c in controls]):
            url = f"{GSOD_BASE}{year}/{stn['gsod_id']}.csv"
            r = fetch(url, timeout=300)
            manifest.append(r.provenance(
                note=f"GSOD {year} archive probe: {stn['gsod_id']}"))
            entry = {"year": year, "gsod_id": stn["gsod_id"],
                     "name": stn.get("name"), "is_subject": bool(stn.get("is_subject")),
                     "distance_mi": stn.get("distance_mi_from_subject"),
                     "url": url, "http_status": r.status, "ok": bool(r.ok)}
            if r.ok and r.body:
                last, last_wind, nrows = gsod_last_date(r.text())
                entry.update({"rows": nrows, "last_date": last,
                              "last_date_with_wind": last_wind,
                              "bytes": r.size, "sha256": r.sha256})
            elif r.status == 404:
                entry["expected_absent"] = "annual-file-not-published-for-this-year"
            comparisons.append(entry)
    out["gsod_comparisons"] = comparisons

    # Compare like with like: the subject's last date *in a given year* against
    # the controls' last dates in the same year.  Comparing a complete 2024 file
    # with a truncated 2025 one would manufacture a gap that is not there, so the
    # verdict is taken from the most recent year in which both sides have data.
    per_year = {}
    for c in comparisons:
        if not (c.get("ok") and c.get("last_date")):
            continue
        slot = per_year.setdefault(c["year"], {"subject": [], "controls": []})
        slot["subject" if c.get("is_subject") else "controls"].append(c)
    year_rows = []
    for year in sorted(per_year):
        side = per_year[year]
        if not side["subject"] or not side["controls"]:
            continue
        subj = max(x["last_date"] for x in side["subject"])
        ctrl = max(x["last_date"] for x in side["controls"])
        try:
            gap = (dt.date.fromisoformat(ctrl) - dt.date.fromisoformat(subj)).days
        except ValueError:
            gap = None
        year_rows.append({"year": year, "subject_last_date": subj,
                          "control_last_date": ctrl, "gap_days": gap,
                          "n_controls": len(side["controls"]),
                          "control_ids": sorted(x["gsod_id"] for x in side["controls"])})
    out["comparison_by_year"] = year_rows
    chosen = year_rows[-1] if year_rows else None

    verdict = None
    if not chosen:
        why = ("the subject station's GSOD file could not be read"
               if not any(c.get("is_subject") and c.get("ok") for c in comparisons)
               else "no control station's GSOD file could be read")
        verdict = {
            "classification": "not-determinable",
            "statement": (f"No year had both the subject station and a control station "
                          f"readable ({why}), so a station-specific gap cannot be "
                          "distinguished from an archive-wide one."),
        }
    else:
        gap = chosen["gap_days"]
        if gap is None:
            classification = "not-determinable"
            statement = "The two last dates could not be compared."
        elif gap <= SAME_STOP_SLACK_DAYS:
            classification = "archive-wide-lag"
            statement = (
                f"In {chosen['year']}, {chosen['n_controls']} control station(s) near "
                f"this airport stop within {gap} day(s) of the subject station "
                f"({chosen['subject_last_date']} vs {chosen['control_last_date']}), so "
                "the GSOD annual archive stopped advancing at about the same point for "
                "everyone. That is an NCEI publication/processing lag, not a station "
                "identifier change.")
        else:
            classification = "station-specific-gap"
            statement = (
                f"In {chosen['year']}, control stations run to "
                f"{chosen['control_last_date']} while this station's file stops at "
                f"{chosen['subject_last_date']} - {gap} days earlier. The gap is "
                "specific to this station's rows, which points at the station's own "
                "reporting or at its identifier rather than at the archive as a whole.")
        verdict = {
            "classification": classification,
            "statement": statement,
            "year_compared": chosen["year"],
            "subject_last_date": chosen["subject_last_date"],
            "control_last_date": chosen["control_last_date"],
            "gap_days": gap,
            "slack_days_allowed": SAME_STOP_SLACK_DAYS,
            "controls_compared": chosen["n_controls"],
            "control_ids": chosen["control_ids"],
            "successor_found": bool(successors),
            "successor_ids": [s["gsod_id"] for s in successors[:5]],
        }
    out["verdict"] = verdict

    # -------------------------------------------------- 3. GHCN-Daily wind
    ghcn_id = ((climo_data.get("meta") or {}).get("ghcn_wind_station")
               or {}).get("id") or "USW00023234"
    url = f"{GHCND_BASE}/{ghcn_id}.csv"
    r = fetch(url, timeout=600)
    manifest.append(r.provenance(
        note=f"GHCN-Daily {ghcn_id} probed for daily wind elements"))
    probe = {"station_id": ghcn_id, "url": url, "http_status": r.status,
             "ok": bool(r.ok), "bytes": r.size, "sha256": r.sha256}
    if r.ok and r.body:
        text = r.text()
        header = ghcn_header_elements(text)
        present = [e for e in GHCN_WIND_ELEMENTS if e in header]
        last, counts = ghcn_element_last_dates(text, present)
        probe.update({
            "header_columns": header,
            "wind_elements_present": present,
            "wind_elements_absent": [e for e in GHCN_WIND_ELEMENTS if e not in header],
            "last_date_by_element": last,
            "value_count_by_element": counts,
            "most_current_wind_date": max([v for v in last.values() if v], default=None),
        })
        if not present:
            note("info", "ncei_archive_probe",
                 f"GHCN-Daily {ghcn_id} carries none of the daily wind elements "
                 f"({', '.join(GHCN_WIND_ELEMENTS)}), so it is not a route to a current "
                 "wind record for this station.",
                 {"url": url, "header_columns": header[:40]})
        else:
            note("info", "ncei_archive_probe",
                 f"GHCN-Daily {ghcn_id} carries {', '.join(present)}; the most recent "
                 f"date with a wind value is {probe['most_current_wind_date']}.",
                 {"url": url, "last_date_by_element": last})
    else:
        note("warning", "ncei_archive_probe",
             f"GHCN-Daily {ghcn_id} could not be retrieved, so the independent "
             "current-wind test could not be run.",
             {"url": url, "status": r.status})
    out["ghcn_daily_wind_probe"] = probe

    # -------------------------------------------------- 4. NCEI alerts page
    r = fetch(NCEI_ALERTS_URL, timeout=120)
    manifest.append(r.provenance(note="NCEI service alerts page (data-access delays)"))
    if r.ok and r.body:
        out["ncei_alerts"] = parse_ncei_alerts(fetchlib.decode_text(r.body)[0], today)
        out["ncei_alerts"].update({"http_status": r.status, "sha256": r.sha256,
                                   "retrieved_utc": r.retrieved_utc})
    else:
        out["ncei_alerts"] = {"url": NCEI_ALERTS_URL, "http_status": r.status,
                              "ok": False,
                              "error": r.error or f"HTTP {r.status}"}

    # -------------------------------------------------- 5. what follows
    actions = []
    if successors:
        s = successors[0]
        actions.append({
            "action": "stitch the successor identifier into the wind archive",
            "successor_id": s["gsod_id"], "successor_name": s.get("name"),
            "begin": s.get("begin"), "end": s.get("end"),
            "note": ("Not done automatically: changing the wind station would move "
                     "every published 1991-2020 wind statistic, so the switch is a "
                     "deliberate, documented decision for a maintainer, not a "
                     "side effect of a nightly run."),
        })
    if probe.get("most_current_wind_date"):
        actions.append({
            "action": "publish the current wind record from GHCN-Daily alongside "
                      "(not instead of) the GSOD climatology",
            "station_id": probe["station_id"],
            "elements": probe.get("wind_elements_present"),
            "most_current_wind_date": probe["most_current_wind_date"],
            "note": ("GHCN-Daily wind is a different product from GSOD (AWND is a "
                     "daily mean, WSF2/WSF5 are the fastest 2-minute and 5-second "
                     "winds), so it is labelled with its own element names and never "
                     "mixed into the GSOD-based statistics."),
        })
    if (verdict or {}).get("classification") == "archive-wide-lag":
        actions.append({
            "action": "keep the stale-archive flag and re-probe nightly",
            "note": ("The archive stopped advancing for everyone; there is no "
                     "successor to switch to, so the honest output is the flag the "
                     "site already publishes, plus this evidence for it."),
        })
    out["recommended_actions"] = actions

    out["tests"] = [
        {"name": "successor identifier",
         "ran": bool(stations),
         "result": (f"{len(successors)} candidate(s) with an END date later than "
                    f"{stale_last}" if stations else "isd-history.csv not retrieved")},
        {"name": "control-station comparison",
         "ran": bool(out.get("comparison_by_year")),
         "result": (verdict or {}).get("classification")},
        {"name": "GHCN-Daily wind elements",
         "ran": bool(probe.get("ok")),
         "result": (f"present: {', '.join(probe.get('wind_elements_present') or []) or 'none'}"
                    if probe.get("ok") else "not retrieved")},
        {"name": "NCEI service alerts",
         "ran": bool((out.get("ncei_alerts") or {}).get("n_mentions") is not None),
         "result": (f"{(out.get('ncei_alerts') or {}).get('n_mentions')} data-access "
                    f"mention(s) on the alerts page")},
    ]
    out["provenance_note"] = ("Every URL touched is recorded in "
                              "data/ncei_archive_probe_provenance.json with its HTTP "
                              "status, byte count and SHA-256.")
    return out, manifest


def write_outputs(out, manifest, datadir):
    datadir = Path(datadir)
    datadir.mkdir(parents=True, exist_ok=True)
    (datadir / "ncei_archive_probe.json").write_text(
        json.dumps(out, indent=2) + "\n")
    provlib.write_manifest(
        datadir, "ncei_archive_probe", manifest, out["generated_utc"],
        "Fetches made by pipeline/ncei_archive_probe.py.")
    provlib.merge_irregularities(datadir, "ncei_archive_probe", out["irregularities"])
    return datadir / "ncei_archive_probe.json"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datadir", default="data")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--max-controls", type=int, default=None)
    ap.add_argument("--selftest", action="store_true",
                    help="run the classification logic offline against synthetic "
                         "NCEI files (no network, writes nothing)")
    args = ap.parse_args()

    if args.selftest:
        import selftest_ncei_probe
        return selftest_ncei_probe.run()

    datadir = Path(args.datadir)
    outdir = Path(args.outdir or args.datadir)
    log(f"NCEI archive probe - {dt.datetime.now(dt.timezone.utc).date().isoformat()}")
    out, manifest = build(datadir=datadir, max_controls=args.max_controls)
    path = write_outputs(out, manifest, outdir)
    v = out.get("verdict") or {}
    log(f"  verdict: {v.get('classification')} - {v.get('statement')}")
    log(f"  successors: {v.get('successor_ids') or 'none'}")
    log(f"  GHCN-Daily wind elements: "
        f"{(out.get('ghcn_daily_wind_probe') or {}).get('wind_elements_present')}")
    log(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
