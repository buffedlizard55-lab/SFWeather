#!/usr/bin/env python3
"""Assemble the Oct 1 2026 - Jan 31 2027 day-by-day scoreboard.

Tiering rules (these are the anti-hallucination rules of the whole project):

1. ``nws``          - the day falls inside the official NWS gridded forecast
                      horizon.  Temperature, humidity, wind, gusts, rain chance
                      and rain amount are the actual NWS numbers.
2. ``cpc_week2``    - the day falls inside the CPC 6-10 or 8-14 day outlook
                      window.  Only CPC's probability-of-above/below-normal
                      statement is carried; daily numbers come from climatology.
3. ``cpc_monthly``  - the day falls in a month that has an official CPC
                      monthly outlook.  Same rule: outlook probabilities only.
4. ``climatology``  - beyond the official forecast horizon.  Everything shown is
                      the 1991-2020 observed climatology for that calendar date
                      at the verified NCEI station, and is labelled as such.

No day ever shows a made-up "forecast" number.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "calendar.json"

SEASON_START = dt.date(2026, 10, 1)
SEASON_END = dt.date(2027, 1, 31)
MM_PER_INCH = 25.4


def load(name):
    p = DATA / name
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def parse_wind(s):
    """NWS hourly windSpeed strings look like '8 mph' or '5 to 11 mph'."""
    if not s:
        return None
    nums = [float(x) for x in __import__("re").findall(r"(\d+(?:\.\d+)?)", s)]
    if not nums:
        return None
    return max(nums)


def daily_from_hourly(periods, tz_name="America/Los_Angeles"):
    """Aggregate the NWS hourly gridded forecast into local calendar days."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
        tz_ok = True
    except Exception:  # noqa: BLE001
        tz = dt.timezone(dt.timedelta(hours=-8))   # PST fallback
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
        local = t.astimezone(tz)
        key = local.date().isoformat()
        d = days.setdefault(key, {
            "temps": [], "rh": [], "dewpoint": [], "wind": [], "gust": [],
            "pop": [], "qpf_mm": 0.0, "hours": 0, "qpf_known": False,
        })
        d["hours"] += 1
        if p.get("temperature_f") is not None:
            d["temps"].append(p["temperature_f"])
        if p.get("rh_pct") is not None:
            d["rh"].append(p["rh_pct"])
        if p.get("dewpoint_f") is not None:
            d["dewpoint"].append(p["dewpoint_f"])
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


def main():
    run = load("run.json")
    nws = load("nws.json")
    cpc = load("cpc.json")
    climo = load("climatology.json")
    enso = load("enso.json")

    daily_climo = {d["mmdd"]: d for d in climo.get("daily", [])}
    season_climo = climo.get("season", {})
    meta = climo.get("meta", {})

    # ---- NWS daily aggregation -------------------------------------------
    hourly = (nws.get("forecast_hourly") or {}).get("periods") or []
    nws_days, tz_ok = daily_from_hourly(hourly)
    nws_min_date = min(nws_days) if nws_days else None
    nws_max_date = max(nws_days) if nws_days else None
    nws_updated = (nws.get("forecast_hourly") or {}).get("updated")
    hourly_url = (nws.get("forecast_hourly") or {}).get("source_url")
    daily_url = (nws.get("forecast_daily") or {}).get("source_url")
    human_url = (nws.get("forecast_daily") or {}).get("human_url")

    if not tz_ok:
        print("  WARNING: zoneinfo/America_Los_Angeles not available; used a fixed "
              "-08:00 offset. Day assignment in November-January may be off by an hour.")

    # ---- CPC windows -------------------------------------------------------
    cpc_windows = []
    for sf in cpc.get("shapefiles", []):
        if not sf.get("ok"):
            continue
        cpc_windows.append({
            "label": sf["label"],
            "url": sf["url"],
            "attributes": sf.get("attributes"),
            "fields": sf.get("fields"),
            "issuance_ym": sf.get("issuance_ym"),
        })
    cpc_valid = cpc.get("valid_periods", {})
    cpc_maps = {m["slug"]: m for m in cpc.get("maps", []) if m.get("ok")}

    # Parse the "Valid: <Month> <D> to <Month> <D>, <YYYY>" strings into spans.
    def parse_span(text, default_year):
        if not text:
            return None
        import re
        m = re.search(r"([A-Za-z]+)\s+(\d{1,2})\s+(?:to|-|through)\s+([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})?",
                      text, re.I)
        if not m:
            return None
        months = {mo.lower(): i for i, mo in enumerate(
            ["january", "february", "march", "april", "may", "june", "july",
             "august", "september", "october", "november", "december"], 1)}
        m1, m2 = months.get(m.group(1).lower()), months.get(m.group(3).lower())
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

    # ---- walk the season ---------------------------------------------------
    calendar = []
    d = SEASON_START
    while d <= SEASON_END:
        mmdd = f"{d.month:02d}-{d.day:02d}"
        iso = d.isoformat()
        c = daily_climo.get(mmdd, {})
        n = nws_days.get(iso)

        entry = {
            "date": iso,
            "month": d.month,
            "day": d.day,
            "weekday": d.strftime("%A"),
            "month_label": d.strftime("%B"),
            "mmdd": mmdd,
        }

        # --- tier 1: official NWS forecast
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
                {"label": "NWS hourly gridded forecast", "url": hourly_url},
                {"label": "NWS 7-day forecast (readable)", "url": daily_url},
                {"label": "NWS forecast for this point", "url": human_url},
            ]
        else:
            entry["tier"] = "climatology"
            entry["tier_label"] = "1991-2020 observed climatology"
            entry["high_f"] = c.get("normal_high_f")
            entry["low_f"] = c.get("normal_low_f")
            entry["humidity_pct"] = None
            entry["wind_max_mph"] = c.get("normal_max_sustained_mph")
            entry["gust_max_mph"] = c.get("normal_max_gust_mph")
            entry["rain_chance_pct"] = c.get("p_rain_day_pct")
            entry["rain_amount_in"] = c.get("mean_daily_prcp_in")
            entry["sources"] = [
                {"label": meta.get("precip_station", {}).get("name", "NCEI GHCN-Daily"),
                 "url": meta.get("precip_station", {}).get("url")},
                {"label": meta.get("wind_station", {}).get("name", "NCEI GSOD"),
                 "url": meta.get("wind_station", {}).get("url")},
            ]

        # --- CPC overlay
        entry["cpc"] = []
        if span_610 and span_610[0] <= iso <= span_610[1]:
            entry["cpc"].append({"period": "6-10 Day Outlook",
                                 "valid": (cpc_valid.get("610day") or {}).get("valid"),
                                 "issued": (cpc_valid.get("610day") or {}).get("issued"),
                                 "url": "https://www.cpc.ncep.noaa.gov/products/predictions/610day/",
                                 "map": cpc_maps.get("610day_temp", {}).get("local_path"),
                                 "map_prcp": cpc_maps.get("610day_prcp", {}).get("local_path")})
        if span_814 and span_814[0] <= iso <= span_814[1]:
            entry["cpc"].append({"period": "8-14 Day Outlook",
                                 "valid": (cpc_valid.get("814day") or {}).get("valid"),
                                 "issued": (cpc_valid.get("814day") or {}).get("issued"),
                                 "url": "https://www.cpc.ncep.noaa.gov/products/predictions/814day/",
                                 "map": cpc_maps.get("814day_temp", {}).get("local_path"),
                                 "map_prcp": cpc_maps.get("814day_prcp", {}).get("local_path")})

        # --- always carry the climatological context
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

    # ------------------------------------------------------------------
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
            "first_day": nws_min_date,
            "last_day": nws_max_date,
            "days_covered": sum(1 for e in calendar if e["tier"] == "nws"),
            "forecast_updated": nws_updated,
            "hourly_url": hourly_url,
            "daily_url": daily_url,
            "human_url": human_url,
        },
        "cpc": {
            "windows": cpc_windows,
            "valid_periods": cpc_valid,
            "span_610day": span_610,
            "span_814day": span_814,
            "maps": cpc_maps,
        },
        "enso": {
            "latest": enso.get("latest_oni"),
            "recent": enso.get("recent_oni"),
            "table_url": enso.get("oni_table_url"),
            "diagnostic_url": enso.get("diagnostic_url"),
        },
        "season_summary": season_climo.get("distribution", {}),
        "streak_probability": season_climo.get("probability_of_at_least_one_streak", {}),
        "enso_stratified": season_climo.get("enso_stratified_season_total_prcp_in", {}),
        "wettest_seasons": season_climo.get("wettest_seasons", []),
        "driest_seasons": season_climo.get("driest_seasons", []),
        "season_by_year": season_climo.get("seasons", []),
        "definitions": meta.get("definitions", {}),
        "units": meta.get("units", {}),
        "stations": {
            "precip_temp": meta.get("precip_station"),
            "wind": meta.get("wind_station"),
        },
        "days": calendar,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    n_forecast = out["nws_window"]["days_covered"]
    print(f"  wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    print(f"  {n_forecast} day(s) carry an official NWS forecast; "
          f"{len(calendar) - n_forecast} day(s) show 1991-2020 climatology.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
