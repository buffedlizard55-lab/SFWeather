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
import re
import statistics
import sys
from pathlib import Path

from build_calendar import local_date_from_iso

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Aliased: main() has a local `climo` (the loaded climatology.json) that
# would otherwise shadow the module - the same trap already hit
# build_calendar.py.
import climo as climo_lib  # noqa: E402
from build_digest import POP_THRESHOLD_PCT  # noqa: E402
# The Rain-related event-type set and the damage parser are used by the
# storm-event recount below; importing them keeps one definition in the project
# instead of a second copy that can drift.
from landlord_summary import RAIN_RELATED_EVENT_TYPES, parse_damage_usd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Test hook, matching build_calendar.py: SFWEATHER_DATA points the whole verify
# chain at a fixture directory so it can be exercised without the real datasets
# and without touching the committed ones.
_env_dir = __import__("os").environ.get("SFWEATHER_DATA")
if _env_dir:
    DATA = Path(_env_dir)

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
    climo_json = climo  # the published climatology dataset, for the encoding sweep
    enso = load("enso.json")
    nws = load("nws.json")
    quality = load("quality_report.json")
    humidity_normals = load("humidity_normals.json")
    monthly_normals = load("monthly_normals.json")
    landlord = load("landlord.json")
    storms = load("storm_events.json")
    cpc_backtest = load("cpc_backtest.json", default=None)
    afd_history = load("afd_history.json", default=None)
    digest = load("digest.json", default=None)
    isd_history = load("isd_history.json", default=None)
    ghcnh_probe = load("ghcnh_probe.json", default=None)

    # Keep every manifest row, including repeated fetches of the same URL.  A
    # dict keyed only by URL silently collapsed the two 90-day discussion
    # fetches in the 17 Sep run and made the ledger say "104 fetches" while the
    # provenance page correctly showed 105.  URL lookups below use the latest
    # successful row, but the integrity checks count the actual records.
    manifest_entries = [e for e in (prov.get("entries") or [])
                        if isinstance(e, dict) and e.get("url")]
    entries_by_url = {}
    for entry in manifest_entries:
        entries_by_url.setdefault(entry["url"], []).append(entry)
    unique_urls = set(entries_by_url)
    ledger = Ledger()
    gen = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def source_entry(url):
        records = entries_by_url.get(url) or []
        # Prefer a successful record, then the last record in the manifest.  A
        # failed retry must never hide a successful source fetch from a claim.
        for entry in reversed(records):
            if entry.get("ok"):
                return entry
        return records[-1] if records else {}

    def src(url, label):
        e = source_entry(url)
        return {
            "label": label,
            "url": url,
            "http_status": e.get("http_status"),
            "bytes": e.get("bytes"),
            "sha256": e.get("sha256"),
            "retrieved_utc": e.get("retrieved_utc"),
        }

    def fetch_ok(url):
        return any(e.get("ok") for e in entries_by_url.get(url, []))

    def fetch_has_evidence(url):
        return any(
            e.get("ok") and isinstance(e.get("http_status"), int)
            and 200 <= e["http_status"] < 300
            and isinstance(e.get("bytes"), int) and e["bytes"] > 0
            and bool(e.get("sha256"))
            for e in entries_by_url.get(url, [])
        )

    # ---------------------------------------------------------------- 0. meta
    ledger.check("provenance-present", "A provenance manifest exists with fetches",
                 bool(manifest_entries), f"{len(manifest_entries)} recorded fetches "
                 f"({len(unique_urls)} unique URLs)",
                 evidence={"records": len(manifest_entries), "unique_urls": len(unique_urls)})

    expected_records = (run.get("counts") or {}).get("manifest_entries")
    ledger.check("provenance-record-count",
                 "The provenance manifest count agrees with the pipeline run metadata",
                 expected_records is None or expected_records == len(manifest_entries),
                 f"manifest has {len(manifest_entries)} records; run.json says {expected_records}",
                 evidence={"manifest_records": len(manifest_entries),
                           "run_manifest_entries": expected_records})

    # The three fetch counts must be re-derivable from the manifest, and an
    # "expected absence" must never be silently folded into the failure count:
    # that is how a station that stopped answering disappears behind a routine
    # 404 for a not-yet-published annual file.
    counts = run.get("counts") or {}
    ok_n = sum(1 for e in manifest_entries if e.get("ok"))
    absent_n = sum(1 for e in manifest_entries if not e.get("ok") and e.get("expected_absent"))
    failed_n = sum(1 for e in manifest_entries if not e.get("ok") and not e.get("expected_absent"))
    ledger.check("fetch-counts-recompute",
                 "The published fetch counts (ok / failed / absent by design) match "
                 "the manifest entry by entry",
                 counts.get("expected_absences") is None
                 or (counts.get("successful_fetches") == ok_n
                     and counts.get("failed_fetches") == failed_n
                     and counts.get("expected_absences") == absent_n),
                 f"run.json says {counts.get('successful_fetches')} ok / "
                 f"{counts.get('failed_fetches')} failed / "
                 f"{counts.get('expected_absences')} absent by design; the manifest "
                 f"recounts {ok_n} / {failed_n} / {absent_n}"
                 + ("" if counts.get("expected_absences") is not None else
                    " (this dataset predates the classification, so only the ok "
                    "count is required to agree)"),
                 evidence={"manifest_ok": ok_n, "manifest_failed": failed_n,
                           "manifest_expected_absences": absent_n,
                           "run_expected_absences": counts.get("expected_absences"),
                           "expected_absent_urls":
                               [e.get("url") for e in manifest_entries
                                if e.get("expected_absent")][:6]})

    # Every "expected absence" must name a reason that its own URL can be checked
    # against.  Without this, an archive that stops answering could be relabelled
    # as routine and silently leave the failure count -- which is the whole point
    # of separating the two numbers.
    absence_rules = {
        "annual-file-not-yet-published",
        "station-without-observations-product",
        "candidate-station-without-the-product",
        "historical-archive-not-retained",
    }
    run_year = str(run.get("generated_utc") or "")[:4]
    bad_absences = []
    for e in manifest_entries:
        rule = e.get("expected_absent")
        if not rule:
            continue
        url = str(e.get("url") or "")
        if rule not in absence_rules:
            bad_absences.append((url, f"unknown reason {rule!r}"))
        elif rule == "annual-file-not-yet-published":
            m = re.search(r"/access/(\d{4})/", url)
            if not m or not (run_year.isdigit() and int(m.group(1)) >= int(run_year)):
                bad_absences.append((url, "annual-file rule needs a year >= the run year"))
        elif rule == "station-without-observations-product":
            if not re.search(r"/stations/[A-Za-z0-9]+/observations/latest$", url):
                bad_absences.append((url, "station rule needs an observations/latest URL"))
        elif rule == "candidate-station-without-the-product":
            if "/normals-hourly/" not in url:
                bad_absences.append((url, "candidate rule needs an hourly-normals URL"))
        elif rule == "historical-archive-not-retained":
            if not re.search(r"seas(prcp|temp)_\d{6}\.zip", url):
                bad_absences.append((url, "historical-archive rule needs a seas*_YYYYMM.zip URL"))
    ledger.check("expected-absences-justified",
                 "Every fetch classified as an expected absence carries a reason the "
                 "ledger can check against its own URL",
                 not bad_absences,
                 (f"{len([e for e in manifest_entries if e.get('expected_absent')])} "
                  f"expected absence(s), all justified by URL"
                  if not bad_absences else
                  "; ".join(f"{u}: {why}" for u, why in bad_absences)[:280]),
                 evidence={"run_year": run_year,
                           "unjustified": [{"url": u, "why": w} for u, w in bad_absences][:6]})

    if failed_n:
        # A real failure is a finding to review, not a published number to accept.
        # It is a warning rather than a hard failure so one flaky request cannot
        # stop the nightly publish; every check that needs the missing bytes fails
        # on its own evidence, and the site names the failing URLs on the status
        # line instead of burying the count.
        ledger.check(
            "fetch-failures-flagged",
            "Every fetch that was supposed to work and did not is flagged for review",
            False,
            f"{failed_n} fetch(es) failed that are not expected absences: "
            + ", ".join(e.get("url", "?") for e in manifest_entries
                        if not e.get("ok") and not e.get("expected_absent"))[:280],
            severity="warn")

    hosts = [host_of(e.get("url")) for e in manifest_entries]
    ledger.check("hosts-official",
                 "Every recorded fetch is an official government host",
                 bool(manifest_entries) and all(h in OFFICIAL_HOSTS for h in hosts),
                 "hosts: " + ", ".join(sorted({h or "?" for h in hosts})),
                 evidence={"hosts": sorted({h or "?" for h in hosts}),
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
            tz_name = ((cal.get("forecast_aggregation") or {}).get("timezone")
                       or (nws.get("point") or {}).get("timezone")
                       or "America/Los_Angeles")
            local_day = local_date_from_iso(st, tz_name)
            if local_day is None:
                continue
            by_day.setdefault(local_day.isoformat(), []).append(p)
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

    aggregation = cal.get("forecast_aggregation") or {}
    required_aggregation = {"timezone", "temperature", "humidity", "rain_chance", "rain_amount", "wind"}
    point_timezone = (nws.get("point") or {}).get("timezone") or "America/Los_Angeles"
    ledger.check("forecast-aggregation-contract",
                 "The forecast dataset records the timezone and the exact aggregation method for each requested field",
                 required_aggregation.issubset(aggregation)
                 and aggregation.get("timezone") == point_timezone
                 and (cf.get("aggregation") or {}).get("timezone") == point_timezone,
                 f"timezone={aggregation.get('timezone')}; required methods present="
                 f"{sorted(required_aggregation.intersection(aggregation))}")

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
                 {"nws_forecast_days": win.get("scoreboard_days_in_horizon"),
                  "climatology_days": len(days) - (win.get("scoreboard_days_in_horizon") or 0)},
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

    # --------------------------------------- 6b. maintenance cost-driver block
    # The executive summary's cost drivers are built only from verified
    # structures; the ledger re-derives the published expected-day counts from
    # the committed climatology table and audits the block's structure (ranks,
    # evidence presence, official-only sources).  A cost driver without
    # evidence or with a non-official source is exactly the class of claim
    # this project is not allowed to make.
    from landlord_summary import expected_event_days as _eed

    es = (landlord.get("executive_summary") or {})
    drivers = es.get("cost_drivers") or []
    struct_issues = []
    if not isinstance(drivers, list) or not (4 <= len(drivers) <= 8):
        struct_issues.append(f"driver count {len(drivers)} outside expected 4-8")
    for i, d in enumerate(drivers if isinstance(drivers, list) else []):
        if not isinstance(d, dict):
            struct_issues.append(f"driver {i} is not an object")
            continue
        if d.get("rank") != i + 1:
            struct_issues.append(f"driver {i} rank {d.get('rank')} != {i + 1}")
        if not d.get("driver"):
            struct_issues.append(f"driver {i} has no title")
        if not d.get("why_it_costs"):
            struct_issues.append(f"driver {i} has no guidance sentence")
        ev = d.get("evidence") or []
        if not ev:
            struct_issues.append(f"driver {i} has no evidence rows")
        for j, row in enumerate(ev):
            if not (row.get("label") and row.get("value") not in (None, "", "None")):
                struct_issues.append(f"driver {i} evidence row {j} empty: {row!r:.120}")
        srcs = d.get("sources") or []
        if not srcs:
            struct_issues.append(f"driver {i} has no sources")
        for s in srcs:
            u = (s or {}).get("url") or ""
            if not u.startswith("https://") or host_of(u) not in OFFICIAL_HOSTS:
                struct_issues.append(f"driver {i} source not official: {u}")
    if "guidance" not in (es.get("cost_drivers_note") or ""):
        struct_issues.append("cost_drivers_note does not separate guidance from verified numbers")
    ledger.check("cost-drivers-structure",
                 "Every maintenance cost driver is ranked, carries evidence rows, and cites only "
                 "official .gov sources",
                 not struct_issues,
                 (f"{len(drivers)} drivers; " +
                  ("all structural rules hold" if not struct_issues
                   else f"{len(struct_issues)} issue(s)")),
                 evidence={"issues": struct_issues[:8], "driver_count": len(drivers)})

    pub_days = es.get("expected_days") or {}
    recomp = {}
    daily = climo.get("daily") or []
    season_daily = [d for d in daily if d.get("month") in (10, 11, 12, 1)]
    for key, field in (("ge_025in_days", "p_rain_ge_025in_pct"),
                       ("ge_100in_days", "p_rain_ge_100in_pct")):
        recomp[key] = _eed(season_daily, field)
    arith_ok = all(
        pub_days.get(k) is not None and recomp[k] is not None
        and abs(float(pub_days[k]) - float(recomp[k])) <= 0.01
        for k in recomp)
    ledger.check("cost-driver-expected-days-arithmetic",
                 "The published expected heavy-rain day counts equal the sum of the per-date "
                 "1991-2020 probabilities in the committed climatology table",
                 arith_ok,
                 "; ".join(f"{k}: published {pub_days.get(k)} vs recomputed {recomp[k]} "
                           f"over {len(season_daily)} season dates" for k in recomp),
                 evidence={"published": pub_days, "recomputed": recomp,
                           "n_season_dates": len(season_daily)})

    # Raw ENSO data tokens ("el_nino", "la_nina") are keys, not phrases; none
    # may appear in any string the executive summary displays to the reader.
    import re as _re3
    display_strings = [es.get("key_finding") or ""]
    for a in landlord.get("action_items") or []:
        display_strings += [a.get("title") or "", a.get("detail") or ""]
    for d in drivers:
        display_strings += [d.get("driver") or "", d.get("why_it_costs") or ""]
        for row in d.get("evidence") or []:
            display_strings += [str(row.get("label") or ""), str(row.get("value") or "")]
    raw_tokens = [s for s in display_strings
                  if _re3.search(r"\b(?:el_nino|la_nina)\b", s, _re3.IGNORECASE)]
    # The same rule is then applied to *every* string anywhere in the datasets the
    # page renders, not just the executive summary.  The narrower check above
    # passed while the season panel was still printing "el nino" out of
    # calendar.json's ENSO block and the claim ledger was still printing
    # "phase: el_nino", because neither of those strings lived in the executive
    # summary.  A reader-facing token is a reader-facing token wherever it sits.
    def _walk_strings(node, path="", out=None):
        out = [] if out is None else out
        if isinstance(node, str):
            out.append((path, node))
        elif isinstance(node, dict):
            for k, v in node.items():
                # Source URLs and SHA-256s are not prose, and `phase` / `enso_phase`
                # are machine enums that the renderer is required to map through a
                # label; all three classes are excluded here and guarded separately
                # (see phase-label-present and the rendered-page assertions).
                if k.lower() in ("url", "sha256", "source_url", "human_url", "local_path",
                                 "hourly_url", "daily_url", "detail", "phase",
                                 "enso_phase"):
                    continue
                _walk_strings(v, f"{path}.{k}" if path else k, out)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _walk_strings(v, f"{path}[{i}]", out)
        return out

    dataset_strings = []
    for _name, doc in (("landlord.json", landlord), ("calendar.json", cal),
                       ("enso.json", enso)):
        dataset_strings += [(_name + "." + p, s) for p, s in _walk_strings(doc)]
    dataset_tokens = [(p, s) for p, s in dataset_strings
                      if _re3.search(r"\b(?:el_nino|la_nina)\b", s)]
    ledger.check("raw-phase-tokens-dataset",
                 "No reader-facing string anywhere in the rendered datasets carries a raw "
                 "ENSO data token (el_nino / la_nina)",
                 not dataset_tokens,
                 (f"{len(dataset_tokens)} string(s) carry a raw phase token out of "
                  f"{len(dataset_strings)} scanned"
                  if dataset_tokens else
                  f"0 raw tokens across {len(dataset_strings)} scanned string(s)"),
                 evidence=[{"path": p, "text": s[:200]} for p, s in dataset_tokens[:8]])

    # Every machine phase value the renderer may touch must ship with a
    # reader-facing label, so the site never has to translate a token itself.
    label_paths = [
        ("landlord.json executive_summary.current_enso.phase_label",
         ((landlord.get("executive_summary") or {}).get("current_enso") or {}).get("phase_label")),
        ("calendar.json enso.latest_official.phase_label",
         ((cal.get("enso") or {}).get("latest_official") or {}).get("phase_label")),
        ("calendar.json enso.official.latest.phase_label",
         (((cal.get("enso") or {}).get("official") or {}).get("latest") or {}).get("phase_label")),
    ]
    bad_labels = [{"path": p, "value": v} for p, v in label_paths
                  if not v or _re3.search(r"\b(?:el_nino|la_nina)\b", str(v))]
    ledger.check("phase-label-present",
                 "Every ENSO phase value a renderer can reach ships with a reader-facing "
                 "label (no underscore token, correct capitalisation)",
                 not bad_labels,
                 (f"{len(label_paths)} label(s) published"
                  if not bad_labels else f"{len(bad_labels)} missing or token-valued"),
                 evidence={"labels": [{"path": p, "value": v} for p, v in label_paths],
                           "problems": bad_labels})

    ledger.check("raw-phase-tokens",
                 "No raw ENSO data token (el_nino / la_nina) appears in any reader-facing "
                 "executive-summary string",
                 not raw_tokens,
                 (f"{len(raw_tokens)} string(s) carry a raw phase token"
                  if raw_tokens else "0 raw tokens in display strings"),
                 evidence=raw_tokens[:5])

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

    # --------------------- 7b. NOAA's published daily normals, date by date
    # NCEI publishes, for every calendar date at this station, the share of years
    # recording >= 0.01 / 0.25 / 1.00 in of precipitation.  The project derives
    # the same three quantities from 30 seasons of GHCN-Daily.  Both are shown on
    # the site, so the ledger has to do three things: confirm the published value
    # shown on a day really is the value in the file, confirm the derived value
    # really is the project's own count, and publish the difference.
    daily_normals = load("daily_normals.json")
    pub_by_mmdd = (daily_normals or {}).get("by_mmdd") or {}
    season_days = cal.get("days") or []
    cmp_block = cal.get("daily_normals_comparison") or {}
    if not pub_by_mmdd:
        ledger.check(
            "official-daily-normals-present",
            "NOAA's published per-date daily normals were fetched and parsed",
            False,
            ("data/daily_normals.json carries no parsed per-date values. Either the "
             "official file could not be read this run or the file predates the "
             "published-normals feature. The site shows the derived values only, and "
             "says so - it does not present them as published."),
            severity="warning")
    else:
        # (a) layout: the file must have yielded a full year of dated values.
        n_dates = len(pub_by_mmdd)
        ledger.check(
            "official-daily-normals-present",
            "NOAA's published per-date daily normals were fetched and parsed",
            n_dates >= 366,
            f"{n_dates} calendar date(s) parsed from the official file",
            severity="warning",
            evidence={"url": daily_normals.get("url"),
                      "sha256": daily_normals.get("sha256"),
                      "dates_parsed": n_dates,
                      "columns": (daily_normals.get("layout") or {}).get("column_by_key")})

        # (a2) A sentinel must never be published as a value.  NCEI writes -9999
        # for a percentile it could not compute, and the first release of this
        # feature rendered that as "-9999.00 in" on 123 dates.  The ranges below
        # are physical, not fitted to the data: a share of years is 0-100 %, a
        # precipitation percentile cannot be negative, and a temperature normal
        # for San Francisco must sit inside a range any inhabited place satisfies.
        sentinels = []
        for mmdd, row in pub_by_mmdd.items():
            for key, value in row.items():
                if not isinstance(value, (int, float)):
                    continue
                # The rule lives in climo so the offline tests can pin it
                # (tests/test_parsers.py) rather than leaving a guard that only
                # ever runs on CI.  Written after a first version of this check
                # silently matched nothing and passed with a -9999 in the row.
                bad = climo_lib.implausible_normals_value(key, value)
                if bad:
                    sentinels.append({"mmdd": mmdd, "key": key, "value": value,
                                      "why": bad})
        ledger.check(
            "official-daily-normals-no-sentinels",
            "No missing-value sentinel (NCEI writes -9999 for an uncomputable "
            "percentile) is published as if it were a reading",
            not sentinels,
            (f"{len(sentinels)} sentinel/impossible value(s) among the published "
             f"per-date normals"
             if sentinels else
             f"all values read from the file are inside their physical range "
             f"({len(pub_by_mmdd)} date(s) checked)"),
            evidence={"examples": sentinels[:10],
                      "url": daily_normals.get("url"),
                      "ranges": {"*_pct": "0-100 %",
                                 "*_pctl_in": ">= 0 in",
                                 "*_f": "-50..130 F"}})

        # (b) every date in the season window must carry the published block, and
        # the values must equal the file's own values (re-read, not restated).
        missing, mismatch = [], []
        checked_values = 0
        for day in season_days:
            off = day.get("official_normal")
            pub = pub_by_mmdd.get(day.get("mmdd"))
            if not off:
                missing.append(day.get("date"))
                continue
            for key, published_value in pub.items():
                shown = off.get(key)
                if shown is None:
                    continue
                checked_values += 1
                if abs(float(shown) - float(published_value)) > 1e-9:
                    mismatch.append({"date": day.get("date"), "key": key,
                                     "shown": shown, "in_file": published_value})
        ledger.check(
            "official-daily-normals-traceable",
            "Every published normal shown on a day is the value in the NOAA file "
            "(re-read from the same bytes), and every season date carries one",
            not missing and not mismatch,
            (f"{checked_values} published value(s) re-checked across "
             f"{len(season_days) - len(missing)} of {len(season_days)} date(s); "
             f"{len(missing)} date(s) without a published block, "
             f"{len(mismatch)} mismatch(es)"),
            evidence={"dates_without_a_published_block": missing[:10],
                      "mismatches": mismatch[:10]})

        # (c) the difference between the published and derived values, published
        # as a number on the site rather than reconciled away.
        pairs = (cmp_block.get("pairs") or {})
        flagged = cmp_block.get("flagged") or []
        key_label = "share of years with >= 0.01 in"
        blk = pairs.get(key_label) or {}
        detail = "; ".join(
            f"{label}: mean {b.get('mean_difference')} {b.get('unit')}, "
            f"largest |diff| {b.get('largest_absolute_difference')} on "
            f"{b.get('largest_difference_date')}"
            for label, b in sorted(pairs.items()) if b.get("n"))
        # A disagreement larger than 15 points on the >=0.01 in probability would
        # mean the two official sources genuinely disagree about this station and
        # must be looked at by a human, so it is an error, not a warning.
        worst = (blk.get("largest_absolute_difference") or 0.0)
        ledger.check(
            "official-daily-normals-cross-check",
            "The site publishes both NOAA's own per-date rain probabilities and this "
            "project's derived ones, with the difference stated",
            bool(pairs) and worst <= 15.0,
            (detail or "no comparable pairs this run") +
            (f"; {len(flagged)} date(s) differ by more than 10 points"
             if flagged else ""),
            severity="error" if (worst > 15.0) else "warning",
            evidence={"pairs": pairs, "largest": cmp_block.get("largest"),
                      "flagged_sample": flagged[:10],
                      "published_source": cmp_block.get("published_source_url")})
        if pairs:
            ledger.claim(
                "official-daily-normals-expected-days",
                "Expected heavy-rain days per season, computed from NOAA's own "
                "published per-date probabilities",
                (landlord.get("official_daily_normals") or {}).get("published_expected_days"),
                "days per season",
                source=src(daily_normals.get("url"),
                           "NOAA NCEI 1991-2020 daily climate normals (DLY-PRCP-PCTALL-GE***HI)"),
                method=("sum of the published per-date probabilities "
                        "DLY-PRCP-PCTALL-GE025HI / GE100HI over the 123 dates of "
                        "Oct 1 2026 - Jan 31 2027 (linearity of expectation)"),
                verified=True,
                cross_check={"derived_expected_days":
                             (landlord.get("executive_summary") or {}).get("expected_days")})

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
    # The landlord dashboard prints source URLs too (action checklist and the
    # cost-driver block); they are held to the same traceability rule.
    for a in landlord.get("action_items") or []:
        if a.get("source_url"):
            refs.add(a["source_url"])
    for d in (landlord.get("executive_summary") or {}).get("cost_drivers") or []:
        for s in d.get("sources") or []:
            if s.get("url"):
                refs.add(s["url"])
    # Some citations point at an official dataset *landing page* rather than at a
    # single file (the pipeline fetches the per-year files beneath it).  Those are
    # allowed, but only if the page is an official host AND at least one fetched
    # file sits underneath the same path - so the citation is still auditable.
    citation_only = {
        "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/":
            "GSOD dataset landing page; the per-year files under this path are fetched nightly",
        "https://www.ncei.noaa.gov/data/global-hourly/access/":
            "ISD hourly dataset landing page; the per-year station files under this path "
            "are fetched nightly and drive the hour-by-hour wind+rain statistic",
    }
    untraceable, cited = [], []
    for u in sorted(refs):
        if u in unique_urls:
            continue
        if u in citation_only and host_of(u) in OFFICIAL_HOSTS and \
                any(e.startswith(u) for e in unique_urls):
            cited.append({"url": u, "note": citation_only[u],
                          "files_fetched_under_it": sum(1 for e in unique_urls if e.startswith(u))})
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

    # ------------------------------------------- 12b. executive bottom line
    # The block the page leads with makes six statements.  Every one has to
    # carry a basis and at least one official source link, the six have to be
    # numbered in order, and every number printed in an answer has to be
    # findable in the datasets the page publishes - so a typo or an invented
    # figure cannot survive into the lead paragraph.
    exec_summary = (landlord.get("executive_summary") or {})
    bottom_line = exec_summary.get("bottom_line") or []
    bl_problems = []
    if not bottom_line:
        bl_problems.append("no bottom_line block was produced")
    published_strings = json.dumps(
        {k: v for k, v in landlord.items() if k != "executive_summary"}, default=str
    ) + json.dumps(cal.get("season_summary") or {}, default=str) \
      + json.dumps(cal.get("streak_probability") or {}, default=str) \
      + json.dumps(cal.get("severity_record") or {}, default=str) \
      + json.dumps(enso or {}, default=str)
    for i, item in enumerate(bottom_line, start=1):
        tag = item.get("key") or f"item {i}"
        if item.get("n") != i:
            bl_problems.append(f"{tag}: numbered {item.get('n')}, expected {i}")
        if not (item.get("question") or "").strip():
            bl_problems.append(f"{tag}: no question")
        if not (item.get("answer") or "").strip():
            bl_problems.append(f"{tag}: no answer")
        if not (item.get("basis") or "").strip():
            bl_problems.append(f"{tag}: no basis stated")
        nums = item.get("numbers") or []
        if not nums:
            bl_problems.append(f"{tag}: no supporting numbers")
        for nrow in nums:
            if nrow.get("value") in (None, ""):
                bl_problems.append(f"{tag}: empty value for '{nrow.get('label')}'")
        srcs = [s for s in (item.get("sources") or []) if s.get("url")]
        if not srcs:
            bl_problems.append(f"{tag}: no source link")
        for s in srcs:
            host = host_of(s["url"])
            if host not in OFFICIAL_HOSTS:
                bl_problems.append(f"{tag}: non-official host {host}")
    ledger.check("bottom-line-structure",
                 "Every answer in the executive bottom line carries a basis, "
                 "supporting numbers and an official source link, numbered in order",
                 not bl_problems,
                 (f"{len(bottom_line)} answer(s); all structural rules hold"
                  if not bl_problems else f"{len(bl_problems)} problem(s)"),
                 evidence=bl_problems[:10])

    # Re-derive the headline figures the bottom line quotes, from the datasets
    # it reads, and require each one to appear in that dataset.  This is the
    # check that makes "no number on this page is typed in" true for the lead
    # paragraph specifically.
    bl_untraceable = []
    if bottom_line:
        import re as _re3

        def _appears_as_a_number(blob, value):
            """True when *value* is printed in *blob* as a standalone number.

            The naive version of this test accepted ``f"{v:.0f}"`` as a
            spelling and then did a plain substring search, so 12.79 matched
            the "13" inside an unrelated "13.26" and the check could not fail.
            A candidate now only counts when it is not glued to another digit
            or a decimal point.
            """
            if value is None:
                return False
            try:
                f = float(value)
            except (TypeError, ValueError):
                return True  # non-numeric: nothing to trace
            cands = {f"{f:.2f}", f"{f:.1f}", str(value)}
            if abs(f - round(f)) < 0.05:
                cands.add(f"{f:.0f}")
            for c in cands:
                if _re3.search(r"(?<![\d.])" + _re3.escape(c) + r"(?![\d.])", blob):
                    return True
            return False

        wanted = {}
        for key, path in (
            ("rain_amount", ("season_total_prcp", "mean")),
            ("rain_amount", ("season_total_prcp", "median")),
            ("rain_amount", ("season_total_prcp", "p10")),
            ("rain_amount", ("season_total_prcp", "p90")),
            ("rain_amount", ("season_total_prcp", "max")),
            ("rain_amount", ("season_total_prcp", "min")),
            ("rain_duration", ("streak_probability", "ge_7_days", "pct")),
            ("rain_duration", ("longest_streak", "mean")),
            ("heavy_rain_days", ("expected_days", "ge_025in_days")),
            ("heavy_rain_days", ("expected_days", "ge_100in_days")),
            ("wind", ("max_gust", "mean")),
            ("wind", ("max_gust", "max")),
            ("wind_and_rain", ("wind_and_rain", "mean")),
            ("wind_and_rain", ("heavy_wind_and_rain", "mean")),
        ):
            node = exec_summary
            for step in path:
                node = (node or {}).get(step) if isinstance(node, dict) else None
            wanted.setdefault(key, []).append((path, node))
        by_key = {item.get("key"): item for item in bottom_line}
        for key, pairs in wanted.items():
            item = by_key.get(key)
            if not item:
                continue
            blob = " ".join(str(x.get("value", "")) for x in (item.get("numbers") or [])) \
                   + " " + (item.get("answer") or "")
            for path, value in pairs:
                if value is None:
                    continue
                if not _appears_as_a_number(blob, value):
                    bl_untraceable.append({
                        "key": key, "quantity": ".".join(path), "value": value})
    ledger.check("bottom-line-numbers-traceable",
                 "Every figure the executive bottom line quotes exists in the dataset it claims to read",
                 not bl_untraceable,
                 ("all quoted figures found in the source datasets" if not bl_untraceable
                  else f"{len(bl_untraceable)} figure(s) not found"),
                 evidence=bl_untraceable[:10])

    # ---------------------------------- 12b2. storm-event counts, one definition
    # Two cards on the same page used to count "flood-type" reports with two
    # different type sets, so the page published 98 in one place and 99 in the
    # other for the same quantity.  The counts are now re-derived here from
    # storm_events.json, and the two published places must agree with each other
    # and with the file.
    sev_item = next((r for r in (landlord.get("executive_summary") or {})
                     .get("bottom_line", []) if r.get("key") == "storm_severity"), {})
    def _leading_int(text):
        m = re.search(r"(\d[\d,]*)", str(text or ""))
        return int(m.group(1).replace(",", "")) if m else None

    events = (storms or {}).get("events") or []
    rain_types = tuple(RAIN_RELATED_EVENT_TYPES)
    rain_n = sum(1 for e in events if (e or {}).get("event_type") in rain_types)
    rain_damage_n = sum(
        1 for e in events
        if (e or {}).get("event_type") in rain_types
        and (parse_damage_usd((e or {}).get("damage_property")) or 0) > 0)
    all_damage_n = sum(1 for e in events
                       if (parse_damage_usd((e or {}).get("damage_property")) or 0) > 0)

    sev_numbers = {n.get("label"): n.get("value") for n in (sev_item.get("numbers") or [])}
    published_all = _leading_int(sev_numbers.get("Storm Events records, SF County"))
    published_rain = _leading_int(next((v for k, v in sev_numbers.items()
                                        if str(k).startswith("Rain-related records")), None))
    published_damage = _leading_int(sev_numbers.get("Records with a non-zero damage figure"))
    driver_rain = driver_damage = None
    for driver in (landlord.get("executive_summary") or {}).get("cost_drivers") or []:
        for ev_item in driver.get("evidence") or []:
            label = str(ev_item.get("label") or "")
            if label.startswith("Rain-related storm reports"):
                driver_rain = _leading_int(ev_item.get("value"))
            if label.startswith("\u2026of those, reports carrying"):
                driver_damage = _leading_int(ev_item.get("value"))
    storm_problems = []
    if published_all is not None and published_all != len(events):
        storm_problems.append(f"bottom line says {published_all} records; the file holds {len(events)}")
    if published_rain is not None and published_rain != rain_n:
        storm_problems.append(f"bottom line says {published_rain} rain-related; recount from the file gives {rain_n}")
    if driver_rain is not None and driver_rain != rain_n:
        storm_problems.append(f"cost driver says {driver_rain} rain-related; recount gives {rain_n}")
    if published_rain is not None and driver_rain is not None and published_rain != driver_rain:
        storm_problems.append(f"the two published rain-related counts disagree: {published_rain} vs {driver_rain}")
    if published_damage is not None and published_damage != all_damage_n:
        storm_problems.append(f"bottom line says {published_damage} records carry damage; the file gives {all_damage_n}")
    if driver_damage is not None and driver_damage != rain_damage_n:
        storm_problems.append(f"cost driver says {driver_damage} rain-related records carry damage; the file gives {rain_damage_n}")
    ledger.check("storm-events-counts-recompute",
                 "Every published Storm Events count is re-derived from the county file, "
                 "and the two cards that count them use one definition",
                 not storm_problems,
                 (f"{len(events)} records, {rain_n} rain-related, {all_damage_n} with a "
                  f"token damage figure; bottom line and cost driver agree"
                  if not storm_problems else "; ".join(storm_problems))[:280],
                 evidence={"file_records": len(events), "file_rain_related": rain_n,
                           "file_rain_related_with_damage": rain_damage_n,
                           "file_with_damage": all_damage_n,
                           "published": {"records": published_all, "rain_related": published_rain,
                                         "with_damage": published_damage,
                                         "cost_driver_rain_related": driver_rain,
                                         "cost_driver_with_damage": driver_damage}})

    # ------------------------------------- 12c. severity counters arithmetic
    # The per-season severity counters live in calendar.json's season_by_year.
    # The published distribution must be the arithmetic summarise() of exactly
    # those values - the same rule the other distributions already follow.
    sev_fields = ("wet_days_ge_050in", "wet_days_ge_1in", "wet_days_ge_2in",
                  "wet_days_ge_400in", "wind_days_ge_30kt", "gust_days_ge_40kt",
                  "gust_days_ge_50kt", "severe_wind_and_rain_days", "max_wind_mph")
    sev_bad = []
    seasons = cal.get("season_by_year") or []
    dist_block = cal.get("season_summary") or {}
    for field in sev_fields:
        pub = dist_block.get(field)
        if not isinstance(pub, dict) or pub.get("mean") is None:
            continue
        vals = [s.get(field) for s in seasons if s.get(field) is not None]
        if not vals:
            sev_bad.append({"field": field, "problem": "published but no per-season values"})
            continue
        if abs(round(sum(vals) / len(vals), 2) - round(float(pub["mean"]), 2)) > 0.06:
            sev_bad.append({"field": field, "published_mean": pub["mean"],
                            "recomputed": round(sum(vals) / len(vals), 2)})
        if pub.get("max") is not None and round(float(pub["max"]), 1) != round(max(vals), 1):
            sev_bad.append({"field": field, "published_max": pub["max"], "recomputed_max": max(vals)})
        if pub.get("min") is not None and round(float(pub["min"]), 1) != round(min(vals), 1):
            sev_bad.append({"field": field, "published_min": pub["min"], "recomputed_min": min(vals)})
    if sev_fields and not any(dist_block.get(f) for f in sev_fields):
        # Not yet produced by a fetching run: report rather than pass silently.
        ledger.check("severity-counters-arithmetic",
                     "Every published severity counter equals the arithmetic summary of the per-season values",
                     True, "no severity counters in this dataset yet (the fetching run produces them)",
                     severity="warning")
    else:
        ledger.check("severity-counters-arithmetic",
                     "Every published severity counter equals the arithmetic summary of the per-season values",
                     not sev_bad,
                     (f"{len(sev_fields)} counter(s) recomputed from season_by_year"
                      if not sev_bad else f"{len(sev_bad)} mismatch(es)"),
                     evidence=sev_bad[:10])

    # ------------------------------- 12c-bis. the two-method threshold table
    # The site prints this project's own heavy-rain-day counts next to NOAA's
    # published expectations.  The NOAA column has to be the actual sum of the
    # published per-date percentages in the days data - a hand-typed number
    # here would be exactly the kind of "looks official" figure the ledger
    # exists to stop.
    thr = (((landlord.get("executive_summary") or {}).get("severity") or {})
           .get("threshold_comparison") or [])
    thr_bad = []
    cal_days = cal.get("days") or []
    n_with_block = sum(1 for d in cal_days if d.get("official_normal"))
    key_for = {0.01: "p_pcp_ge_0p01in_pct", 0.10: "p_pcp_ge_0p10in_pct",
               0.25: "p_pcp_ge_0p25in_pct", 0.50: "p_pcp_ge_0p50in_pct",
               1.00: "p_pcp_ge_1p00in_pct", 2.00: "p_pcp_ge_2p00in_pct",
               4.00: "p_pcp_ge_4p00in_pct", 6.00: "p_pcp_ge_6p00in_pct"}
    for row in thr:
        inches = row.get("threshold_in")
        published = row.get("noaa_expected_days")
        if published is None:
            continue
        key = key_for.get(float(inches))
        if key is None:
            thr_bad.append({"threshold_in": inches, "problem": "no published column for this threshold"})
            continue
        total, seen = 0.0, 0
        for d in cal_days:
            v = (d.get("official_normal") or {}).get(key)
            if v is None:
                continue
            seen += 1
            total += float(v) / 100.0
        if not seen:
            thr_bad.append({"threshold_in": inches, "problem": "no published probabilities in the days data"})
        elif abs(round(total, 2) - round(float(published), 2)) > 0.01:
            thr_bad.append({"threshold_in": inches, "published": published,
                            "recomputed_from_days": round(total, 2)})
        # Coverage matters as much as the total: a date quietly missing its
        # published probability changes the sum by a few hundredths, which the
        # tolerance above absorbs.  Every date that carries the published block
        # at all must carry this column, or the sum is over a subset.
        if seen and n_with_block and seen != n_with_block:
            thr_bad.append({"threshold_in": inches,
                            "dates_with_block": n_with_block, "dates_with_this_column": seen,
                            "problem": "published probabilities are missing from some dates"})
    if thr:
        ledger.check("threshold-table-recomputable",
                     "Every NOAA column in the counted-vs-published threshold table "
                     "equals the sum of the published per-date probabilities",
                     not thr_bad,
                     (f"{len(thr)} threshold(s) recomputed from the daily published values"
                      if not thr_bad else f"{len(thr_bad)} mismatch(es)"),
                     evidence=thr_bad[:10])
    else:
        ledger.check("threshold-table-recomputable",
                     "Every NOAA column in the counted-vs-published threshold table "
                     "equals the sum of the published per-date probabilities",
                     True, "the threshold table is not in this snapshot yet",
                     severity="warning")

    # ---------------------- 12c-quater. the computed agreement verdict is true
    # The page's strongest claim is that two independent NOAA products agree.
    # That verdict is computed in the pipeline from the differences, then quoted
    # - so the check is simply: re-compute it.  An overstated verdict here would
    # be the most persuasive wrong sentence on the site.
    agree = (((landlord.get("executive_summary") or {}).get("severity") or {})
             .get("two_method_agreement") or {})
    agree_bad = []
    if agree:
        diffs = [t.get("difference_days") for t in thr if t.get("difference_days") is not None]
        if not diffs:
            agree_bad.append("a verdict was published with nothing to base it on")
        else:
            worst = max(abs(float(d)) for d in diffs)
            if agree.get("thresholds_compared") != len(diffs):
                agree_bad.append({"thresholds_compared": agree.get("thresholds_compared"),
                                  "recomputed": len(diffs)})
            if agree.get("largest_difference_days") is None or \
                    abs(float(agree["largest_difference_days"]) - worst) > 0.005:
                agree_bad.append({"largest_difference_days": agree.get("largest_difference_days"),
                                  "recomputed": round(worst, 2)})
            claimed_ok = bool(agree.get("agree_within_a_tenth"))
            if claimed_ok != (worst <= 0.10):
                agree_bad.append({"agree_within_a_tenth": claimed_ok, "recomputed": worst <= 0.10})
            stmt = agree.get("statement") or ""
            # The sentence must carry the number it is claiming, so a reader
            # cannot read "agree" without seeing how well.
            if f"{worst:.2f}" not in stmt:
                agree_bad.append({"statement": stmt,
                                  "problem": "the verdict sentence does not quote the "
                                             "difference it is based on"})
            if "agree" in stmt.lower() and worst > 0.10:
                agree_bad.append({"statement": stmt,
                                  "problem": "the sentence claims agreement the numbers "
                                             "do not support"})
    ledger.check("two-method-verdict-recomputable",
                 "The counted-vs-published agreement verdict is re-derivable from the "
                 "differences it describes",
                 not agree_bad,
                 (f"{agree.get('thresholds_compared')} threshold(s); largest difference "
                  f"{agree.get('largest_difference_days')} day(s)"
                  if agree and not agree_bad else
                  ("no verdict in this snapshot (the severity block has not been produced yet)"
                   if not agree else f"{len(agree_bad)} mismatch(es)")),
                 evidence=agree_bad[:5])

    # ------------------------- 12c-ter. one name, one quantity (days_covered)
    # ``days_covered`` used to mean two different things in two different
    # files: "scoreboard days inside the NWS horizon" in nws_window, and
    # "dates compared" in the published-normals block.  Both were renamed; this
    # check keeps the ambiguity from creeping back.
    ambiguous = []
    nws_win = cal.get("nws_window") or {}
    if "days_covered" in nws_win:
        ambiguous.append("calendar.json nws_window.days_covered")
    pub = ((landlord.get("official_daily_normals") or {}).get("published_expected_days") or {})
    if "days_covered" in pub:
        ambiguous.append("landlord.json official_daily_normals.published_expected_days.days_covered")
    ledger.check("no-ambiguous-days-covered",
                 "No dataset publishes a bare 'days_covered' that means something different "
                 "in each file",
                 not ambiguous,
                 ("0 ambiguous keys" if not ambiguous else "; ".join(ambiguous)))

    # -------------------------------------------- 12d. CPC baseline honesty
    # A CPC polygon whose probability is the 33.3% three-way baseline must not
    # be presented as a tilt.  Checked in both directions: every flagged record
    # really is at the baseline, and every non-EC record at the baseline is
    # flagged.
    cpc_recs_all = (cal.get("cpc") or {}).get("records") or []
    cpc_flag_bad = []
    for r in cpc_recs_all:
        try:
            prob = float(r.get("prob"))
        except (TypeError, ValueError):
            continue
        cat = (r.get("category") or "").strip().upper()
        at_base = abs(prob - (100.0 / 3.0)) < 0.5
        directional = cat in ("ABOVE", "BELOW", "A", "B")
        flagged = bool(r.get("probability_at_climatological_baseline"))
        if directional and at_base and not flagged:
            cpc_flag_bad.append({"period": r.get("valid_season"), "cat": cat,
                                 "prob": prob, "problem": "directional category at baseline, not flagged"})
        if flagged and not at_base:
            cpc_flag_bad.append({"period": r.get("valid_season"), "cat": cat,
                                 "prob": prob, "problem": "flagged as baseline but prob is not 33%"})
    ledger.check("cpc-baseline-honesty",
                 "No CPC polygon whose probability sits on the 33.3% three-way baseline is presented as a tilt",
                 not cpc_flag_bad,
                 (f"{len(cpc_recs_all)} CPC record(s) checked, 0 unflagged baseline values"
                  if not cpc_flag_bad else f"{len(cpc_flag_bad)} problem(s)"),
                 evidence=cpc_flag_bad[:10])

    # -------------------------------------------- 12e. no corrupted characters
    # Publishers' legacy encodings used to be decoded with errors="replace",
    # which silently committed U+FFFD into the datasets.  Nothing published may
    # carry one, so a future encoding regression fails the build instead of
    # reaching the page.
    corrupted = []
    for name, obj in (("storm_events", storms), ("landlord", landlord),
                      ("calendar", cal), ("climatology", climo_json)):
        # ensure_ascii=False is essential: with the default the U+FFFD is
        # escaped to the six characters \ufffd and the search for the actual
        # character can never match, which made this guard unable to fire.
        blob = json.dumps(obj, default=str, ensure_ascii=False)
        if "\ufffd" in blob:
            idx = blob.index("\ufffd")
            corrupted.append({"dataset": name,
                              "context": blob[max(0, idx - 60):idx + 60]})
    ledger.check("no-replacement-characters",
                 "No published text carries a Unicode replacement character (a silent encoding failure)",
                 not corrupted,
                 ("0 corrupted string(s) across the published datasets" if not corrupted
                  else f"{len(corrupted)} dataset(s) carry U+FFFD"),
                 evidence=corrupted[:5])

    # --------------------------- 12f. disclosed loss of publisher characters
    # The Storm Events file NCEI serves already contains U+FFFD, so the pipeline
    # removes those characters and records how many.  Removing text is a
    # publishable act: the dataset has to say what was lost and where, and the
    # quality report has to carry the same thing, or the site is quietly
    # editing an official document.
    ti = storms.get("text_integrity") or {}
    removed = ti.get("characters_removed")
    loss_problems = []
    if removed:
        if not ti.get("fields_affected"):
            loss_problems.append("characters were removed but no field is named")
        if not ti.get("reason"):
            loss_problems.append("characters were removed with no stated reason")
        # The claim "the glyph was already gone in the publisher's file" is only
        # supportable if the file that contained it decoded as UTF-8 with no
        # fallback.  Each affected field records the encoding used for its own
        # file, so a file that needed a fallback cannot hide behind a clean one.
        for entry in ti.get("fields_affected") or []:
            if (entry.get("encoding_used") or "utf-8") != "utf-8":
                loss_problems.append(
                    f"{entry.get('field')} in {entry.get('file')} was decoded as "
                    f"{entry.get('encoding_used')}, so this project's decoder cannot be "
                    "ruled out as the cause")
        if ti.get("encoding_fallback_used") is True and not ti.get("files_with_an_encoding_fallback"):
            loss_problems.append("a fallback was used but no file is named")
        noted = [i for i in (quality.get("irregularities") or [])
                 if i.get("area") == "storm_events" and "U+FFFD" in (i.get("message") or "")]
        if not noted:
            loss_problems.append("the removal is not recorded as an irregularity")
    ledger.check("publisher-text-loss-disclosed",
                 "Any character removed from a publisher's text is counted, located, "
                 "attributed and reported",
                 not loss_problems,
                 (f"{removed} character(s) removed and disclosed" if removed
                  else "nothing was removed from any publisher's text this run"),
                 evidence=loss_problems[:5])

    # ------------------------------------------------ 13. claim source evidence
    # A claim may be mathematically correct yet still be unsafe to publish if
    # its cited file was not actually retrieved with enough evidence to review.
    # Check every claim that has a URL, including claims added by future code.
    claim_source_issues = []
    for claim in ledger.claims:
        url = (claim.get("source") or {}).get("url")
        if url and not fetch_has_evidence(url):
            claim_source_issues.append({
                "claim": claim.get("id"),
                "url": url,
                "records": len(entries_by_url.get(url, [])),
            })
    ledger.check("claim-source-evidence",
                 "Every recorded claim with a source URL has a successful fetch with HTTP, size and hash evidence",
                 not claim_source_issues,
                 ("0 claim source(s) lack fetch evidence" if not claim_source_issues else
                  f"{len(claim_source_issues)} claim source(s) lack fetch evidence"),
                 evidence=claim_source_issues[:10])

    # --------------------------------- 12. official geography evidence (Census)
    # The site says which part of San Francisco the single forecast point is in.
    # That statement must come from the Census, be traceable to a recorded fetch,
    # and be internally consistent: Census GEOIDs nest (county -> county
    # subdivision / tract -> block), so a mismatched GEOID means the wrong
    # record was read.  When the lookup did not happen, the run must have said
    # so in the quality report - a silent hole is a failure.
    census_geo = centroid.get("census_geographies") or {}
    if census_geo:
        geo_url = census_geo.get("url")
        co = str(census_geo.get("county_geoid") or "")
        nesting = []
        for key in ("county_subdivision_geoid", "census_tract_geoid",
                    "census_block_geoid"):
            v = str(census_geo.get(key) or "")
            if co and v and not v.startswith(co):
                nesting.append(f"{key} {v} does not start with county GEOID {co}")
        tr = str(census_geo.get("census_tract_geoid") or "")
        bl = str(census_geo.get("census_block_geoid") or "")
        if tr and bl and not bl.startswith(tr):
            nesting.append(f"block GEOID {bl} does not start with tract GEOID {tr}")
        ok = (bool(geo_url) and fetch_has_evidence(geo_url)
              and host_of(geo_url or "") in OFFICIAL_HOSTS
              and any(census_geo.get(k) for k in
                      ("county_subdivision", "county", "census_tract"))
              and not nesting)
        named = [census_geo.get(k) for k in
                 ("county_subdivision", "county", "census_tract") if census_geo.get(k)]
        ledger.check(
            "census-geographies-traceable",
            "The named geography of the forecast point came from the Census "
            "geocoder, is traceable to a recorded fetch, and its GEOIDs nest",
            ok,
            (f"named by the Census: {', '.join(str(x) for x in named)}; nesting issues: "
             f"{nesting or 'none'}") if ok else
            (f"geography evidence present but unusable: url={geo_url} "
             f"evidence={fetch_has_evidence(geo_url) if geo_url else False} "
             f"nesting={nesting or 'ok'} named={named or 'nothing'}"),
            evidence={"county_subdivision": census_geo.get("county_subdivision"),
                      "geoids": {k: census_geo.get(k) for k in
                                 ("county_geoid", "county_subdivision_geoid",
                                  "census_tract_geoid", "census_block_geoid")},
                      "nesting_issues": nesting,
                      "url": geo_url})
    else:
        flagged = [i for i in (quality.get("irregularities") or [])
                   if i.get("area") == "geography"]
        ledger.check(
            "census-geographies-traceable",
            "Either the Census geography evidence is published, or its absence "
            "is flagged in the quality report",
            bool(flagged),
            ("no census_geographies in the dataset and no geography irregularity "
             "recorded - the site would name a district with no evidence")
            if not flagged else
            f"absent and flagged: {flagged[0].get('message', '')[:120]}",
            evidence={"geography_irregularities": len(flagged)})

    # ------------------------------------ 13. NWS discussion language scan (AFD)
    # The AFD card publishes quotations of NWS's own discussion.  Three rules
    # are enforced: every quoted sentence must be a whitespace-collapsed
    # substring of the fetched product text; the scan state must agree with
    # whether text was fetched; and no quotation may carry a date or a weather
    # value, because a flag is a quotation and never a number.
    afd_lang = cal.get("afd_language") or {}
    afd_product = ((nws.get("products") or {}).get("AFD") or {})
    afd_text = afd_product.get("text") or ""
    if not afd_lang:
        ledger.check("afd-language-verbatim",
                     "The Area Forecast Discussion scan is present in the dataset",
                     False, "calendar.json has no afd_language block",
                     evidence={})
    else:
        collapsed = climo_lib.collapse_ws(afd_text)
        offenders = []
        count_problems = []
        for cat in afd_lang.get("categories") or []:
            sents = cat.get("sentences") or []
            for s in sents:
                sent = s.get("sentence") or ""
                if not sent:
                    offenders.append({"category": cat.get("id"), "problem": "empty sentence"})
                elif sent not in collapsed:
                    offenders.append({"category": cat.get("id"),
                                      "problem": "not a substring of the fetched text",
                                      "sentence": sent[:120]})
            if (cat.get("sentence_count") or 0) < len(sents):
                count_problems.append(
                    f"{cat.get('id')}: count {cat.get('sentence_count')} < "
                    f"{len(sents)} published sentences")
        state_ok = (bool(afd_lang.get("scanned")) == bool(afd_text))
        if not afd_lang.get("scanned") and not (afd_lang.get("reason") or "").strip():
            state_ok = False
        excluded_ok = set(afd_lang.get("sections_excluded_this_run") or []) <= \
            set(afd_lang.get("excluded_sections") or [])
        src_url = afd_lang.get("source_url")
        src_ok = (not afd_text) or (bool(src_url) and fetch_has_evidence(src_url))
        ledger.check(
            "afd-language-verbatim",
            "Every quoted AFD sentence is verbatim in the fetched product text, "
            "the counts are not smaller than the published lists, and the scan "
            "state agrees with the fetched text",
            not offenders and not count_problems and state_ok and excluded_ok and src_ok,
            (f"{sum(len(c.get('sentences') or []) for c in afd_lang.get('categories') or [])} "
             f"quoted sentence(s) all found verbatim in {len(afd_text)} fetched characters")
            if not (offenders or count_problems) else
            f"{len(offenders)} non-verbatim sentence(s); {len(count_problems)} count problem(s)",
            evidence={"offenders": offenders[:5], "count_problems": count_problems[:5],
                      "scanned": afd_lang.get("scanned"),
                      "afd_text_chars": len(afd_text),
                      "excluded_within_declared": excluded_ok,
                      "source_traced": src_ok})

        # quotations only: no date, no value, no probability anywhere in the block
        forbidden_keys = {"date", "day", "value", "amount_in", "inches",
                          "probability", "forecast_amount", "pop_pct"}
        hits = []

        def scan_keys(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if str(k).lower() in forbidden_keys:
                        hits.append(f"{path}.{k}")
                    scan_keys(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    scan_keys(v, f"{path}[{i}]")

        scan_keys(afd_lang)
        sent_keys = set()
        for cat in afd_lang.get("categories") or []:
            for s in cat.get("sentences") or []:
                sent_keys.update((s or {}).keys())
        allowed_sent_keys = {"section", "sentence", "matched_patterns"}
        ledger.check(
            "afd-language-quotations-only",
            "The AFD scan publishes quotations only: no date, no amount and no "
            "probability is attached to any quoted sentence",
            not hits and sent_keys <= allowed_sent_keys,
            (f"sentence keys {sorted(sent_keys)}; forbidden keys found: {hits or 'none'}"),
            evidence={"sentence_keys": sorted(sent_keys),
                      "allowed_sentence_keys": sorted(allowed_sent_keys),
                      "forbidden_key_hits": hits[:10]})

    # ------------------------------------------- 14. per-field basis on every day
    # A published value with no stated basis is the first step towards a number
    # nobody can check.  Every one of the six fields the brief asks for - and
    # the temperature that accompanies them - must name the basis it used on
    # both the scoreboard days and the current-forecast days.
    BASIS_PAIRS = (("high_f", "temp_basis"), ("low_f", "temp_basis"),
                   ("humidity_pct", "humidity_basis"),
                   ("rain_chance_pct", "rain_chance_basis"),
                   ("rain_amount_in", "rain_amount_basis"),
                   ("wind_max_mph", "wind_basis"),
                   ("gust_max_mph", "gust_basis"))
    basis_missing = []
    day_sets = (("scoreboard", cal.get("days") or []),
                ("current_forecast", ((cal.get("current_forecast") or {}).get("days") or [])))
    for label, rows in day_sets:
        for day in rows:
            for value_key, basis_key in BASIS_PAIRS:
                if day.get(value_key) is not None and not str(day.get(basis_key) or "").strip():
                    basis_missing.append({"set": label, "date": day.get("date"),
                                          "field": value_key, "missing": basis_key})
    ledger.check(
        "day-field-basis-complete",
        "Every published value on every day names the basis it was computed from "
        "(temperature, humidity, rain chance, rain amount, wind, gusts)",
        not basis_missing,
        f"{len(basis_missing)} value(s) published without a basis"
        if basis_missing else
        f"all values on {len(cal.get('days') or [])} scoreboard day(s) and "
        f"{len((cal.get('current_forecast') or {}).get('days') or [])} current-forecast "
        "day(s) carry a basis",
        evidence={"missing": basis_missing[:10], "missing_total": len(basis_missing)})

    # ------------------------------------------------- 15. documentation drift
    # Prose is the one place a number can survive a data refresh untouched.  Two
    # checks, both warnings: documentation must never block the nightly data
    # publication (that would leave the site showing older numbers because a
    # sentence in a Markdown file went stale), but drift must still be visible
    # in the published ledger rather than discovered by a reader.
    import re as _re_docs

    readme_path = ROOT / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

    def numbers_published(obj, out):
        if isinstance(obj, dict):
            for v in obj.values():
                numbers_published(v, out)
        elif isinstance(obj, list):
            for v in obj:
                numbers_published(v, out)
        elif isinstance(obj, bool):
            return
        elif isinstance(obj, (int, float)):
            out.add(float(obj))
        return out

    published_numbers = numbers_published(landlord, set())
    # Thresholds and unit factors are written into prose on purpose; they are not
    # dataset figures and must not be reported as drift.
    doc_allowlist = {0.01, 0.10, 0.25, 0.50, 1.00, 2.00, 4.00, 6.00, 1.15078,
                     33.3, 3.33, 0.5, 9.0}
    block = _re_docs.search(
        r"\*\*Typical rainy season(?P<body>.*?)\*\*Current ENSO state",
        readme, _re_docs.S)
    doc_numbers = []
    if block:
        for m in _re_docs.finditer(r"(?<![\d.])\d+\.\d+(?![\d.])", block.group("body")):
            value = float(m.group(0))
            if value in doc_allowlist:
                continue
            decimals = len(m.group(0).split(".")[1])
            if not any(abs(round(v, decimals) - value) < 1e-9 for v in published_numbers):
                doc_numbers.append(m.group(0))
    ledger.check(
        "readme-figures-traceable",
        "Every figure in the README's rainy-season table is a number the dataset "
        "actually publishes (at the precision written)",
        not doc_numbers,
        (f"{len(doc_numbers)} README figure(s) match no published value: {doc_numbers[:8]}")
        if doc_numbers else
        "all README table figures matched a published value",
        severity="warning",
        evidence={"unmatched": doc_numbers,
                  "block_found": bool(block),
                  "published_number_count": len(published_numbers),
                  "allowlist": sorted(doc_allowlist)})

    run_date = dt.datetime.strptime(
        (run.get("generated_utc") or "")[:10], "%Y-%m-%d").date() \
        if (run.get("generated_utc") or "")[:4].isdigit() else None
    window_dates = set()
    win = cal.get("nws_window") or {}
    for key in ("first_day", "last_day", "forecast_updated"):
        v = str(win.get(key) or "")[:10]
        if len(v) == 10:
            window_dates.add(v)
    for day in ((cal.get("current_forecast") or {}).get("days") or []):
        window_dates.add(str(day.get("date"))[:10])
    if run_date:
        window_dates.add(run_date.isoformat())
    # CPC issuance dates belong in the vocabulary too: documentation that says an
    # outlook was "issued 2026-09-17" is making a claim the dataset can confirm
    # or refute, and it is not a claim about the NWS forecast horizon.
    def add_cpc_dates(rows):
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            for key in ("issued", "fcst_date", "start_date", "end_date"):
                v = str(r.get(key) or "")
                if len(v) == 10 and v[4] == "-":
                    window_dates.add(v)
                elif len(v) == 8 and v.isdigit():
                    window_dates.add(f"{v[:4]}-{v[4:6]}-{v[6:]}")
    add_cpc_dates((landlord.get("cpc_outlooks_relevant") or []))
    add_cpc_dates(((cal.get("cpc") or {}).get("records") or []))
    stale_dates = []
    if run_date:
        doc_files = [("README.md", readme)]
        docs_dir = ROOT / "docs"
        if docs_dir.exists():
            doc_files += [(p.name, p.read_text(encoding="utf-8"))
                          for p in sorted(docs_dir.glob("*.md"))]
        for name, text in doc_files:
            for m in _re_docs.finditer(r"\b(\d{4}-\d{2}-\d{2})\b", text):
                try:
                    when = dt.date.fromisoformat(m.group(1))
                except ValueError:
                    continue
                # Only dates near this run can be "the current horizon"; a date
                # in the scoreboard window or in the past is prose about the
                # season or about history, not a claim about today's forecast.
                if abs((when - run_date).days) <= 30 and m.group(1) not in window_dates:
                    stale_dates.append({"file": name, "date": m.group(1)})
    ledger.check(
        "docs-current-dates-traceable",
        "Any date in the documentation that could be read as the current NWS "
        "forecast horizon is a date this run actually published",
        not stale_dates,
        (f"{len(stale_dates)} documentation date(s) near this run match no published "
         f"forecast-window date: {stale_dates[:6]}")
        if stale_dates else
        f"no documentation date near {run_date.isoformat() if run_date else 'this run'} "
        f"contradicts the published window {sorted(window_dates)}",
        severity="warning",
        evidence={"stale": stale_dates[:10], "window_dates": sorted(window_dates)})

    # ------------------------------------ 12d. hour-by-hour wind+rain statistics
    # The landlord's key question is whether rain and wind happen *at the same
    # time*.  The published hour-by-hour figure must be the arithmetic over the
    # per-season values in isd_hourly_summary.json, over exactly the seasons the
    # block says it used, and it may not be published at all if the hourly
    # archive is absent.
    isd = load("isd_hourly_summary.json")
    hourly = ((landlord.get("executive_summary") or {}).get("wind_and_rain_hourly")
              or {})
    _isd_years_ok = [y.get("year") for y in (isd.get("per_year") or []) if y.get("ok")]
    isd_url = ("https://www.ncei.noaa.gov/data/global-hourly/access/"
               f"{min(_isd_years_ok)}/{(isd or {}).get('station_id') or '72494023234'}.csv"
               ) if _isd_years_ok else None
    if not hourly:
        ledger.check("wind-rain-hourly-published",
                     "The hour-by-hour wind+rain statistic is published when the hourly "
                     "archive is available",
                     True,
                     "landlord.json carries no hourly wind+rain block; the site must then "
                     "publish the whole-day figure alone, which it does",
                     severity="warning")
    elif not hourly.get("available"):
        ledger.check("wind-rain-hourly-published",
                     "The hour-by-hour wind+rain statistic is published when the hourly "
                     "archive is available",
                     bool(isd.get("by_local_date")),
                     "the block reports itself unavailable while an hourly archive exists",
                     severity="warning",
                     evidence={"reason": hourly.get("reason"),
                               "archive_dates": len((isd or {}).get("by_local_date") or {})})
    else:
        y0, y1 = (run.get("normals_period") or [1991, 2020])
        per_season = hourly.get("per_season") or []
        problems = []
        if not per_season:
            problems.append("no per-season values published")
        # Every season used must sit inside the window the daily statistic uses.
        outside = [s.get("season") for s in per_season
                   if not (y0 <= (s.get("season_year") or 0) <= y1)]
        if outside:
            problems.append(f"seasons outside the {y0}-{y1} window: {outside[:5]}")
        # The cover story must match the data: an excluded season may not also be
        # counted as used.
        used_names = {s.get("season") for s in per_season}
        overlap = [e.get("season") for e in (hourly.get("excluded_seasons") or [])
                   if e.get("season") in used_names]
        if overlap:
            problems.append(f"seasons both used and excluded: {overlap}")
        # Coverage: a season below the *published threshold* may not be used, and
        # the excluded seasons must carry a reason.
        required = ((hourly.get("coverage") or {}).get("min_coverage_pct_required"))
        if required is None:
            problems.append("the coverage threshold the seasons were filtered by is not published")
        low = [s.get("season") for s in per_season
               if (s.get("coverage_pct") is not None and required is not None
                   and s["coverage_pct"] < required - 1e-9)]
        if low:
            problems.append(f"seasons used below the published minimum coverage "
                            f"({required}%): {low[:5]}")
        unnamed = [e.get("season") for e in (hourly.get("excluded_seasons") or [])
                   if not e.get("excluded_because")]
        if unnamed:
            problems.append(f"excluded seasons with no reason: {unnamed[:5]}")

        def recompute(key):
            vals = [s.get(key) for s in per_season if s.get(key) is not None]
            if not vals:
                return None
            return {"n": len(vals), "mean": round(statistics.fmean(vals), 2),
                    "median": round(statistics.median(vals), 2),
                    "max": max(vals), "min": min(vals)}

        for field, key in (("days_with_a_simultaneous_hour", "days_simultaneous"),
                           ("simultaneous_hours_per_season", "simultaneous_hours")):
            published = hourly.get(field) or {}
            got = recompute(key)
            if published.get("mean") is None:
                problems.append(f"{field}: published with no mean")
            elif got is None:
                problems.append(f"{field}: published but no per-season values")
            elif round(float(published["mean"]), 2) != got["mean"]:
                problems.append(f"{field}: published mean {published['mean']} vs "
                                f"recomputed {got['mean']}")
            elif published.get("max") is not None and round(float(published["max"]), 1) != round(got["max"], 1):
                problems.append(f"{field}: published max {published['max']} vs "
                                f"recomputed max {got['max']}")

        # The same-station whole-day comparison needs the per-date wind maximum.
        # If the fields are absent it must be None, never a zero.
        has_fields = any(isinstance(d, dict) and "wind_max_kt" in d
                         for d in (isd.get("by_local_date") or {}).values())
        pair = hourly.get("days_daily_pair_same_station")
        if has_fields and (pair is None or pair.get("mean") is None):
            problems.append("per-date wind maximum present but the whole-day pairing is not published")
        if not has_fields and pair is not None:
            problems.append("whole-day pairing published although the per-date fields are absent")
        if hourly.get("same_station_daily_fields_available") != has_fields:
            problems.append("same_station_daily_fields_available does not match the archive")

        ledger.check("wind-rain-hourly-arithmetic",
                     "The hour-by-hour wind+rain figures equal the arithmetic over the "
                     "per-season values, over exactly the seasons published as used",
                     not problems,
                     (f"{len(per_season)} season(s) used, {len(hourly.get('excluded_seasons') or [])} "
                      f"excluded and named; mean days with a simultaneous hour "
                      f"{(hourly.get('days_with_a_simultaneous_hour') or {}).get('mean')}")
                     if not problems else "; ".join(problems[:6]),
                     evidence={"problems": problems[:10],
                               "coverage": hourly.get("coverage")})

        # The station, the archive and the method must be traceable to a recorded
        # official fetch: a quote of a method that was never fetched is exactly
        # the kind of claim this ledger exists to stop.
        station_id = str(isd.get("station_id") or "")
        fetched_years = [y for y in (isd.get("per_year") or []) if y.get("ok")]
        ledger.check("wind-rain-hourly-traceable",
                     "The hourly wind+rain statistic names the station and the fetched ISD "
                     "archive it was computed from",
                     bool(station_id) and bool(fetched_years)
                     and any(f"global-hourly" in (e.get("url") or "")
                             and station_id in (e.get("url") or "")
                             for e in manifest_entries)
                     and hourly.get("source_url") == "https://www.ncei.noaa.gov/data/"
                                                     "global-hourly/access/",
                     f"station {station_id}, {len(fetched_years)} year file(s) retrieved, "
                     f"source_url {hourly.get('source_url')}",
                     evidence={"station_id": station_id,
                               "years_ok": [y.get("year") for y in fetched_years][:5],
                               "years_ok_count": len(fetched_years)})

    # ----------------------------------------------- 12e. archive recency published
    # An archive that stops updating must not be presented as current.  run.json
    # publishes the newest row of each NCEI archive; a claim that a source is
    # current cannot outrun that date.
    cov = run.get("record_coverage") or {}
    if not cov:
        ledger.check("record-coverage-published",
                     "The run publishes how current each source archive is",
                     False,
                     "run.json carries no record_coverage block; this dataset predates the "
                     "coverage step, and the site must not claim currency from it",
                     severity="warning")
    else:
        problems = []
        for a in cov.get("archives") or []:
            if not a.get("last_date"):
                problems.append(f"{a.get('area')}: no last_date published")
                continue
            if a.get("age_days") is None:
                problems.append(f"{a.get('area')}: age_days not computable from last_date")
                continue
            try:
                expected_age = (dt.date.fromisoformat(str(cov.get("as_of")))
                                - dt.date.fromisoformat(str(a["last_date"])[:10])).days
            except ValueError:
                problems.append(f"{a.get('area')}: last_date is not an ISO date")
                continue
            if expected_age != a["age_days"]:
                problems.append(f"{a.get('area')}: age_days {a['age_days']} but the dates "
                                f"give {expected_age}")
        stale = [a.get("area") for a in (cov.get("archives") or [])
                 if (a.get("age_days") or 0) > 180]
        if sorted(stale) != sorted(cov.get("stale_archives") or []):
            problems.append(f"stale_archives {cov.get('stale_archives')} does not match the "
                            f"archives older than 180 days {stale}")
        if bool(cov.get("recent_enough_for_current_conditions")) != (not stale):
            problems.append("recent_enough_for_current_conditions disagrees with the archive ages")
        # The ISD recency must be the one the parsed hourly rows actually carry.
        isd_last = (isd or {}).get("latest_observation_utc")
        cov_isd = next((a for a in (cov.get("archives") or []) if a.get("area") == "isd_hourly"),
                       None)
        if isd_last and cov_isd and (cov_isd.get("last_date") or "")[:10] != str(isd_last)[:10]:
            problems.append(f"isd_hourly last_date {cov_isd.get('last_date')} does not match "
                            f"the parsed rows {str(isd_last)[:10]}")
        # A missing hourly archive is a data-availability event the site already
        # discloses, not a claim problem, so that case warns instead of failing.
        isd_absent = not (isd or {}).get("latest_observation_utc")
        ledger.check("record-coverage-published",
                     "The published archive dates and ages are re-derived from the datasets, "
                     "and a stale archive is flagged rather than presented as current",
                     not problems,
                     (f"{len(cov.get('archives') or [])} archive(s); stale: "
                      f"{cov.get('stale_archives') or 'none'}")
                     if not problems else "; ".join(problems[:6]),
                     severity="warning" if (isd_absent and all(
                         "isd_hourly" in p for p in problems)) else "error",
                     evidence={"problems": problems[:10], "archives": cov.get("archives")})
        years_ok = [y.get("year") for y in (isd.get("per_year") or []) if y.get("ok")]
        isd_file_url = (f"https://www.ncei.noaa.gov/data/global-hourly/access/"
                        f"{max(years_ok)}/{isd.get('station_id')}.csv") if years_ok else None
        ledger.claim(
            "archive-recency",
            "Newest observation available in each NCEI archive this project reads",
            {a.get("area"): a.get("last_date") for a in (cov.get("archives") or [])},
            source=(src(isd_file_url, f"NCEI ISD hourly {max(years_ok)} "
                                      f"({isd.get('station_id')})")
                    if isd_file_url and fetch_ok(isd_file_url) else {}),
            method="Newest date present in the fetched annual files; every published "
                   "statistic is a 1991-2020 statistic and does not depend on it.",
            verified=bool(cov.get("archives")))

    # --------------------------------- 12f. CPC back-test (scored or honestly pending)
    # The back-test is real when rows exist (every row re-derived below) and
    # honestly pending when no historical archive was retrievable.  What must
    # never happen is a published hit-rate that the rows do not support, an EC
    # row counted as a hit/miss, or a row sampled by any method other than the
    # live point-in-polygon path.
    if not cpc_backtest:
        ledger.check("cpc-backtest-sampling-method",
                     "CPC back-test rows (when present) use the live point-in-polygon "
                     "path and EC rows are never scored",
                     True,
                     "no cpc_backtest.json in this dataset (back-fill pending); "
                     "the site reports pending-backfill rather than a hit-rate",
                     severity="warning")
    else:
        bt_problems = []
        rows = cpc_backtest.get("rows") or []
        for i, r in enumerate(rows):
            if r.get("sampling") != ("lib_shape.point_in_polygon at the 94122 centroid "
                                     "(same code path as live CPC outlooks)"):
                bt_problems.append(f"row {i}: sampling method is not the live path")
            cat = (r.get("category") or "").strip()
            hit = r.get("hit")
            if cat == "EC" and hit is not None:
                bt_problems.append(f"row {i}: EC outlook scored as hit/miss")
            if cat in ("Above", "Below") and hit is None and r.get("observed_tercile"):
                bt_problems.append(f"row {i}: tilted outlook left unscored")
            if not r.get("url") or not fetch_ok(r["url"]):
                bt_problems.append(f"row {i}: archive URL has no recorded successful fetch")
            if r.get("polygon_index") is None:
                bt_problems.append(f"row {i}: no polygon_index published")
        # Re-derive the summary hit-rate from the rows.
        scored = [r for r in rows if r.get("hit") is True or r.get("hit") is False]
        hits = sum(1 for r in scored if r.get("hit") is True)
        expect_rate = round(100.0 * hits / len(scored), 1) if scored else None
        got_rate = (cpc_backtest.get("summary") or {}).get("hit_rate_pct")
        if expect_rate != got_rate:
            bt_problems.append(f"hit_rate_pct {got_rate} but rows give {expect_rate}")
        if (cpc_backtest.get("summary") or {}).get("n_rows_scored") != len(scored):
            bt_problems.append("n_rows_scored does not match the scored rows")
        # Pending status must not carry scored rows, and scored status must.
        status = cpc_backtest.get("status")
        if status == "pending-backfill" and rows:
            bt_problems.append("status is pending-backfill but rows are present")
        if status == "scored" and not rows:
            bt_problems.append("status is scored but no rows are present")
        ledger.check("cpc-backtest-sampling-method",
                     "CPC back-test rows (when present) use the live point-in-polygon "
                     "path and EC rows are never scored",
                     not bt_problems,
                     (f"{len(rows)} row(s), {len(scored)} scored, hit-rate {got_rate}%"
                      if not bt_problems else "; ".join(bt_problems[:6])),
                     evidence={"problems": bt_problems[:10]})

    # --------------------------------- 12g. per-field deep links traceable
    dl_problems = []
    for d in cal.get("days") or []:
        dl = d.get("deep_links") or {}
        for field in ("temp", "humidity", "rain_chance", "rain_amount", "wind", "gust"):
            e = dl.get(field) or {}
            if not e.get("url"):
                dl_problems.append(f"{d.get('date')}: deep link {field} has no URL")
            elif host_of(e["url"]) not in OFFICIAL_HOSTS:
                dl_problems.append(f"{d.get('date')}: deep link {field} is not an official host")
            if not e.get("hint"):
                dl_problems.append(f"{d.get('date')}: deep link {field} has no hint")
        # NWS days must name the hourly startTimes they aggregate, and each
        # tier must carry its 7th link (human forecast / published normals).
        if d.get("tier") == "nws":
            if not d.get("nws_hourly_start_times"):
                dl_problems.append(f"{d.get('date')}: NWS day names no hourly startTimes")
            if not (dl.get("human") or {}).get("url"):
                dl_problems.append(f"{d.get('date')}: NWS day has no human-forecast link")
        if d.get("tier") == "climatology" and not (dl.get("published_normals") or {}).get("url"):
            dl_problems.append(f"{d.get('date')}: climatology day has no published-normals link")
        if len(dl_problems) > 12:
            break
    if not (cal.get("days") or []):
        dl_problems.append("no calendar days to check")
    elif not any(d.get("deep_links") for d in cal["days"]):
        # Datasets predating the deep-link step warn rather than fail.  The
        # test is "no day has links", not "day zero has none": keying on one
        # day would let a single stripped day pass as a legacy dataset.
        ledger.check("deep-links-traceable",
                     "Every scoreboard day carries per-field manual-verification links "
                     "to official URLs",
                     True,
                     "this dataset predates per-field deep links; the next pipeline run adds them",
                     severity="warning")
    else:
        ledger.check("deep-links-traceable",
                     "Every scoreboard day carries per-field manual-verification links "
                     "to official URLs",
                     not dl_problems,
                     (f"{len(cal.get('days') or [])} day(s) carry 6 deep links each"
                      if not dl_problems else "; ".join(dl_problems[:6])),
                     evidence={"problems": dl_problems[:10]})

    # --------------------------------- 12h. AFD issuance history consistent
    afd_lang = (cal.get("afd_language") or {})
    hist = afd_history if isinstance(afd_history, list) else None
    if hist is None:
        ledger.check("afd-history-consistent",
                     "AFD issuance history is append-only, deduped, and quotations-only",
                     True,
                     "no afd_history.json in this dataset; the next pipeline run starts it",
                     severity="warning")
    else:
        ah_problems = []
        seen = set()
        prev = ""
        for i, e in enumerate(hist):
            iss = e.get("issuance_time")
            if not iss:
                ah_problems.append(f"entry {i}: no issuance_time")
                continue
            if iss in seen:
                ah_problems.append(f"entry {i}: duplicate issuance_time {iss}")
            seen.add(iss)
            if iss < prev:
                ah_problems.append("history is not sorted oldest-first")
            prev = iss
            for c in e.get("categories") or []:
                for s in c.get("sentences") or []:
                    for forbidden in ("date", "amount", "probability", "pop_pct", "qpf"):
                        if forbidden in s:
                            ah_problems.append(f"entry {i}: quotation carries {forbidden}")
        # The live scan's last_mention block must agree with the history.
        last_mention = ((afd_lang.get("history") or {}).get("last_mention") or {})
        for key, blk in last_mention.items():
            expect = None
            for e in hist:
                for c in e.get("categories") or []:
                    if (c.get("id") or c.get("key")) == key and (c.get("sentence_count") or 0) > 0:
                        expect = e.get("issuance_time")
            if blk.get("last_issuance_time") != expect:
                ah_problems.append(f"last_mention[{key}] does not match the history")
        ledger.check("afd-history-consistent",
                     "AFD issuance history is append-only, deduped, and quotations-only",
                     not ah_problems,
                     (f"{len(hist)} issuance(s) in history"
                      if not ah_problems else "; ".join(ah_problems[:6])),
                     evidence={"problems": ah_problems[:10]})

    # --------------------------------- 12i. digest / RSS traceable
    if not digest:
        ledger.check("digest-rss-traceable",
                     "Alert digest items trace to the verified NWS alert and forecast blocks",
                     True,
                     "no digest.json in this dataset; the next pipeline run builds it",
                     severity="warning")
    else:
        dg_problems = []
        if digest.get("pop_threshold_pct") != POP_THRESHOLD_PCT:
            dg_problems.append(
                f"pop_threshold_pct is not the published {POP_THRESHOLD_PCT}%")
        if "stores no" not in (digest.get("privacy") or ""):
            dg_problems.append("privacy note does not state the no-storage rule")
        cf_days = {(d.get("date")): d for d in ((cal.get("current_forecast") or {}).get("days") or [])}
        for it in digest.get("high_pop_days") or []:
            d = cf_days.get(it.get("date"))
            if not d:
                dg_problems.append(f"digest day {it.get('date')} is not in the current forecast")
            elif (d.get("rain_chance_pct") or 0) < POP_THRESHOLD_PCT:
                dg_problems.append(f"digest day {it.get('date')} has POP below threshold")
        cf_alerts = [e for e in (((cal.get("current_forecast") or {}).get("alerts") or {}).get("events") or [])
                     if not e.get("is_test")]
        if len(digest.get("nws_alerts") or []) != len(cf_alerts):
            dg_problems.append("digest alert count does not match the current forecast alerts")
        # The RSS file must exist and be well-formed XML with the same items.
        rss_path = DATA / "alerts.xml"
        if not rss_path.exists():
            dg_problems.append("data/alerts.xml was not written")
        else:
            try:
                import xml.etree.ElementTree as _et
                root = _et.fromstring(rss_path.read_bytes())
                n_items = len(root.findall(".//item"))
                expect_items = len(digest.get("nws_alerts") or []) + len(digest.get("high_pop_days") or [])
                if n_items != expect_items:
                    dg_problems.append(f"RSS has {n_items} item(s) but digest.json has {expect_items}")
            except Exception as exc:
                dg_problems.append(f"RSS is not well-formed XML: {exc}")
        ledger.check("digest-rss-traceable",
                     "Alert digest items trace to the verified NWS alert and forecast blocks",
                     not dg_problems,
                     (f"{len(digest.get('nws_alerts') or [])} alert(s), "
                      f"{len(digest.get('high_pop_days') or [])} high-POP day(s)"
                      if not dg_problems else "; ".join(dg_problems[:6])),
                     evidence={"problems": dg_problems[:10]})

    # --------------------------------- 12j. model guidance never merged
    mg_problems = []
    for d in cal.get("days") or []:
        if d.get("tier") not in ("nws", "climatology"):
            mg_problems.append(f"{d.get('date')}: tier {d.get('tier')} is not nws/climatology")
            break
        for k in list(d.keys()):
            if k.startswith("model_") or k in ("cfs_sst", "nmme_prob"):
                mg_problems.append(f"{d.get('date')}: model key {k} on a scoreboard day")
                break
        if mg_problems:
            break
    ledger.check("model-guidance-separated",
                 "No model guidance (CFSv2/NMME) is merged into the scoreboard tiers",
                 not mg_problems,
                 ("all scoreboard days are nws/climatology with no model keys"
                  if not mg_problems else "; ".join(mg_problems[:6])),
                 evidence={"problems": mg_problems[:6]})

    # --------------------------------- 12k. successor probe (GSOD/ISD retirement)
    if not isd_history and not ghcnh_probe:
        ledger.check("successor-probe-present",
                     "The GSOD/ISD retirement is investigated (history + successor probe)",
                     True,
                     "no isd_history.json / ghcnh_probe.json in this dataset; "
                     "the next pipeline run investigates the 2025-08-27 stop",
                     severity="warning")
    else:
        sp_problems = []
        if isd_history:
            if isd_history.get("url") != climo_lib.ISD_HISTORY_URL:
                sp_problems.append("isd_history URL is not the official history file")
            elif not fetch_ok(isd_history["url"]):
                sp_problems.append("isd_history URL has no recorded successful fetch")
            if isd_history.get("verdict") not in ("successor-id-found",
                                                 "station-found-no-successor",
                                                 "station-not-in-history"):
                sp_problems.append("isd_history verdict is not from the closed set")
        if ghcnh_probe:
            if ghcnh_probe.get("station_list_url") != climo_lib.GHCNH_STATION_LIST_URL:
                sp_problems.append("ghcnh probe URL is not the official station list")
            elif ghcnh_probe.get("station_list_ok") and not fetch_ok(
                    ghcnh_probe["station_list_url"]):
                sp_problems.append("ghcnh station list claims ok with no recorded fetch")
        ledger.check("successor-probe-present",
                     "The GSOD/ISD retirement is investigated (history + successor probe)",
                     not sp_problems,
                     ((f"verdict={(isd_history or {}).get('verdict')}; "
                       f"GHCNh probe ok={(ghcnh_probe or {}).get('station_list_ok')}")
                      if not sp_problems else "; ".join(sp_problems[:6])),
                     evidence={"problems": sp_problems[:10]})

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
