#!/usr/bin/env python3
"""Assemble the Oct 1 2026 - Jan 31 2027 day-by-day scoreboard.

Tiering rules - these are the anti-hallucination rules of the whole project:

1. ``nws``         - the day is inside the official NWS gridded forecast
                     horizon.  Temperature, humidity, wind, gusts, rain chance
                     and rain amount are the actual NWS numbers.
2. ``climatology`` - beyond the official forecast horizon.  Every number shown
                     is a 1991-2020 observed statistic for that calendar date
                     at the verified NCEI station, and is labelled as such.

CPC outlooks (6-10 day, 8-14 day, Week 3-4, monthly and 3-month seasonal) are
attached to the days they validly cover as *probability statements only* - they
never become made-up daily numbers.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "calendar.json"

# Test hook: SFWEATHER_DATA lets the builder be exercised against a fixture
# directory without touching the real datasets.
_env_dir = __import__("os").environ.get("SFWEATHER_DATA")
if _env_dir:
    DATA = Path(_env_dir)
    OUT = DATA / "calendar.json"

SEASON_START = dt.date(2026, 10, 1)
SEASON_END = dt.date(2027, 1, 31)
MM_PER_INCH = 25.4

MONTH_ABBR = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
              "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
MONTH_NAME = {v: k for k, v in MONTH_ABBR.items()}


def load(name):
    p = DATA / name
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def parse_wind(s):
    """NWS wind strings look like '8 mph' or '5 to 11 mph' -> take the max."""
    if not s:
        return None
    nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)", s)]
    return max(nums) if nums else None


def daily_from_hourly(periods, tz_name="America/Los_Angeles"):
    """Aggregate the NWS hourly gridded forecast into local calendar days."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
        tz_ok = True
    except Exception:  # noqa: BLE001
        tz = dt.timezone(dt.timedelta(hours=-8))
        tz_ok = False
    days = {}
    for p in periods:
        st = p.get("start_time")
        if not st:
            continue
        try:
            t = dt.datetime.fromisoformat(st.replace("Z", "+00:00"))
        except ValueError:
            continue
        key = t.astimezone(tz).date().isoformat()
        d = days.setdefault(key, {"temps": [], "rh": [], "wind": [], "gust": [],
                                  "pop": [], "qpf_mm": 0.0, "hours": 0, "qpf_known": False})
        d["hours"] += 1
        if p.get("temperature_f") is not None:
            d["temps"].append(p["temperature_f"])
        if p.get("rh_pct") is not None:
            d["rh"].append(p["rh_pct"])
        w = parse_wind(p.get("wind_speed"))
        if w is not None:
            d["wind"].append(w)
        g = parse_wind(p.get("wind_gust"))
        if g is not None:
            d["gust"].append(g)
        if p.get("pop_pct") is not None:
            d["pop"].append(p["pop_pct"])
        if p.get("qpf_mm") is not None:
            d["qpf_mm"] += p["qpf_mm"]
            d["qpf_known"] = True
    return days, tz_ok


def r1(x):
    return None if x is None else round(x, 1)


def r2(x):
    return None if x is None else round(x, 2)


# --------------------------------------------------------------------------
# CPC outlook parsing
# --------------------------------------------------------------------------

# First letter -> candidate months.  CPC seasons are written with month
# initials, so J/M/A are ambiguous and resolved by requiring three consecutive
# months (DJF -> 12,1,2 ; JJA -> 6,7,8 ; MAM -> 3,4,5).
MONTH_INITIALS = {"J": (1, 6, 7), "F": (2,), "M": (3, 5), "A": (4, 8),
                  "S": (9,), "O": (10,), "N": (11,), "D": (12,)}


def season_months(token):
    """Resolve a CPC 3-letter season code to three consecutive months.

    Returns ``(m1, m2, m3)`` or ``None`` if it is not a valid season code.
    """
    token = token.upper()
    if len(token) != 3:
        return None
    cands = [MONTH_INITIALS.get(ch) for ch in token]
    if any(c is None for c in cands):
        return None
    import itertools
    for combo in itertools.product(*cands):
        m1, m2, m3 = combo
        if m2 == (m1 % 12) + 1 and m3 == (m2 % 12) + 1:
            return (m1, m2, m3)
    return None


def parse_season_key(valid_season, stem):
    """Turn a CPC 'Valid_Seas' string into the (year, month) pairs it covers.

    CPC writes 3-month seasons in upper case (``OND 2026``) and single months
    in mixed case (``Sep 2026``); the shapefile stem repeats the same
    convention (``lead2_OND_prcp`` vs ``lead14_Sep_prcp``).
    """
    if not valid_season:
        return None, None
    parts = valid_season.split()
    if len(parts) < 2:
        return None, None
    token, year_s = parts[0], parts[1]
    try:
        year = int(year_s)
    except ValueError:
        return None, None

    if token.isupper():
        triple = season_months(token)
        if triple:
            start = triple[0]
            return [(year + (1 if m < start else 0), m) for m in triple], "season"
    # mixed-case (or word) single month, e.g. "Sep"
    if token.upper()[:3] in MONTH_ABBR:
        return [(year, MONTH_ABBR[token.upper()[:3]])], "month"
    return None, None


def collect_cpc(cpc, default_year):
    """Flatten every point-sampled CPC outlook into a list of records."""
    out = []
    for sf in cpc.get("shapefiles", []):
        if not sf.get("ok"):
            continue
        for smp in sf.get("sampled", []):
            if not smp.get("ok") or not smp.get("hits"):
                continue
            stem = smp.get("stem") or ""
            # Real CPC stems: seasonal  "lead1_SON_prcp"
            #                 short    "610temp_latest", "814prcp_latest",
            #                          "wk34temp_latest"
            # Normalise the trailing "_latest" off before matching so both
            # families can be recognised by one pair of patterns.
            stem_norm = re.sub(r"_latest$", "", stem, flags=re.I)
            m = re.match(r"lead(\d+)_([A-Za-z]+)_(temp|prcp)$", stem_norm, re.I)
            lead = int(m.group(1)) if m else None
            abbrev = m.group(2) if m else None
            var_from_stem = (m.group(3).lower() if m else None)  # 'temp' | 'prcp'
            if var_from_stem is None:
                m2 = re.match(r"^(610|814|wk34)_?(temp|prcp)$", stem_norm, re.I)
                if m2:
                    var_from_stem = m2.group(2).lower()

            for hit in smp["hits"]:
                a = hit.get("attrs") or {}
                months, kind = parse_season_key(a.get("Valid_Seas"), stem)
                start_date = a.get("Start_Date")
                end_date = a.get("End_Date")

                def iso(yyyymmdd):
                    """DBF numeric fields arrive as floats (20260922.0), so
                    coerce through int before slicing."""
                    if yyyymmdd in (None, ""):
                        return None
                    try:
                        s = str(int(float(yyyymmdd)))
                    except (TypeError, ValueError):
                        s = str(yyyymmdd).strip()
                    if len(s) != 8:
                        return None
                    try:
                        return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8])).isoformat()
                    except ValueError:
                        return None

                rec = {
                    "label": sf["label"],
                    "url": sf["url"],
                    "stem": stem,
                    # Evidence for the point sample: which polygon of the official
                    # shapefile contained 37.760459,-122.483894, its bounding box,
                    # and the raw DBF attribute row it came from.  A reviewer can
                    # check all of it against the published map.
                    "polygon_index": hit.get("index"),
                    "polygon_bbox_lon_lat": hit.get("bbox"),
                    "polygon_rings": hit.get("rings"),
                    "polygon_vertices": hit.get("vertices"),
                    "raw_dbf_row": {k: v for k, v in (a or {}).items()},
                    "lead": lead,
                    "abbrev": abbrev,
                    "variable": var_from_stem,
                    "valid_season": a.get("Valid_Seas"),
                    "kind": kind,
                    "covers": [f"{y:04d}-{m:02d}" for (y, m) in months] if months else None,
                    "start_date": iso(start_date),
                    "end_date": iso(end_date),
                    "prob": a.get("Prob"),
                    "category": a.get("Cat"),
                    "fcst_date": a.get("Fcst_Date"),
                    "used_nearest_polygon": bool(smp.get("used_nearest_polygon")),
                }
                # Human-readable category
                cat = (rec["category"] or "").strip()
                rec["category_label"] = {
                    "EC": "Equal chances",
                    "Above": "Above normal" if rec["variable"] == "temp" else "Above median",
                    "Below": "Below normal" if rec["variable"] == "temp" else "Below median",
                    "A": "Above", "B": "Below", "N": "Near normal",
                }.get(cat, cat)

                issued = rec["fcst_date"]
                if isinstance(issued, str) and len(issued) == 8 and issued.isdigit():
                    issued = f"{issued[:4]}-{issued[4:6]}-{issued[6:8]}"
                rec["issued"] = issued
                out.append(rec)

    # Deduplicate.  Several archives legitimately describe the same valid
    # period - seasprcp_202608.zip, seasprcp_202609.zip and
    # monthupd_prcp_latest.zip can all carry an "Oct 2026" outlook.  Showing
    # all of them makes a day look like it has a dozen outlooks when it has a
    # handful, so keep only the most recent issuance for each
    # (valid period, variable) pair and record which issuance was used.
    best = {}
    passthrough = []
    for rec in out:
        if rec.get("valid_season"):
            key = ("season", rec["valid_season"], rec["variable"])
        elif rec.get("start_date"):
            key = ("range", rec["stem"], rec["start_date"], rec["end_date"])
        else:
            passthrough.append(rec)
            continue
        prev = best.get(key)
        if prev is None or (rec.get("fcst_date") or "") >= (prev.get("fcst_date") or ""):
            best[key] = rec
    deduped = passthrough + list(best.values())
    return deduped


def main():
    run = load("run.json")
    nws = load("nws.json")
    cpc = load("cpc.json")
    climo = load("climatology.json")
    enso = load("enso.json")
    humidity_normals = load("humidity_normals.json")
    monthly_normals = load("monthly_normals.json")
    month_rh = {int(k): v for k, v in (humidity_normals.get("month_rh_pct") or {}).items()}
    date_rh = humidity_normals.get("date_rh_pct") or {}
    humidity_station = humidity_normals.get("station_id")
    humidity_station_name = humidity_normals.get("station_name")

    daily_climo = {d["mmdd"]: d for d in climo.get("daily", [])}
    season_climo = climo.get("season", {})
    meta = climo.get("meta", {})

    hourly = (nws.get("forecast_hourly") or {}).get("periods") or []
    nws_days, tz_ok = daily_from_hourly(hourly)
    if not tz_ok:
        print("  WARNING: zoneinfo unavailable; used fixed -08:00 offset.")
    _hourly_meta = nws.get("forecast_hourly") or {}
    nws_updated = _hourly_meta.get("updated") or _hourly_meta.get("generated_at")
    hourly_url = (nws.get("forecast_hourly") or {}).get("source_url")
    daily_url = (nws.get("forecast_daily") or {}).get("source_url")
    human_url = (nws.get("forecast_daily") or {}).get("human_url")

    cpc_records = collect_cpc(cpc, SEASON_START.year)
    cpc_maps = {m["slug"]: m for m in cpc.get("maps", []) if m.get("ok")}
    cpc_valid = cpc.get("valid_periods", {})

    def parse_span(text, default_year):
        if not text:
            return None
        m = re.search(r"([A-Za-z]+)\s+(\d{1,2})\s+(?:to|-|through)\s+([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})?", text, re.I)
        if not m:
            return None
        names = {n.lower(): i for i, n in enumerate(
            ["january", "february", "march", "april", "may", "june", "july",
             "august", "september", "october", "november", "december"], 1)}
        m1, m2 = names.get(m.group(1).lower()), names.get(m.group(3).lower())
        if not m1 or not m2:
            return None
        y = int(m.group(5)) if m.group(5) else default_year
        y2 = y if m2 >= m1 else y + 1
        try:
            return (dt.date(y, m1, int(m.group(2))).isoformat(),
                    dt.date(y2, m2, int(m.group(4))).isoformat())
        except ValueError:
            return None

    today = dt.datetime.now(dt.timezone.utc).date()
    span_610 = parse_span((cpc_valid.get("610day") or {}).get("valid"), today.year)
    span_814 = parse_span((cpc_valid.get("814day") or {}).get("valid"), today.year)

    # Index short-range outlooks by their explicit date span
    short_range = [r for r in cpc_records if r["start_date"] and r["end_date"]]
    seasonal = [r for r in cpc_records if r["covers"]]

    calendar = []
    d = SEASON_START
    while d <= SEASON_END:
        mmdd = f"{d.month:02d}-{d.day:02d}"
        iso = d.isoformat()
        ym = f"{d.year:04d}-{d.month:02d}"
        c = daily_climo.get(mmdd, {})
        n = nws_days.get(iso)

        entry = {"date": iso, "month": d.month, "day": d.day,
                 "weekday": d.strftime("%A"), "month_label": d.strftime("%B"),
                 "mmdd": mmdd}

        if n and n["hours"] >= 8:
            entry["tier"] = "nws"
            entry["tier_label"] = "Official NWS forecast"
            entry["high_f"] = r1(max(n["temps"])) if n["temps"] else None
            entry["low_f"] = r1(min(n["temps"])) if n["temps"] else None
            entry["humidity_pct"] = r1(sum(n["rh"]) / len(n["rh"])) if n["rh"] else None
            entry["humidity_min_pct"] = r1(min(n["rh"])) if n["rh"] else None
            entry["humidity_max_pct"] = r1(max(n["rh"])) if n["rh"] else None
            entry["wind_max_mph"] = r1(max(n["wind"])) if n["wind"] else None
            entry["gust_max_mph"] = r1(max(n["gust"])) if n["gust"] else None
            entry["rain_chance_pct"] = r1(max(n["pop"])) if n["pop"] else None
            entry["rain_amount_in"] = r2(n["qpf_mm"] / MM_PER_INCH) if n["qpf_known"] else None
            entry["hours_covered"] = n["hours"]
            entry["sources"] = [
                {"label": "NWS hourly gridded forecast (api.weather.gov)", "url": hourly_url},
                {"label": "NWS 7-day forecast for this point (weather.gov)", "url": human_url},
            ]
        else:
            entry["tier"] = "climatology"
            entry["tier_label"] = "1991-2020 observed climatology"
            entry["high_f"] = c.get("normal_high_f")
            entry["low_f"] = c.get("normal_low_f")
            # Relative humidity is not published as a normals element.  Where the
            # official NCEI hourly normals of temperature and dew point are
            # available it is derived from them (Magnus formula) and the
            # derivation is stated on the site.  Where they are not, the field
            # stays empty - never estimated.
            entry["humidity_pct"] = date_rh.get(mmdd)
            basis_scope = "for this calendar date"
            if entry["humidity_pct"] is None:
                entry["humidity_pct"] = month_rh.get(d.month)
                basis_scope = "for %s" % d.strftime("%B")
            if entry["humidity_pct"] is not None:
                entry["humidity_basis"] = (
                    "derived: mean of NOAA NCEI 1991-2020 hourly temperature and dew-point "
                    "normals %s at station %s, converted with the Magnus formula (%s)"
                    % (basis_scope, humidity_station or "n/a", humidity_station_name or "n/a"))
            else:
                entry["humidity_basis"] = "not available from official normals" 
            entry["wind_max_mph"] = c.get("normal_max_sustained_mph")
            entry["gust_max_mph"] = c.get("normal_max_gust_mph")
            entry["rain_chance_pct"] = c.get("p_rain_day_pct")
            entry["rain_amount_in"] = c.get("mean_daily_prcp_in")
            entry["hours_covered"] = 0
            entry["sources"] = [
                {"label": f"NCEI GHCN-Daily {meta.get('precip_station', {}).get('id', '')}",
                 "url": meta.get("precip_station", {}).get("url")},
                {"label": f"NCEI GSOD {meta.get('wind_station', {}).get('id', '')}",
                 "url": meta.get("wind_station", {}).get("url")},
            ]

        # CPC outlooks that validly cover this day
        covering = []
        for r in short_range:
            if r["start_date"] <= iso <= r["end_date"]:
                covering.append(r)
        for r in seasonal:
            if ym in (r["covers"] or []):
                covering.append(r)
        entry["cpc"] = covering

        entry["climo"] = {
            "p_rain_day_pct": c.get("p_rain_day_pct"),
            "p_rain_ge_025in_pct": c.get("p_rain_ge_025in_pct"),
            "p_rain_ge_100in_pct": c.get("p_rain_ge_100in_pct"),
            "mean_daily_prcp_in": c.get("mean_daily_prcp_in"),
            "median_wet_day_prcp_in": c.get("median_wet_day_prcp_in"),
            "max_daily_prcp_in": c.get("max_daily_prcp_in"),
            "wettest_on_record": c.get("wettest_on_record"),
            "normal_high_f": c.get("normal_high_f"),
            "normal_low_f": c.get("normal_low_f"),
            "record_high_f": c.get("record_high_f"),
            "record_low_f": c.get("record_low_f"),
            "normal_mean_wind_mph": c.get("normal_mean_wind_mph"),
            "normal_max_sustained_mph": c.get("normal_max_sustained_mph"),
            "normal_max_gust_mph": c.get("normal_max_gust_mph"),
            "max_gust_on_record_mph": c.get("max_gust_on_record_mph"),
            "max_gust_on_record_date": c.get("max_gust_on_record_date"),
            "p_gust_ge_25kt_pct": c.get("p_gust_ge_25kt_pct"),
            "p_gust_ge_35kt_pct": c.get("p_gust_ge_35kt_pct"),
            "p_wind_and_rain_pct": c.get("p_wind_and_rain_pct"),
            "p_heavy_wind_and_rain_pct": c.get("p_heavy_wind_and_rain_pct"),
            "n_years_precip": c.get("n_years_precip"),
            "n_years_wind": c.get("n_years_wind"),
            "n_years_joint": c.get("n_years_joint"),
        }
        calendar.append(entry)
        d += dt.timedelta(days=1)

    # ---- monthly roll-ups -------------------------------------------------
    dist = season_climo.get("distribution", {})
    monthly = []
    for month in (10, 11, 12, 1):
        key = {10: "october_total_prcp_in", 11: "november_total_prcp_in",
               12: "december_total_prcp_in", 1: "january_total_prcp_in"}[month]
        days_in_month = [x for x in calendar if x["month"] == month]
        exp_wet = round(sum((x["climo"]["p_rain_day_pct"] or 0) for x in days_in_month) / 100.0, 1)
        monthly.append({
            "month": month,
            "label": dt.date(2026, month, 1).strftime("%B"),
            "year": 2026 if month >= 10 else 2027,
            "total_prcp": dist.get(key),
            "expected_wet_days": exp_wet,
            "days": len(days_in_month),
            "cpc_seasonal": [r for r in seasonal
                             if f"{2026 if month >= 10 else 2027:04d}-{month:02d}" in (r["covers"] or [])],
        })

    # ---- the *current* official forecast (outside the Oct-Jan window too) ----
    # The day-by-day calendar only starts on 1 Oct, but a landlord asking "what
    # is the forecast right now" needs the days that are actually inside the
    # official horizon today.  This block is the raw NWS 7-day forecast, with no
    # season filtering and no derived numbers beyond simple daily aggregation of
    # the hourly grid.
    daily_periods = (nws.get("forecast_daily") or {}).get("periods") or []
    narrative = {}
    for p_ in daily_periods:
        st = p_.get("start_time")
        if not st:
            continue
        try:
            t_ = dt.datetime.fromisoformat(st.replace("Z", "+00:00")).astimezone(
                dt.timezone(dt.timedelta(hours=-7)))
        except ValueError:
            continue
        narrative.setdefault(t_.date().isoformat(), []).append({
            "name": p_.get("name"),
            "is_daytime": p_.get("is_daytime"),
            "temperature_f": p_.get("temperature_f"),
            "wind_speed": p_.get("wind_speed"),
            "wind_direction": p_.get("wind_direction"),
            "pop_pct": p_.get("pop_pct"),
            "short_forecast": p_.get("short_forecast"),
            "detailed_forecast": p_.get("detailed_forecast"),
        })
    current_days = []
    for iso in sorted(nws_days):
        n_ = nws_days[iso]
        current_days.append({
            "date": iso,
            "weekday": dt.date.fromisoformat(iso).strftime("%A"),
            "high_f": r1(max(n_["temps"])) if n_["temps"] else None,
            "low_f": r1(min(n_["temps"])) if n_["temps"] else None,
            "humidity_pct": r1(sum(n_["rh"]) / len(n_["rh"])) if n_["rh"] else None,
            "humidity_min_pct": r1(min(n_["rh"])) if n_["rh"] else None,
            "humidity_max_pct": r1(max(n_["rh"])) if n_["rh"] else None,
            "rain_chance_pct": r1(max(n_["pop"])) if n_["pop"] else None,
            "rain_amount_in": r2(n_["qpf_mm"] / MM_PER_INCH) if n_["qpf_known"] else None,
            "wind_max_mph": r1(max(n_["wind"])) if n_["wind"] else None,
            "gust_max_mph": r1(max(n_["gust"])) if n_["gust"] else None,
            "hours_covered": n_["hours"],
            "periods": narrative.get(iso, []),
        })
    current_forecast = {
        "generated_utc": (nws.get("forecast_hourly") or {}).get("generated_at"),
        "forecast_updated": nws_updated,
        "elevation_m": (nws.get("forecast_hourly") or {}).get("elevation_m"),
        "horizon_days": len(current_days),
        "first_day": current_days[0]["date"] if current_days else None,
        "last_day": current_days[-1]["date"] if current_days else None,
        "inside_season_window": bool([d_ for d_ in current_days
                                      if SEASON_START.isoformat() <= d_["date"] <= SEASON_END.isoformat()]),
        "sources": [
            {"label": "NWS hourly gridded forecast (api.weather.gov)", "url": hourly_url},
            {"label": "NWS 7-day forecast for this point (weather.gov)", "url": human_url},
        ],
        "alerts": nws.get("active_alerts", {}),
        "observations": nws.get("stations", {}),
        "days": current_days,
    }

    out = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": run.get("target", {}),
        "season": {"start": SEASON_START.isoformat(), "end": SEASON_END.isoformat()},
        "normals_period": run.get("normals_period", [1991, 2020]),
        "tier_definitions": {
            "nws": "Day is inside the official NWS gridded forecast horizon. Values are the actual NWS forecast.",
            "climatology": "Beyond the official forecast horizon. Values are 1991-2020 observed statistics for this calendar date - NOT a forecast.",
        },
        "nws_window": {
            "first_day": min(nws_days) if nws_days else None,
            "last_day": max(nws_days) if nws_days else None,
            "days_covered": sum(1 for e in calendar if e["tier"] == "nws"),
            # How long the official daily horizon is today, independent of how
            # many scoreboard days fall inside it (today: none, because the
            # horizon ends in September and the scoreboard starts on 1 October).
            "horizon_days": len(current_forecast.get("days") or []),
            "forecast_updated": nws_updated,
            "hourly_url": hourly_url,
            "daily_url": daily_url,
            "human_url": human_url,
        },
        "cpc": {
            "records": cpc_records,
            "valid_periods": cpc_valid,
            "span_610day": span_610,
            "span_814day": span_814,
            "maps": cpc_maps,
            "discussions": [{"label": d["label"], "url": d["url"],
                             "human_url": d["human_url"],
                             "stale": d.get("stale", False)}
                            for d in cpc.get("discussions", []) if d.get("ok")],
        },
        "enso": {
            # NOAA's published ONI product is the headline value.
            "official": enso.get("official_oni", {}),
            "latest_official": (enso.get("official_oni") or {}).get("latest"),
            # The project's own derivation is kept only as a published cross-check.
            "derived": enso.get("latest_oni_derived"),
            "cross_check": enso.get("oni_cross_check"),
            "table_url": enso.get("oni_table_url"),
            "diagnostic_url": enso.get("diagnostic_url"),
            "diagnostic_status": enso.get("diagnostic_status"),
            "diagnostic_synopsis": enso.get("diagnostic_synopsis"),
            "diagnostic_key_sentences": enso.get("diagnostic_key_sentences", []),
            "diagnostic_sha256": enso.get("diagnostic_sha256"),
            "sources": enso.get("sources", []),
            "unusable_pages": enso.get("unusable_pages", []),
            "reference_links": enso.get("reference_links", []),
        },
        "humidity_normals": humidity_normals or None,
        "monthly_normals_official": monthly_normals or None,
        "season_summary": dist,
        "streak_probability": season_climo.get("probability_of_at_least_one_streak", {}),
        "enso_stratified": season_climo.get("enso_stratified_season_total_prcp_in", {}),
        "wettest_seasons": season_climo.get("wettest_seasons", []),
        "driest_seasons": season_climo.get("driest_seasons", []),
        "season_by_year": season_climo.get("seasons", []),
        "monthly": monthly,
        "definitions": meta.get("definitions", {}),
        "caveats": meta.get("caveats", []),
        "units": meta.get("units", {}),
        "stations": {"precip_temp": meta.get("precip_station"), "wind": meta.get("wind_station")},
        "current_forecast": current_forecast,
        "days": calendar,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    n_forecast = out["nws_window"]["days_covered"]
    print(f"  wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    print(f"  {n_forecast} day(s) carry an official NWS forecast; "
          f"{len(calendar) - n_forecast} day(s) show 1991-2020 climatology.")
    print(f"  CPC records attached: {len(cpc_records)} "
          f"({len(seasonal)} seasonal/monthly, {len(short_range)} short-range)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
