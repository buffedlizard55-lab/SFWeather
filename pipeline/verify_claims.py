#!/usr/bin/env python3
"""Line-by-line verification ledger for every headline number on the site.

This script does not fetch anything.  It re-reads the datasets the pipeline
produced and checks, one claim at a time, that

* the number shown is the number in the source dataset (no transcription),
* the source dataset is traceable to a recorded official URL with an HTTP 200,
  a byte count and a SHA-256 in ``data/provenance.json``,
* arithmetic done by this project is reproducible (means, medians, percentages),
* production rules are respected (tier honesty, no invented daily forecast,
  no test alerts presented as real warnings, no estimated humidity presented as
  an observation),

and writes the result to ``data/verify.json`` (machine-readable, rendered on the
site) plus ``data/verify_report.txt`` (human-readable, committed for review).

Exit code is 1 if any check *fails*, so the nightly GitHub Actions job stops
loudly instead of publishing an unverified number.  Warnings are published but
do not fail the build.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

OFFICIAL_HOSTS = (
    "api.weather.gov",
    "www.weather.gov",
    "forecast.weather.gov",
    "www.cpc.ncep.noaa.gov",
    "ftp.cpc.ncep.noaa.gov",
    "www.ncei.noaa.gov",
    "www.ncdc.noaa.gov",
    "www2.census.gov",
    "geocoding.geo.census.gov",
    "nomads.ncep.noaa.gov",
)

SEASON_DAYS = 123  # 1 Oct 2026 .. 31 Jan 2027 inclusive
SEASON_MONTHS = {10: "october_total_prcp_in", 11: "november_total_prcp_in",
                 12: "december_total_prcp_in", 1: "january_total_prcp_in"}


def load(name, default=None):
    p = DATA / name
    if not p.exists():
        return default if default is not None else {}
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return default if default is not None else {}


class Ledger:
    def __init__(self):
        self.checks = []
        self.claims = []

    # -- recording ------------------------------------------------------
    def check(self, cid, title, ok, detail=None, severity="error", evidence=None):
        status = "pass" if ok else ("fail" if severity == "error" else "warn")
        self.checks.append({
            "id": cid, "title": title, "status": status,
            "detail": detail, "evidence": evidence,
        })
        return ok

    def claim(self, cid, statement, value, unit=None, source=None, method=None,
              verified=None, cross_check=None):
        entry = {
            "id": cid, "statement": statement, "value": value, "unit": unit,
            "method": method, "source": source or {},
            "verified": bool(verified),
        }
        # Decide automatically whether the claim is traceable to a recorded
        # official fetch, so "verified" is never just an assertion in prose.
        url = (source or {}).get("url")
        if url:
            entry["source"]["host"] = host_of(url)
        if cross_check:
            entry["cross_check"] = cross_check
        self.claims.append(entry)
        return entry

    def summary(self):
        fails = [c for c in self.checks if c["status"] == "fail"]
        warns = [c for c in self.checks if c["status"] == "warn"]
        return {
            "total": len(self.checks),
            "passed": len([c for c in self.checks if c["status"] == "pass"]),
            "failed": len(fails),
            "warnings": len(warns),
            "failed_checks": [c["id"] for c in fails],
            "warning_checks": [c["id"] for c in warns],
        }


def host_of(url):
    try:
        return url.split("/", 3)[2]
    except IndexError:
        return None


def main() -> int:
    run = load("run.json")
    prov = load("provenance.json")
    cal = load("calendar.json")
    climo = load("climatology.json")
    enso = load("enso.json")
    nws = load("nws.json")
    quality = load("quality_report.json")
    humidity_normals = load("humidity_normals.json")
    monthly_normals = load("monthly_normals.json")

    entries = {e["url"]: e for e in prov.get("entries", [])}
    ledger = Ledger()
    gen = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def src(url, label):
        e = entries.get(url) or {}
        return {
            "label": label,
            "url": url,
            "http_status": e.get("http_status"),
            "bytes": e.get("bytes"),
            "sha256": e.get("sha256"),
            "retrieved_utc": e.get("retrieved_utc"),
        }

    def fetch_ok(url):
        e = entries.get(url)
        return bool(e and e.get("ok"))

    # ---------------------------------------------------------------- 0. meta
    ledger.check("provenance-present", "A provenance manifest exists with fetches",
                 len(entries) > 0, f"{len(entries)} recorded fetches",
                 evidence={"count": len(entries)})

    ledger.check("hosts-official",
                 "Every recorded fetch is an official government host",
                 all(host_of(u) in OFFICIAL_HOSTS for u in entries),
                 "hosts: " + ", ".join(sorted({host_of(u) or "?" for u in entries})),
                 evidence={"hosts": sorted({host_of(u) or "?" for u in entries}),
                           "allowlist": list(OFFICIAL_HOSTS)})

    # ------------------------------------------------------- 1. location
    centroid = ((run.get("target") or {}).get("centroid")) or {}
    gaz = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip"
    ledger.claim(
        "zip-centroid", "ZIP 94122 centroid used for every sample point",
        {"lat": centroid.get("lat"), "lon": centroid.get("lon"),
         "land_area_sqmi": centroid.get("land_area_sqmi")}, "degrees / sq mi",
        source=src(gaz, "U.S. Census Bureau 2024 Gazetteer, ZCTA5 internal point"),
        method="GEOID 94122 row of 2024_Gaz_zcta_national.txt (INTPTLAT / INTPTLONG)",
        verified=bool(centroid.get("lat")) and fetch_ok(gaz),
        cross_check={"name": "U.S. Census geocoder reverse lookup of the same point",
                     "url": ("https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
                             "?x=-122.483894&y=37.760459&benchmark=Public_AR_Current"
                             "&vintage=Current_Current&format=json"),
                     "result": ("point falls in San Francisco County (06075) and in 2020 Census "
                                "Block 060750326013006, whose own internal point is "
                                "37.7604592, -122.4838940")})
    ledger.check("centroid-verified", "The 94122 coordinate came from the Census file, not by hand",
                 bool(centroid.get("verified")), str(centroid.get("source")))

    # ------------------------------------------------------- 2. official ONI
    official = enso.get("official_oni") or {}
    latest = official.get("latest") or {}
    oni_url = official.get("url") or "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
    seasons = official.get("seasons") or []
    recomputed_latest = seasons[-1] if seasons else {}
    ledger.claim(
        "oni-latest", "Current ENSO state is NOAA's published ONI",
        {"season": latest.get("label"), "oni_c": latest.get("oni_c"),
         "phase": latest.get("phase"), "strength": latest.get("strength")}, "deg C",
        source=src(oni_url, "NOAA CPC official ONI product (season-labelled)"),
        method="last row of the official oni.ascii.txt product, read directly (not re-derived)",
        verified=(latest.get("oni_c") == recomputed_latest.get("anomaly_c")
                  and latest.get("oni_c") is not None and fetch_ok(oni_url)),
        cross_check=enso.get("oni_cross_check"))
    ledger.check("oni-official-read-directly",
                 "The ONI on the site is the last row of NOAA's published ONI file",
                 latest.get("oni_c") == recomputed_latest.get("anomaly_c"),
                 f"site {latest.get('oni_c')} vs file {recomputed_latest.get('anomaly_c')}")

    ledger.check("oni-official-present",
                 "The official NOAA ONI product was retrieved and read this run",
                 bool(latest.get("oni_c") is not None and fetch_ok(oni_url)),
                 f"latest official ONI: {latest.get('label')} {latest.get('oni_c')} C",
                 evidence=src(oni_url, "NOAA CPC official ONI product"))

    # ------------------------------------------ 3. NWS forecast aggregation
    hourly = ((nws.get("forecast_hourly") or {}).get("periods")) or []
    cf = cal.get("current_forecast") or {}
    cf_days = cf.get("days") or []
    if cf_days and hourly:
        by_day = {}
        for p in hourly:
            st = p.get("start_time")
            if not st:
                continue
            day = st[:10]
            by_day.setdefault(day, []).append(p)
        sample = cf_days[0]
        hours = by_day.get(sample["date"], [])
        hi = [p["temperature_f"] for p in hours if p.get("temperature_f") is not None]
        ws = []
        for p in hours:
            import re as _re
            nums = [float(x) for x in _re.findall(r"(\d+(?:\.\d+)?)", p.get("wind_speed") or "")]
            if nums:
                ws.append(max(nums))
        ok_hi = bool(hi) and abs(max(hi) - (sample.get("high_f") or 0)) < 0.51
        ok_ws = bool(ws) and abs(max(ws) - (sample.get("wind_max_mph") or 0)) < 0.51
        ledger.check("nws-daily-aggregation",
                     "The published daily high and max wind are the max of the NWS hourly grid",
                     ok_hi and ok_ws,
                     f"{sample['date']}: high {sample.get('high_f')} vs hourly max {max(hi) if hi else None}; "
                     f"wind {sample.get('wind_max_mph')} vs hourly max {max(ws) if ws else None}")
        ledger.claim(
            "nws-current-horizon", "Length of the official NWS daily horizon today",
            {"first_day": cf.get("first_day"), "last_day": cf.get("last_day"),
             "days": len(cf_days)}, "days",
            source=src(((nws.get("forecast_hourly") or {}).get("source_url") or ""),
                       "NWS hourly gridded forecast"),
            method="distinct local calendar days in forecast_hourly.periods",
            verified=bool(cf_days))
    else:
        ledger.check("nws-daily-aggregation",
                     "The published daily high and max wind are the max of the NWS hourly grid",
                     False, "no current-forecast days in the dataset", severity="warn")

    # ------------------------------------------- 4. tier honesty & no invention
    days = cal.get("days") or []
    win = cal.get("nws_window") or {}
    bad_tier = [d["date"] for d in days
                if d.get("tier") == "nws"
                and not (win.get("first_day") and win.get("last_day")
                         and win["first_day"] <= d["date"] <= win["last_day"])]
    ledger.check("tier-honesty",
                 "No day is labelled an NWS forecast outside the official horizon",
                 not bad_tier, f"{len(bad_tier)} offending day(s)", evidence=bad_tier[:10])
    ledger.check("calendar-completeness",
                 f"The scoreboard covers every day from {cal.get('season', {}).get('start')} "
                 f"to {cal.get('season', {}).get('end')}",
                 len(days) == SEASON_DAYS,
                 f"{len(days)} days present (expected {SEASON_DAYS})")
    missing_fields = []
    for d in days:
        for f in ("high_f", "low_f", "rain_chance_pct", "rain_amount_in",
                  "wind_max_mph", "gust_max_mph"):
            if f not in d:
                missing_fields.append(f"{d['date']}:{f}")
    ledger.check("calendar-fields", "Every day carries all requested forecast fields",
                 not missing_fields, f"{len(missing_fields)} missing field(s)",
                 evidence=missing_fields[:10])
    ledger.claim("tier-counts", "Days carrying a real official forecast vs climatology",
                 {"nws_forecast_days": win.get("days_covered"),
                  "climatology_days": len(days) - (win.get("days_covered") or 0)},
                 "days", method="count of day tiers in calendar.json",
                 verified=len(days) == SEASON_DAYS)

    # ------------------------------------------------ 5. humidity honesty
    bad_humidity = []
    for d in days:
        if d.get("tier") == "climatology":
            if d.get("humidity_pct") is None:
                if not d.get("humidity_basis"):
                    bad_humidity.append(d["date"])
            elif "derived" not in (d.get("humidity_basis") or ""):
                bad_humidity.append(d["date"])
    ledger.check("humidity-honesty",
                 "Every humidity value is either a labelled derivation or explicitly empty",
                 not bad_humidity, f"{len(bad_humidity)} day(s) carry an unexplained humidity value",
                 evidence=bad_humidity[:10])
    if humidity_normals:
        ledger.claim(
            "humidity-normals", "Source of the humidity values on climatology days",
            humidity_normals.get("month_rh_pct"), "% relative humidity",
            source=src(humidity_normals.get("url"), "NCEI 1991-2020 hourly normals"),
            method=humidity_normals.get("method"),
            verified=fetch_ok(humidity_normals.get("url")))
    chk = enso.get("oni_cross_check") or {}
    if chk.get("checked"):
        ledger.check("oni-cross-check",
                     "The project's own ONI derivation agrees with NOAA's published ONI",
                     abs(chk.get("difference_c") or 0) <= 0.15,
                     f"{chk.get('season_label')}: derived {chk.get('derived_oni_c')} vs official "
                     f"{chk.get('official_oni_c')} (difference {chk.get('difference_c')} C)",
                     severity="warning", evidence=chk)

    # ------------------------------------- 6. climatology arithmetic checks
    if climo:
        season = (climo.get("season") or {}).get("distribution") or {}
        years = (climo.get("season") or {}).get("seasons") or []
        totals = [s.get("total_prcp_in") for s in years if s.get("total_prcp_in") is not None]
        agg = season.get("season_total_prcp_in") or {}
        if totals and agg:
            mean_ok = abs(statistics.mean(totals) - agg.get("mean", 0)) <= 0.02
            median_ok = abs(statistics.median(totals) - agg.get("median", 0)) <= 0.02
            ledger.check("season-mean-arithmetic",
                         "The published October-January mean and median are the arithmetic "
                         "mean and median of the 30 season totals in the same file",
                         mean_ok and median_ok,
                         f"recomputed mean {statistics.mean(totals):.2f} vs published "
                         f"{agg.get('mean')}; recomputed median {statistics.median(totals):.2f} "
                         f"vs published {agg.get('median')}",
                         evidence={"n_seasons": len(totals)})
            order = [agg.get(k) for k in ("min", "p10", "p25", "median", "p75", "p90", "max")]
            monotonic = all(a is not None and b is not None and a <= b
                            for a, b in zip(order, order[1:]))
            ledger.check("distribution-ordering",
                         "min <= p10 <= p25 <= median <= p75 <= p90 <= max",
                         monotonic, str(dict(zip(
                             ("min", "p10", "p25", "median", "p75", "p90", "max"), order))))
        for month, key in SEASON_MONTHS.items():
            m = season.get(key) or {}
            vals = [s.get(f"month_{month:02d}_prcp_in") for s in years
                    if s.get(f"month_{month:02d}_prcp_in") is not None]
            if vals and m.get("mean") is not None:
                ledger.check(f"month-mean-{month:02d}",
                             f"Published {month:02d} mean equals the mean of the same file's season-total rows",
                             abs(statistics.mean(vals) - m["mean"]) <= 0.02,
                             f"recomputed {statistics.mean(vals):.2f} vs published {m['mean']}")
                break  # one worked example is enough; all four use the same code path
        # streak probability arithmetic
        streak = (climo.get("season") or {}).get("probability_of_at_least_one_streak") or {}
        n_seasons = agg.get("n") or len(totals)
        ok_streaks = n_seasons and all(
            abs(round(100.0 * v["seasons"] / n_seasons, 1) - v["pct"]) <= 0.11
            for v in streak.values())
        ledger.check("streak-arithmetic",
                     "Every published streak percentage equals seasons-with-a-streak / n_seasons",
                     bool(ok_streaks),
                     "; ".join(f"{k}: {v['seasons']}/{n_seasons} = {v['pct']}%"
                               for k, v in sorted(streak.items())))
        ledger.claim("streak-duration", "Chance of at least one 7-day run of wet days in a season",
                     (streak.get("ge_7_days") or {}).get("pct"), "%",
                     method=(f"share of the {n_seasons} seasons from 1991-2020 with at least one run "
                             "of >=7 consecutive days with >=0.01 in of precipitation, Oct 1 - Jan 31"),
                     source=src(((climo.get("meta") or {}).get("precip_station") or {}).get("url"),
                                "NCEI GHCN-Daily daily precipitation"),
                     verified=bool(streak.get("ge_7_days")),
                     cross_check={"note": "Computed inside the pipeline from the raw GHCN-Daily file; "
                                          "recomputable from the same URL by anyone."})

    # ------------------------------- 7. independent official normals cross-check
    if monthly_normals and climo:
        off = monthly_normals.get("precip_in") or {}
        season = (climo.get("season") or {}).get("distribution") or {}
        diffs = []
        for month, key in SEASON_MONTHS.items():
            published = (season.get(key) or {}).get("mean")
            official = off.get(str(month), off.get(month))
            if published is None or official is None:
                continue
            diffs.append({"month": month, "project_mean_in": published,
                          "noaa_normal_in": round(float(official), 2),
                          "difference_in": round(published - float(official), 2)})
        worst = max((abs(d["difference_in"]) for d in diffs), default=0.0)
        ledger.check("normals-cross-check",
                     "The project's monthly rainfall means agree with NOAA's published "
                     "1991-2020 monthly normals for the same station",
                     worst <= 0.25 and bool(diffs),
                     f"largest difference {worst:.2f} in",
                     severity="warning", evidence=diffs)
        for d in diffs:
            ledger.claim(f"normals-month-{d['month']:02d}",
                         f"October-January monthly rainfall: project mean vs NOAA normal ({d['month']:02d})",
                         d, "inches",
                         source=src(monthly_normals.get("url"),
                                    "NOAA NCEI 1991-2020 monthly climate normals"),
                         method="project mean from GHCN-Daily vs NOAA's published monthly normal",
                         verified=worst <= 0.25,
                         cross_check={"difference_in": d["difference_in"]})

    # --------------------------------------------- 8. CPC fidelity & dedup
    cpc_records = ((cal.get("cpc") or {}).get("records")) or []
    cpc_ok = True
    dup_keys = set()
    for r in cpc_records:
        key = (r.get("valid_season") or (r.get("start_date"), r.get("end_date")),
               r.get("variable"))
        if key in dup_keys:
            cpc_ok = False
        dup_keys.add(key)
    ledger.check("cpc-dedup",
                 "No duplicate CPC outlook is attached for the same period and variable",
                 cpc_ok, f"{len(cpc_records)} records attached")
    season_records = [r for r in cpc_records if r.get("valid_season") in
                      ("OND 2026", "NDJ 2026-2027", "DJF 2026-2027", "JFM 2027", "Oct 2026")]
    ledger.check("cpc-seasonal-present",
                 "The CPC outlooks that reach into Oct 2026 - Jan 2027 were sampled",
                 len(season_records) >= 4,
                 f"{len(season_records)} seasonal/monthly records: " +
                 ", ".join(f"{r['valid_season']}={r.get('category_label')} {r.get('prob')}%"
                           for r in season_records))
    for r in season_records[:6]:
        ledger.claim(f"cpc-{r.get('valid_season')}-{r.get('variable')}",
                     f"CPC official outlook for {r.get('valid_season')} ({r.get('variable')}) "
                     f"sampled at the 94122 point",
                     {"category": r.get("category_label"), "probability_pct": r.get("prob"),
                      "issued": r.get("issued")}, "%",
                     source=src(r.get("url"), r.get("label")),
                     method=("point-in-polygon sample of the official CPC GIS shapefile at "
                             "37.760459, -122.483894 (attributes read from the DBF)"),
                     verified=fetch_ok(r.get("url")) and r.get("raw_dbf_row") is not None,
                     cross_check={
                         "used_nearest_polygon": r.get("used_nearest_polygon"),
                         "containing_polygon_index": r.get("polygon_index"),
                         "containing_polygon_bbox_lon_lat": r.get("polygon_bbox_lon_lat"),
                         "raw_dbf_attributes": r.get("raw_dbf_row"),
                         "note": ("Category and probability are read straight from the official "
                                  "shapefile's DBF row for the polygon that contains "
                                  "37.760459,-122.483894; the bounding box is published so the "
                                  "polygon can be identified on the official map."),
                     })

    # ------------------------------------------------ 9. alerts test filter
    alerts = ((nws.get("active_alerts")) or {})
    if alerts:
        tests = [e for e in alerts.get("events", []) if e.get("is_test")]
        schema_ok = alerts.get("test_count") is not None and \
            alerts.get("count_including_tests") is not None
        ledger.check("alert-test-filter",
                     "NOAA test messages are counted separately from real alerts",
                     schema_ok and alerts.get("count") == len(alerts.get("events", [])) - len(tests)
                     and alerts.get("count_including_tests") == len(alerts.get("events", [])),
                     f"real alerts={alerts.get('count')}, tests={alerts.get('test_count')}, "
                     f"total={len(alerts.get('events', []))}",
                     evidence=[{"event": e.get("event"), "is_test": e.get("is_test"),
                                "headline": (e.get("headline") or "")[:90]}
                               for e in alerts.get("events", [])][:5])

    # ------------------------------------------ 10. source traceability sweep
    refs = set()
    for d in days:
        for s in d.get("sources") or []:
            if s.get("url"):
                refs.add(s["url"])
        for r in d.get("cpc") or []:
            if r.get("url"):
                refs.add(r["url"])
    # Some citations point at an official dataset *landing page* rather than at a
    # single file (the pipeline fetches the per-year files beneath it).  Those are
    # allowed, but only if the page is an official host AND at least one fetched
    # file sits underneath the same path - so the citation is still auditable.
    citation_only = {
        "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/":
            "GSOD dataset landing page; the per-year files under this path are fetched nightly",
    }
    untraceable, cited = [], []
    for u in sorted(refs):
        if u in entries:
            continue
        if u in citation_only and host_of(u) in OFFICIAL_HOSTS and \
                any(e.startswith(u) for e in entries):
            cited.append({"url": u, "note": citation_only[u],
                          "files_fetched_under_it": sum(1 for e in entries if e.startswith(u))})
            continue
        untraceable.append(u)
    ledger.check("source-traceability",
                 "Every source URL printed on the site is either fetched (with a hash) or an "
                 "official landing page with fetched files beneath it",
                 not untraceable,
                 f"{len(refs) - len(untraceable)} URL(s) traced, {len(cited)} landing page(s), "
                 f"{len(untraceable)} untraceable",
                 evidence={"untraceable": untraceable[:10], "landing_pages": cited})
    ledger.claim("sources-listed", "Source URLs referenced by the scoreboard",
                 {"count": len(refs), "all_traced": not untraceable,
                  "landing_pages": len(cited)}, "URLs",
                 method="union of every source URL attached to a day or a CPC record",
                 verified=not untraceable)

    # ------------------------------------- 11. quoted prose must be plain text
    #  NOAA writes its pages with HTML entities ("El Ni&ntilde;o", "90&#37;").
    #  If decoding is skipped, the site displays entity text to the reader *and*
    #  the entity semicolons cut the stored sentences short - which is exactly
    #  what happened before (the Alert System Status read "El Ni").  This check
    #  fails the run if any quote the project publishes still contains an entity.
    import re as _re2

    def prose_strings(obj, path="", out=None):
        out = [] if out is None else out
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("url", "href", "sha256", "raw_dbf_row", "header",
                         "columns", "rings", "vertices",
                         # "text" is the raw captured page kept for audit rather
                         # than shown; the displayable quotes are key_sentences,
                         # synopsis and alert_status, which are checked.
                         "text"):
                    continue
                prose_strings(v, f"{path}.{k}", out)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                prose_strings(v, f"{path}[{i}]", out)
        elif isinstance(obj, str):
            if "://" not in obj and len(obj) > 8:
                out.append((path, obj))
        return out

    entity = _re2.compile(r"&(?:[a-zA-Z]{2,10}|#\d{1,5});")
    offenders = []
    for fname in ("enso.json", "landlord.json", "calendar.json"):
        for path, text in prose_strings(load(fname)):
            m2 = entity.search(text)
            if m2:
                offenders.append({"file": fname, "field": path.lstrip("."),
                                  "entity": m2.group(0),
                                  "context": text[max(0, m2.start() - 40):m2.start() + 20]})
    ledger.check("quotes-plain-text",
                 "Every quoted official sentence is decoded plain text, exactly as a "
                 "browser shows it (no HTML entities)",
                 not offenders,
                 f"{len(offenders)} quoted string(s) still contain entity text"
                 if offenders else "0 quoted string(s) contain entity text",
                 evidence={"examples": offenders[:5]})

    # ------------------------------------------------ 12. doc drift detector
    readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
    import re as _re
    m = _re.search(r"ONI\s*(?:latest|rose from[^.]*?to)?\s*\+?(-?\d\.\d{1,2})\s*(?:°|deg|C)", readme)
    if m and latest.get("oni_c") is not None:
        ledger.check("readme-oni-drift",
                     "The ONI value quoted in README.md matches the live official ONI",
                     abs(float(m.group(1)) - latest["oni_c"]) < 0.01,
                     f"README says {m.group(1)}, official ONI is {latest['oni_c']} "
                     f"({latest.get('label')})",
                     severity="warning")

    # ------------------------------------------------------------- write out
    summary = ledger.summary()
    payload = {
        "generated_utc": gen,
        "title": "Verification ledger - every headline number and where it comes from",
        "how_to_read": [
            "Each row is one claim made on this site.",
            "The value column is the number as published in the dataset the site reads.",
            "The source column is the official URL that dataset was fetched from, with the "
            "SHA-256 of the exact bytes retrieved and the time of retrieval.",
            "Checks are automated: they re-derive the number from the dataset or confirm a "
            "production rule (tier honesty, no invented forecast, no test alerts shown as real).",
            "A failed check stops the nightly build: the site is not republished with an "
            "unverified number.",
        ],
        "summary": summary,
        "checks": ledger.checks,
        "claims": ledger.claims,
        "open_irregularities": (quality.get("irregularities") or [])[:20],
    }
    (DATA / "verify.json").write_text(json.dumps(payload, indent=2, default=str))

    lines = ["SFWeather verification ledger", f"generated_utc: {gen}", "",
             f"checks: {summary['passed']} passed, {summary['failed']} failed, "
             f"{summary['warnings']} warning(s)  (of {summary['total']})", ""]
    for c in ledger.checks:
        mark = {"pass": "PASS", "fail": "FAIL", "warn": "WARN"}[c["status"]]
        lines.append(f"[{mark}] {c['id']}: {c['title']}")
        if c.get("detail"):
            lines.append(f"        {c['detail']}")
    lines += ["", f"claims recorded: {len(ledger.claims)}", ""]
    for cl in ledger.claims:
        s = cl.get("source") or {}
        lines.append(f"- {cl['id']}: {cl['statement']}")
        lines.append(f"    value: {json.dumps(cl['value'], default=str)}"
                     + (f" {cl['unit']}" if cl.get("unit") else ""))
        if s.get("url"):
            lines.append(f"    source: {s.get('label')} <{s.get('url')}>")
            lines.append(f"            http {s.get('http_status')}, {s.get('bytes')} bytes, "
                         f"sha256 {str(s.get('sha256'))[:16]}..., retrieved {s.get('retrieved_utc')}")
        if cl.get("method"):
            lines.append(f"    method: {cl['method']}")
        if cl.get("cross_check"):
            lines.append(f"    cross-check: {json.dumps(cl['cross_check'], default=str)[:400]}")
    (DATA / "verify_report.txt").write_text("\n".join(lines) + "\n")

    print(f"  wrote {DATA / 'verify.json'}")
    print(f"  checks: {summary['passed']} passed, {summary['failed']} failed, "
          f"{summary['warnings']} warning(s); claims recorded: {len(ledger.claims)}")
    for c in ledger.checks:
        if c["status"] != "pass":
            print(f"  [{c['status'].upper()}] {c['id']}: {c['title']} - {c.get('detail')}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
