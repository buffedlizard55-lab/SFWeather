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

# The shared parser/comparison implementation.  Imported under an explicit
# alias because main() already has a local `climo` (the loaded climatology.json),
# which silently shadowed the module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import climo as climo_lib  # noqa: E402

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


def timezone_for(tz_name="America/Los_Angeles"):
    """Return the named IANA timezone and whether it was resolved exactly.

    Forecast periods are UTC timestamps.  A fixed Pacific offset is tempting,
    but it mislabels winter periods after the daylight-saving transition.  The
    NWS point response supplies the IANA name, and Python 3.11 ships the IANA
    database on the GitHub runner.  The fixed offset is retained only as a
    defensive fallback and is surfaced to the caller as ``tz_ok=False``.
    """
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name), True
    except Exception:  # noqa: BLE001
        return dt.timezone(dt.timedelta(hours=-8)), False


def local_date_from_iso(value, tz_name="America/Los_Angeles"):
    """Convert an ISO timestamp to a local date using the named NWS timezone."""
    if not value:
        return None
    try:
        timestamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    tz, _ = timezone_for(tz_name)
    return timestamp.astimezone(tz).date()


def daily_from_hourly(periods, tz_name="America/Los_Angeles"):
    """Aggregate the NWS hourly gridded forecast into local calendar days."""
    tz, tz_ok = timezone_for(tz_name)
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


KM_PER_MILE = 1.609344

# Matches an ISO 8601 interval as NWS publishes it in gridpoint data, e.g.
#   2026-09-17T14:00:00+00:00/PT3H
#   2026-09-18T00:00:00+00:00/P1DT6H
_INTERVAL_RE = re.compile(
    r"^(?P<start>[^/]+)/(?:P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?)?$")


def parse_valid_time(value):
    """Split an NWS ``validTime`` into (start, duration_hours).

    NWS gridpoint series carry ISO 8601 intervals, not single timestamps:
    ``2026-09-17T14:00:00+00:00/PT3H`` means the value holds for the three
    hours starting at 14:00Z.  Returns (None, None) for anything unparseable
    so the caller can skip it rather than guess.
    """
    if not value or "/" not in value:
        return None, None
    m = _INTERVAL_RE.match(value.strip())
    if not m:
        return None, None
    try:
        start = dt.datetime.fromisoformat(m.group("start").replace("Z", "+00:00"))
    except ValueError:
        return None, None
    hours = (int(m.group("days") or 0) * 24
             + int(m.group("hours") or 0)
             + int(m.group("minutes") or 0) / 60.0)
    if hours <= 0:
        hours = 1.0
    return start, hours


def gridpoint_series(raw_values):
    """Flatten one NWS gridpoint series into (start, hours, value) triples."""
    out = []
    for item in (raw_values or {}).get("values") or []:
        start, hours = parse_valid_time(item.get("validTime"))
        if start is None or item.get("value") is None:
            continue
        out.append((start, hours, float(item["value"])))
    return out


def daily_from_gridpoint(gridpoint_raw, tz_name="America/Los_Angeles"):
    """Aggregate NWS gridpoint gust and QPF series into local calendar days.

    Why this exists: the ``/forecast/hourly`` product returns no ``windGust``
    and no QPF for this grid cell (0 of 156 periods on 17 Sep 2026), so the
    two figures a landlord cares about most - how hard the wind gusts and how
    much rain falls - came back as em dashes even though NWS publishes both at
    the same grid point in ``gridpoint_raw``.

    Two honest derivations are made, and both are labelled on the site:

    * ``windGust`` is an instantaneous km/h value, so the daily figure is the
      maximum over the hours that fall in that local day, converted to mph.
    * ``quantitativePrecipitation`` is an *accumulation over the interval*, not
      a rate.  Where an interval crosses local midnight the accumulation is
      split between the two days in proportion to the hours each gets.  This is
      an allocation of an official total, not a new model.
    """
    tz, tz_ok = timezone_for(tz_name)
    values = (gridpoint_raw or {}).get("values") or {}

    gust_by_day: dict[str, list[float]] = {}
    qpf_by_day: dict[str, float] = {}
    qpf_days_known: set[str] = set()

    for start, hours, kmh in gridpoint_series(values.get("windGust")):
        end = start + dt.timedelta(hours=hours)
        step = dt.timedelta(hours=1)
        cursor = start
        while cursor < end:
            day = cursor.astimezone(tz).date().isoformat()
            gust_by_day.setdefault(day, []).append(kmh / KM_PER_MILE)
            cursor += step

    for start, hours, mm in gridpoint_series(values.get("quantitativePrecipitation")):
        # Allocate the accumulation across local days by the share of hours.
        end = start + dt.timedelta(hours=hours)
        step = dt.timedelta(hours=1)
        cursor = start
        per_hour = mm / hours if hours else 0.0
        while cursor < end:
            day = cursor.astimezone(tz).date().isoformat()
            qpf_by_day[day] = qpf_by_day.get(day, 0.0) + per_hour
            qpf_days_known.add(day)
            cursor += step

    days = {}
    for day in set(gust_by_day) | set(qpf_by_day):
        days[day] = {
            "gust_mph": gust_by_day.get(day) or [],
            "qpf_mm": qpf_by_day.get(day, 0.0),
            "qpf_known": day in qpf_days_known,
        }
    return days, tz_ok


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

                # The DBF's category field and its probability do not always
                # point the same way.  Several of CPC's long-lead polygons
                # carry Cat="Above" with Prob=33.0, and 33.0% is the
                # climatological baseline for a three-way split (100/3 =
                # 33.3%).  Rendering that as a plain "Above median (33%)" would
                # present a no-tilt value as a tilt, so the record carries an
                # explicit, derived flag and a sentence the reader can check
                # against the raw DBF row that ships with it.
                try:
                    prob_val = float(rec.get("prob"))
                except (TypeError, ValueError):
                    prob_val = None
                cat_norm = cat.upper()
                rec["probability_at_climatological_baseline"] = bool(
                    prob_val is not None
                    and abs(prob_val - (100.0 / 3.0)) < 0.5
                    and cat_norm in ("ABOVE", "BELOW", "A", "B", "N", "NEAR")
                )
                if rec["probability_at_climatological_baseline"]:
                    rec["baseline_note"] = (
                        f"CPC's category field for this polygon is '{cat}' but the "
                        f"probability it carries is {prob_val:.1f}%. A three-way split "
                        "has a climatological baseline of 33.3%, so this value sits on "
                        "the baseline and is not a tilt. Both the raw category and the "
                        "probability are shown exactly as CPC published them; this note "
                        "is this project's reading of the two, and the raw DBF row is "
                        "published next to it for checking.")

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
    # NOAA's own published per-date normals (see pipeline/climo.py).  These are
    # carried onto every day so the dialog can show the official number next to
    # this project's derived one, with the difference stated.
    published_daily_normals = load("daily_normals.json")
    pub_by_mmdd = published_daily_normals.get("by_mmdd") or {}
    official_column_names = ((published_daily_normals.get("layout") or {})
                             .get("column_by_key") or {})
    official_column_names = dict(official_column_names)
    official_column_names.setdefault("n_years_pcp_ge_010in",
                                     "years_DLY-PRCP-PCTALL-GE010HI")

    daily_climo = {d["mmdd"]: d for d in climo.get("daily", [])}
    season_climo = climo.get("season", {})
    meta = climo.get("meta", {})

    hourly = (nws.get("forecast_hourly") or {}).get("periods") or []
    point_timezone = (nws.get("point") or {}).get("timezone") or "America/Los_Angeles"
    nws_days, tz_ok = daily_from_hourly(hourly, point_timezone)
    if not tz_ok:
        print("  WARNING: named timezone unavailable; used fixed -08:00 fallback.")

    # Gust and QPF come from the raw gridpoint series, because the hourly
    # forecast product does not carry them for this cell.  They are merged only
    # into days that already exist in the NWS forecast horizon - never into a
    # climatology day.
    gp_days, gp_tz_ok = daily_from_gridpoint(nws.get("gridpoint_raw"), point_timezone)
    if not gp_tz_ok:
        print("  WARNING: gridpoint aggregation used the fixed -08:00 fallback.")
    gp_gust_filled = gp_qpf_filled = 0
    for iso, n in nws_days.items():
        g = gp_days.get(iso)
        if not g:
            continue
        if not n["gust"] and g["gust_mph"]:
            n["gust"].extend(g["gust_mph"])
            n["gust_from_gridpoint"] = True
            gp_gust_filled += 1
        if not n["qpf_known"] and g["qpf_known"]:
            n["qpf_mm"] = g["qpf_mm"]
            n["qpf_known"] = True
            n["qpf_from_gridpoint"] = True
            gp_qpf_filled += 1
    print("  gridpoint fill: %d day(s) gained a gust, %d gained a rain amount"
          % (gp_gust_filled, gp_qpf_filled))

    _hourly_meta = nws.get("forecast_hourly") or {}
    nws_updated = _hourly_meta.get("updated") or _hourly_meta.get("generated_at")
    hourly_url = (nws.get("forecast_hourly") or {}).get("source_url")
    daily_url = (nws.get("forecast_daily") or {}).get("source_url")
    human_url = (nws.get("forecast_daily") or {}).get("human_url")
    gridpoint_url = (nws.get("gridpoint_raw") or {}).get("source_url")
    aggregation = {
        "timezone": point_timezone,
        "temperature": "daily high/low are the maximum/minimum hourly NWS grid temperatures",
        "humidity": "daily humidity is the mean of available hourly NWS relative humidity values; min/max are also published",
        "rain_chance": "daily rain chance is the maximum available hourly NWS probability of precipitation (POP), not a new probability model",
        "rain_amount": "daily rain amount is the sum of available hourly NWS quantitative precipitation forecast (QPF) values. The /forecast/hourly product returned no QPF for this grid cell, so it falls back to the NWS gridpoint quantitativePrecipitation series: each value is an accumulation over a 3-6 hour interval, and where an interval crosses local midnight the total is split between the two days in proportion to the hours each gets. If neither product has a value the cell stays empty - it is never assumed to be zero.",
        "wind": "daily wind is the maximum available hourly NWS grid value. The /forecast/hourly product returned no wind gusts for this grid cell, so gusts fall back to the NWS gridpoint windGust series: the daily figure is the maximum gust over the hours falling in that local day, converted from km/h to mph.",
        "gust_source": gridpoint_url,
        "qpf_source": gridpoint_url,
    }

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
            entry["gust_basis"] = (
                "NWS gridpoint windGust series (max over the local day)"
                if n.get("gust_from_gridpoint") else
                "NWS hourly forecast wind gust (max over the local day)") if n["gust"] else None
            entry["rain_amount_basis"] = (
                "NWS gridpoint quantitativePrecipitation (interval accumulations "
                "allocated to local days by hour)"
                if n.get("qpf_from_gridpoint") else
                "sum of NWS hourly QPF values") if n["qpf_known"] else None
            # Every published field names the basis it used.  Previously only
            # humidity, gust and rain amount did, so a reviewer of a forecast day
            # could not tell where the temperature, the wind or the rain chance
            # came from - the three fields are named here exactly as they are
            # computed in daily_from_hourly(), not as they are assumed to be.
            entry["temp_basis"] = (
                "NWS hourly gridded forecast temperature: highest and lowest of the "
                f"{n['hours']} grid hour(s) falling in this local day") if n["temps"] else None
            entry["humidity_basis"] = (
                "NWS hourly gridded forecast relative humidity: mean over the "
                f"{n['hours']} grid hour(s) falling in this local day") if n["rh"] else None
            entry["wind_basis"] = (
                "NWS hourly gridded forecast wind speed, taking the upper end of each "
                "hour's published range: highest of the hours falling in this local day"
            ) if n["wind"] else None
            entry["rain_chance_basis"] = (
                "NWS hourly gridded probability of precipitation: highest of the hours "
                "falling in this local day") if n["pop"] else None
            entry["hours_covered"] = n["hours"]
            entry["sources"] = [
                {"label": "NWS hourly gridded forecast (api.weather.gov)", "url": hourly_url},
                {"label": "NWS gridpoint data - windGust and QPF series (api.weather.gov)", "url": gridpoint_url},
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

            # Per-field basis for a climatology day.  Each sentence describes the
            # arithmetic that actually produced the number in
            # climo.build_daily_climatology() - including the two facts a reader
            # would otherwise assume away: that the rainfall mean includes dry
            # days, and that GSOD wind days are UTC days.
            p_id = meta.get("precip_station", {}).get("id", "")
            p_name = meta.get("precip_station", {}).get("name", "")
            w_id = meta.get("wind_station", {}).get("id", "")
            w_name = meta.get("wind_station", {}).get("name", "")
            n_years_p = c.get("n_years_precip")
            n_years_w = c.get("n_years_wind")
            period_txt = "%s-%s" % (tuple(run.get("normals_period", [1991, 2020])))
            entry["temp_basis"] = (
                "this project's mean of the observed daily maxima and minima "
                f"(NOAA NCEI GHCN-Daily TMAX / TMIN) for this calendar date over the "
                f"{period_txt} seasons at station {p_id} ({p_name}); NOAA's own "
                "published normal for the same date is shown separately below and the "
                "difference is stated, never averaged away"
            ) if c.get("normal_high_f") is not None or c.get("normal_low_f") is not None else None
            entry["rain_chance_basis"] = (
                f"share of the {n_years_p} seasons with a GHCN-Daily precipitation value "
                f"for this calendar date ({period_txt}) that recorded >= 0.01 in at "
                f"station {p_id}"
            ) if c.get("p_rain_day_pct") is not None else None
            entry["rain_amount_basis"] = (
                f"mean of ALL observed GHCN-Daily totals for this calendar date over the "
                f"{n_years_p} seasons with a value ({period_txt}), dry days included - so "
                "this is the expected amount for the date, not the amount on a day it "
                f"rains; station {p_id}"
            ) if c.get("mean_daily_prcp_in") is not None else None
            entry["wind_basis"] = (
                f"mean of the GSOD daily maximum sustained wind (MXSPD, knots converted "
                f"at 1 kt = 1.15078 mph) for this calendar date over the {n_years_w} "
                f"seasons with a value ({period_txt}) at station {w_id} ({w_name}); GSOD "
                "days are UTC days (0000Z-2359Z), about 16:00-16:00 Pacific, and SFO is "
                "more exposed than the Sunset, so this is an upper bound"
            ) if c.get("normal_max_sustained_mph") is not None else None
            entry["gust_basis"] = (
                f"mean of the GSOD daily peak gust values (GUST, knots converted at "
                f"1 kt = 1.15078 mph) reported for this calendar date over the "
                f"{period_txt} seasons at station {w_id} ({w_name}); GSOD days are UTC "
                "days (0000Z-2359Z)"
            ) if c.get("normal_max_gust_mph") is not None else None
            entry["hours_covered"] = 0
            entry["sources"] = [
                {"label": f"NCEI GHCN-Daily {meta.get('precip_station', {}).get('id', '')}",
                 "url": meta.get("precip_station", {}).get("url")},
                {"label": f"NCEI GSOD {meta.get('wind_station', {}).get('id', '')}",
                 "url": meta.get("wind_station", {}).get("url")},
            ]

        # ---- NOAA's published daily normals for this calendar date ----------
        # Read straight out of the official NCEI file. Where this project also
        # derives the same quantity from GHCN-Daily, the derived value and the
        # signed difference are published alongside it - the two are never
        # reconciled into one number, so a reviewer can see the disagreement.
        pub = pub_by_mmdd.get(mmdd)
        if pub:
            official = dict(pub)
            official["source_url"] = published_daily_normals.get("url")
            official["station_id"] = published_daily_normals.get("station_id")
            official["source"] = published_daily_normals.get("source")
            derived_pairs = (
                ("p_pcp_ge_0p01in_pct", "p_rain_day_pct", "pct_points",
                 "share of years with >= 0.01 in"),
                ("p_pcp_ge_0p25in_pct", "p_rain_ge_025in_pct", "pct_points",
                 "share of years with >= 0.25 in"),
                ("p_pcp_ge_1p00in_pct", "p_rain_ge_100in_pct", "pct_points",
                 "share of years with >= 1.00 in"),
                ("normal_high_f", "normal_high_f", "deg_f", "normal high"),
                ("normal_low_f", "normal_low_f", "deg_f", "normal low"),
            )
            comparison = []
            for pub_key, der_key, unit, label in derived_pairs:
                pv, dv = official.get(pub_key), c.get(der_key)
                if pv is None or dv is None:
                    continue
                comparison.append({
                    "quantity": label,
                    "published": pv,
                    "derived": dv,
                    "difference": round(pv - dv, 3),
                    "unit": unit,
                    "published_column": next(
                        (col for col, key in official_column_names.items() if key == pub_key),
                        pub_key),
                })
            # Only genuinely like-for-like pairs are compared, so a temperature
            # normal is never diffed against a probability.
            official["derived_comparison"] = comparison
            official["published_columns"] = official_column_names
            entry["official_normal"] = official
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
        local_day = local_date_from_iso(p_.get("start_time"), point_timezone)
        if local_day is None:
            continue
        narrative.setdefault(local_day.isoformat(), []).append({
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
            "rain_amount_basis": (
                "NWS gridpoint quantitativePrecipitation (interval accumulations "
                "allocated to local days by hour)"
                if n_.get("qpf_from_gridpoint") else
                "sum of NWS hourly QPF values") if n_["qpf_known"] else None,
            "wind_max_mph": r1(max(n_["wind"])) if n_["wind"] else None,
            "gust_max_mph": r1(max(n_["gust"])) if n_["gust"] else None,
            "gust_basis": (
                "NWS gridpoint windGust series (max over the local day)"
                if n_.get("gust_from_gridpoint") else
                "NWS hourly forecast wind gust (max over the local day)") if n_["gust"] else None,
            # Same per-field basis rule as the scoreboard days: this panel is the
            # only real forecast on the site, so it carries the fullest
            # provenance of all.
            "temp_basis": (
                "NWS hourly gridded forecast temperature: highest and lowest of the "
                f"{n_['hours']} grid hour(s) falling in this local day") if n_["temps"] else None,
            "humidity_basis": (
                "NWS hourly gridded forecast relative humidity: mean over the "
                f"{n_['hours']} grid hour(s) falling in this local day") if n_["rh"] else None,
            "wind_basis": (
                "NWS hourly gridded forecast wind speed, taking the upper end of each "
                "hour's published range: highest of the hours falling in this local day"
            ) if n_["wind"] else None,
            "rain_chance_basis": (
                "NWS hourly gridded probability of precipitation: highest of the hours "
                "falling in this local day") if n_["pop"] else None,
            "hours_covered": n_["hours"],
            "periods": narrative.get(iso, []),
        })
    # ---- NWS's own discussion language (atmospheric river, prolonged rain,
    # heavy rain, strong wind, quoted amounts, wind+rain in one sentence) ------
    # The Area Forecast Discussion is already fetched verbatim every night.  It
    # is the only official product in which a forecaster says in words that a
    # long-duration or high-intensity event is coming, which is precisely the
    # landlord's "days or weeks of straight rain" question.  The scan publishes
    # quotations, never numbers, and never attaches a quotation to a calendar
    # date - see climo.afd_language_scan() for the rule set.
    afd_language = climo_lib.afd_language_scan((nws.get("products") or {}).get("AFD"))

    current_forecast = {
        "generated_utc": (nws.get("forecast_hourly") or {}).get("generated_at"),
        "forecast_updated": nws_updated,
        "elevation_m": (nws.get("forecast_hourly") or {}).get("elevation_m"),
        "horizon_days": len(current_days),
        "first_day": current_days[0]["date"] if current_days else None,
        "last_day": current_days[-1]["date"] if current_days else None,
        "inside_season_window": bool([d_ for d_ in current_days
                                      if SEASON_START.isoformat() <= d_["date"] <= SEASON_END.isoformat()]),
        "aggregation": aggregation,
        "sources": [
            {"label": "NWS hourly gridded forecast (api.weather.gov)", "url": hourly_url},
            {"label": "NWS gridpoint data - windGust and QPF series (api.weather.gov)", "url": gridpoint_url},
            {"label": "NWS 7-day forecast for this point (weather.gov)", "url": human_url},
        ],
        "alerts": nws.get("active_alerts", {}),
        "observations": nws.get("stations", {}),
        "days": current_days,
    }

    # ---- published-vs-derived daily normals, over the whole season window ----
    # This is the single most direct cross-check on the site: NOAA publishes, for
    # each calendar date, the share of years that recorded at least 0.01 in of
    # precipitation.  The project derives the same quantity from 30 seasons of
    # GHCN-Daily.  Both are published; the difference is stated, never averaged
    # away.  A large difference would mean one of the two is wrong, and it is
    # surfaced as an irregularity rather than quietly dropped.
    daily_normals_comparison = None
    if pub_by_mmdd:
        # The aggregation lives in climo, next to the parser, so the site, the
        # ledger and the unit tests all measure the same thing the same way.
        # (build_calendar previously re-implemented it inline, which is how the
        # threshold pairing drifted.)
        comparison = climo_lib.compare_daily_normals(pub_by_mmdd, daily_climo)
        # Inside the season it is the ISO date a reader wants, not "MM-DD".
        mmdd_to_iso = {d["mmdd"]: d["date"] for d in calendar}
        for row in comparison.get("flagged") or []:
            row["date"] = mmdd_to_iso.get(row.get("mmdd"))
        for blk in (comparison.get("pairs") or {}).values():
            if blk.get("largest_difference_date"):
                blk["largest_difference_date"] = mmdd_to_iso.get(
                    blk["largest_difference_date"], blk["largest_difference_date"])
        comparison["published_source_url"] = published_daily_normals.get("url")
        comparison["published_station_id"] = published_daily_normals.get("station_id")
        comparison["published_sha256"] = published_daily_normals.get("sha256")
        comparison["flag_threshold_pct_points"] = 10.0
        comparison["note"] = (
            "Published values are read column-for-column out of NOAA NCEI's "
            "1991-2020 daily normals for the same station; derived values are this "
            "project's own count over the 30 seasons of GHCN-Daily in the same "
            "window. NOAA smooths its published values across neighbouring dates "
            "while this project's are raw counts in 3.33-point steps, so a few "
            "points of difference is expected. Both are shown and the difference is "
            "published rather than reconciled.")
        daily_normals_comparison = comparison

    out = {
        # Keep the source-run timestamp, rather than stamping a later local
        # transform as if it fetched NOAA again.  In the normal workflow this
        # is only minutes before the build; during offline rebuilds it prevents
        # the freshness banner from overstating data recency.
        "generated_utc": run.get("generated_utc") or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": run.get("target", {}),
        "season": {"start": SEASON_START.isoformat(), "end": SEASON_END.isoformat()},
        "normals_period": run.get("normals_period", [1991, 2020]),
        "tier_definitions": {
            "nws": "Day is inside the official NWS gridded forecast horizon. Values are the actual NWS forecast.",
            "climatology": "Beyond the official forecast horizon. Values are 1991-2020 observed statistics for this calendar date - NOT a forecast.",
        },
        "forecast_aggregation": aggregation,
        "nws_window": {
            "first_day": min(nws_days) if nws_days else None,
            "last_day": max(nws_days) if nws_days else None,
            # How many SCOREBOARD days currently carry a real NWS forecast.
            # This is not the length of the NWS horizon - it is 0 whenever the
            # horizon ends before 1 October, which is the normal case in the
            # off-season.  It used to be called "days_covered" here, next to
            # "horizon_days", which invited reading 0 as "the NWS covers no
            # days".  The names now say which is which.
            "scoreboard_days_in_horizon": sum(1 for e in calendar if e["tier"] == "nws"),
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
        # Metadata only. The per-date published values live on each day, and the
        # raw file body is never copied into the site data (an allow-list, not a
        # blocklist: a future key cannot silently drag a megabyte in with it).
        "daily_normals_official": (
            {k: published_daily_normals.get(k) for k in
             ("station_id", "station_name", "url", "sha256", "bytes",
              "retrieved_utc", "source", "units", "dates_parsed", "layout")
             if published_daily_normals.get(k) is not None}
            if published_daily_normals else None),
        "daily_normals_comparison": daily_normals_comparison,
        "season_summary": dist,
        # Record values from the same 30-season files, each bound to the season
        # that produced it (see climo.build_season_statistics).
        "severity_record": season_climo.get("severity_record", {}),
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
        "afd_language": afd_language,
        "days": calendar,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))

    # Forecast verification loop: archive current forecast snapshot and update verification dataset
    try:
        hist_path = DATA / "forecast_history.json"
        existing_hist = json.loads(hist_path.read_text()) if hist_path.exists() else []
        snap = climo_lib.record_forecast_snapshot(current_forecast)
        updated_hist = climo_lib.update_forecast_history(existing_hist, snap)
        hist_path.write_text(json.dumps(updated_hist, indent=2, default=str))

        # Score forecast history against any available observations
        ghcn_probe_path = DATA / "ghcn_probe.json"
        ghcn_obs = {}
        if ghcn_probe_path.exists():
            try:
                probe = json.loads(ghcn_probe_path.read_text())
                for cand in probe.get("candidates", []):
                    if cand.get("sample_parsed"):
                        ghcn_obs.update(cand["sample_parsed"])
            except Exception:
                pass
        scored = climo_lib.score_forecast_history(updated_hist, ghcn_obs)
        (DATA / "forecast_verification.json").write_text(json.dumps(scored, indent=2, default=str))
    except Exception as exc:  # noqa: BLE001 - verification loop should not block calendar build
        print(f"  forecast verification warning: {exc}")

    n_forecast = out["nws_window"]["scoreboard_days_in_horizon"]
    print(f"  wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    print(f"  {n_forecast} day(s) carry an official NWS forecast; "
          f"{len(calendar) - n_forecast} day(s) show 1991-2020 climatology.")
    print(f"  CPC records attached: {len(cpc_records)} "
          f"({len(seasonal)} seasonal/monthly, {len(short_range)} short-range)")
    if daily_normals_comparison:
        cmp_ = daily_normals_comparison
        print(f"  NOAA published daily normals cross-check over "
              f"{cmp_['compared_dates']} date(s):")
        for label, blk in cmp_["pairs"].items():
            if not blk.get("n"):
                continue
            print(f"    {label}: n={blk['n']} mean diff {blk['mean_difference']} "
                  f"{blk['unit']}, largest |diff| {blk['largest_absolute_difference']} "
                  f"on {blk['largest_difference_date']}")
        if cmp_["flagged"]:
            print(f"    {len(cmp_['flagged'])} date(s) differ by more than 10 "
                  f"percentage points - published, not reconciled")
    else:
        print("  NOAA published daily normals: not available this run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
