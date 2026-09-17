"""Climatology built from official NOAA NCEI archives.

Inputs (all public, free, no API key required):

* GHCN-Daily station file  - daily TMAX / TMIN / PRCP, tenths of degC and mm
  https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/<STATION>.csv
* GSOD station-year files  - daily mean wind, max sustained wind, max gust and
  precipitation for the ASOS at SFO
  https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/<YEAR>/<STATION>.csv
* CPC Niño 3.4 anomaly table - used to stratify wet seasons by ENSO phase
  https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt

Only observed data are used.  No values are interpolated or synthesised; where a
day is missing in the archive it stays missing and is counted as such.
"""

from __future__ import annotations

import csv
import io
import statistics
from collections import defaultdict

MM_PER_INCH = 25.4
KT_TO_MPH = 1.15078

# --------------------------------------------------------------------- utils

def _f(x, ndigits=2):
    if x is None:
        return None
    try:
        return round(float(x), ndigits)
    except (TypeError, ValueError):
        return None


def pct(part, whole, ndigits=1):
    if not whole:
        return None
    return round(100.0 * part / whole, ndigits)


def percentile(values, q):
    """Nearest-rank percentile; *values* need not be sorted."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    k = int(round((q / 100.0) * (len(vals) - 1)))
    k = max(0, min(len(vals) - 1, k))
    return vals[k]


def summarise(values, ndigits=2):
    """Descriptive statistics for a list of numbers (None-safe)."""
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "mean": _f(statistics.fmean(vals), ndigits),
        "median": _f(statistics.median(vals), ndigits),
        "min": _f(min(vals), ndigits),
        "max": _f(max(vals), ndigits),
        "p10": _f(percentile(vals, 10), ndigits),
        "p25": _f(percentile(vals, 25), ndigits),
        "p75": _f(percentile(vals, 75), ndigits),
        "p90": _f(percentile(vals, 90), ndigits),
    }


# ------------------------------------------------------------------ GHCN

GHCN_MISSING = -9999.0
GHCN_ELEMENTS = ("PRCP", "TMAX", "TMIN", "TAVG", "SNOW", "SNWD")


def parse_ghcn_daily(text):
    """Parse a GHCN-Daily station CSV into ``{date_iso: {element: value}}``.

    NCEI serves two different layouts from
    ``/data/global-historical-climatology-network-daily/access/<STATION>.csv``:

    * **wide** (what the station files actually use today) - one row per date
      with a column per element, e.g.::

          "STATION","DATE","LATITUDE","LONGITUDE","ELEVATION","NAME","PRCP",
          "PRCP_ATTRIBUTES","SNOW",...,"TMAX","TMAX_ATTRIBUTES","TMIN",...
          "USW00023272","1921-01-01","37.7705","-122.4269","45.7",
          "SAN FRANCISCO DOWNTOWN, CA US","    0",",,X,2400","    0",...

    * **long** - one row per station/date/element::

          USW00023272,1921-01-01,PRCP,0,,,X,2400

    Both are handled.  Values are space padded and quoted in the wide layout,
    so every value is stripped before conversion.  Raw units are preserved here
    (PRCP = tenths of mm, TMAX/TMIN = tenths of degC, SNOW/SNWD = mm); every
    conversion happens in the caller so it stays explicit and auditable.

    Returns ``(data, format_name)``.
    """
    lines = text.splitlines()
    if not lines:
        return {}, "empty"

    header = next(csv.reader([lines[0]]), [])
    h = [c.strip().strip('"').upper().lstrip("﻿") for c in header]

    # ---------------------------------------------------------- wide format
    if "DATE" in h and "PRCP" in h and ("TMAX" in h or "TMIN" in h):
        idx = {name: i for i, name in enumerate(h)}
        i_date = idx["DATE"]
        i_prcp = idx.get("PRCP")
        i_tmax = idx.get("TMAX")
        i_tmin = idx.get("TMIN")
        i_snow = idx.get("SNOW")
        i_snwd = idx.get("SNWD")

        def val(row, i):
            if i is None or i >= len(row):
                return None
            raw = (row[i] or "").strip().strip('"').strip()
            if raw in ("", "nan"):
                return None
            try:
                v = float(raw)
            except ValueError:
                return None
            return None if v == GHCN_MISSING else v

        out = {}
        for row in csv.reader(lines[1:]):
            if not row or i_date >= len(row):
                continue
            date = (row[i_date] or "").strip().strip('"').strip()
            if len(date) != 10:
                continue
            out[date] = {
                "PRCP": val(row, i_prcp),
                "TMAX": val(row, i_tmax),
                "TMIN": val(row, i_tmin),
                "SNOW": val(row, i_snow),
                "SNWD": val(row, i_snwd),
            }
        return out, "wide"

    # ---------------------------------------------------------- long format
    out = defaultdict(dict)
    for row in csv.reader(lines[1:]):
        if len(row) < 4:
            continue
        _sid, date, element, value = row[0], row[1], row[2], row[3]
        if len(date) != 10 or element not in GHCN_ELEMENTS:
            continue
        try:
            v = float(value)
        except ValueError:
            continue
        if v == GHCN_MISSING:
            v = None
        out[date][element] = v
    return dict(out), "long"


def ghcn_to_inches(tenths_mm):
    """GHCN PRCP is tenths of a millimetre."""
    return None if tenths_mm is None else tenths_mm * 0.1 / MM_PER_INCH


def ghcn_to_f(tenths_c):
    """GHCN TMAX/TMIN are tenths of a degree Celsius."""
    return None if tenths_c is None else tenths_c / 10.0 * 9.0 / 5.0 + 32.0


# ------------------------------------------------------------------- GSOD

# Unit convention verified against the official NCEI GSOD README
# (https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt):
# every element in the *CSV* access files is already stored in decimal units -
# "TEMP ... degrees Fahrenheit to tenths. Missing = 9999.9", "WDSP ... knots to
# tenths. Missing = 999.9", "PRCP ... (.01 inches)".  The parenthetical is the
# reporting PRECISION, not a multiplier, so no scaling is applied below.
#
# Caveat recorded in the same README: "The data are reported and summarized
# based on Greenwich Mean Time (GMT, 0000Z - 2359Z)".  A GSOD day is therefore
# a UTC day, i.e. 16:00-16:00 local time in San Francisco, not a local day.
GSOD_MISSING = {"WDSP": 999.9, "MXSPD": 999.9, "GUST": 999.9,
                "PRCP": 99.99, "MAX": 9999.9, "MIN": 9999.9, "TEMP": 9999.9}
GSOD_README_URL = "https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt"
GSOD_SCALE = 1.0


def _split_gsod_row(row, n_fields, name_idx):
    """Repair a GSOD row whose NAME field contains unquoted commas.

    NCEI writes the station NAME unquoted, e.g.
    ``72494023234,2020-01-01,...,SAN FRANCISCO INTERNATIONAL AIRPORT, CA US,...``
    so the row arrives with more fields than the header.  The surplus fields
    belong to NAME and are rejoined here.
    """
    if len(row) == n_fields:
        return row
    if len(row) > n_fields:
        extra = len(row) - n_fields
        return row[:name_idx] + [", ".join(p.strip() for p in row[name_idx:name_idx + extra + 1])] + row[name_idx + extra + 1:]
    return None


def parse_gsod(text):
    """Parse one GSOD station-year CSV into a list of daily dicts.

    GSOD CSV units (see GSOD_README_URL): WDSP/MXSPD/GUST in knots, PRCP in
    inches, MAX/MIN/TEMP in degrees Fahrenheit.  Missing values are all-9s.
    """
    lines = text.splitlines()
    if not lines:
        return []
    header = next(csv.reader([lines[0]]), [])
    if not header:
        return []
    header = [h.strip().lstrip("﻿") for h in header]
    n_fields = len(header)
    try:
        name_idx = header.index("NAME")
    except ValueError:
        name_idx = 5

    def col(name):
        return header.index(name) if name in header else None

    i_date, i_wdsp = col("DATE"), col("WDSP")
    i_mxspd, i_gust = col("MXSPD"), col("GUST")
    i_prcp, i_max, i_min = col("PRCP"), col("MAX"), col("MIN")

    def num(row, index, scale, missing):
        if index is None or index >= len(row):
            return None
        raw = (row[index] or "").strip()
        if raw in ("", "nan"):
            return None
        try:
            v = float(raw)
        except ValueError:
            return None
        if abs(v - missing) < 1e-6:
            return None
        return v * scale

    rows = []
    for raw in csv.reader(lines[1:]):
        if not raw or (i_date is not None and i_date >= len(raw)):
            continue
        row = _split_gsod_row(raw, n_fields, name_idx)
        if row is None or (i_date is not None and len(row) != n_fields):
            continue
        date = (row[i_date] or "").strip() if i_date is not None else ""
        if len(date) != 10:
            continue
        rows.append({
            "date": date,
            "wind_kt": num(row, i_wdsp, GSOD_SCALE, GSOD_MISSING["WDSP"]),        # knots
            "max_wind_kt": num(row, i_mxspd, GSOD_SCALE, GSOD_MISSING["MXSPD"]),  # knots
            "gust_kt": num(row, i_gust, GSOD_SCALE, GSOD_MISSING["GUST"]),        # knots
            "prcp_in": num(row, i_prcp, GSOD_SCALE, GSOD_MISSING["PRCP"]),        # inches
            "max_f": num(row, i_max, GSOD_SCALE, GSOD_MISSING["MAX"]),
            "min_f": num(row, i_min, GSOD_SCALE, GSOD_MISSING["MIN"]),
        })
    return rows


# -------------------------------------------------------------- ENSO / ONI

def parse_nino34(text):
    """Parse CPC's detrended Niño 3.4 ASCII table -> ``{(y, m): anomaly}``."""
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            y, m, _total, _clim, anom = int(parts[0]), int(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
        except ValueError:
            continue
        out[(y, m)] = anom
    return out


def oni_running_means(nino, year, month):
    """ONI = 3-month running mean of Niño 3.4 anomalies centred on *month*."""
    series = {}
    for (y, m), anom in sorted(nino.items()):
        trio = []
        for k in (-1, 0, 1):
            mm, yy = m + k, y
            while mm < 1:
                mm += 12
                yy -= 1
            while mm > 12:
                mm -= 12
                yy += 1
            if (yy, mm) in nino:
                trio.append(nino[(yy, mm)])
        if len(trio) == 3:
            series[(y, m)] = sum(trio) / 3.0
    return series


def enso_phase(oni_value):
    if oni_value is None:
        return "unknown"
    if oni_value >= 0.5:
        return "el_nino"
    if oni_value <= -0.5:
        return "la_nina"
    return "neutral"


# ------------------------------------------------------------- statistics

def build_daily_climatology(ghcn, gsod_by_date, season_month_days, period):
    """Per calendar-date statistics across Oct 1 - Jan 31.

    ``season_month_days`` is an ordered list of ``(month, day)`` tuples.
    ``period`` is ``(start_year, end_year)`` inclusive, applied to the season
    *starting* year.
    """
    y0, y1 = period
    ghcn_by_md = defaultdict(lambda: {"tmax": [], "tmin": [], "prcp": [], "years": [], "records": []})
    gsod_by_md = defaultdict(lambda: {"wind": [], "maxwind": [], "gust": [], "prcp": [],
                                      "gust_max_record": (None, None)})

    for (month, day) in season_month_days:
        mmdd = f"{month:02d}-{day:02d}"
        for season_year in range(y0, y1 + 1):
            # Season Oct <season_year> .. Jan <season_year+1>
            year = season_year if month >= 10 else season_year + 1
            iso = f"{year:04d}-{mmdd}"

            rec = ghcn.get(iso)
            if rec is not None:
                g = ghcn_by_md[mmdd]
                g["years"].append(year)
                tmax = ghcn_to_f(rec.get("TMAX"))
                tmin = ghcn_to_f(rec.get("TMIN"))
                prcp = ghcn_to_inches(rec.get("PRCP"))
                g["tmax"].append(tmax)
                g["tmin"].append(tmin)
                g["prcp"].append(prcp)
                g["records"].append({"year": year, "prcp_in": _f(prcp, 3),
                                     "tmax_f": _f(tmax, 1), "tmin_f": _f(tmin, 1)})

            s = gsod_by_date.get(iso)
            if s is not None:
                d = gsod_by_md[mmdd]
                d["wind"].append(s["wind_kt"])
                d["maxwind"].append(s["max_wind_kt"])
                d["gust"].append(s["gust_kt"])
                d["prcp"].append(s["prcp_in"])
                if s["gust_kt"] is not None:
                    cur = d["gust_max_record"][0]
                    if cur is None or s["gust_kt"] > cur:
                        d["gust_max_record"] = (s["gust_kt"], iso)

    daily = []
    for (month, day) in season_month_days:
        mmdd = f"{month:02d}-{day:02d}"
        g = ghcn_by_md.get(mmdd, {"tmax": [], "tmin": [], "prcp": [], "years": [], "records": []})
        d = gsod_by_md.get(mmdd, {"wind": [], "maxwind": [], "gust": [], "prcp": [],
                                  "gust_max_record": (None, None)})

        prcp = [p for p in g["prcp"] if p is not None]
        n_p = len(prcp)
        wet = [p for p in prcp if p >= 0.01]
        n_gsod_prcp = len([p for p in d["prcp"] if p is not None])
        n_gsod_wind = len([v for v in d["maxwind"] if v is not None])

        # joint wind + rain pairs (only days where both are present)
        pairs = [(p, w, gu) for p, w, gu in zip(d["prcp"], d["maxwind"], d["gust"])
                 if p is not None and w is not None]
        n_pairs = len(pairs)
        windrain = sum(1 for p, w, _g in pairs if p >= 0.01 and w >= 20.0)
        windrain_heavy = sum(1 for p, w, g2 in pairs
                             if p >= 0.50 and (g2 is not None and g2 >= 35.0))

        gusts = [v for v in d["gust"] if v is not None]
        rec_gust, rec_gust_date = d["gust_max_record"]

        top_wettest = sorted([r for r in g["records"] if r["prcp_in"] is not None],
                             key=lambda r: -r["prcp_in"])[:3]

        daily.append({
            "mmdd": mmdd,
            "month": month,
            "day": day,
            "n_years_precip": n_p,
            "n_years_temp": len([v for v in g["tmax"] if v is not None]),
            "normal_high_f": _f(statistics.fmean([v for v in g["tmax"] if v is not None]), 1)
            if any(v is not None for v in g["tmax"]) else None,
            "normal_low_f": _f(statistics.fmean([v for v in g["tmin"] if v is not None]), 1)
            if any(v is not None for v in g["tmin"]) else None,
            "record_high_f": _f(max([v for v in g["tmax"] if v is not None]), 1)
            if any(v is not None for v in g["tmax"]) else None,
            "record_low_f": _f(min([v for v in g["tmin"] if v is not None]), 1)
            if any(v is not None for v in g["tmin"]) else None,
            "p_rain_day_pct": pct(len(wet), n_p),
            "p_rain_ge_025in_pct": pct(sum(1 for p in prcp if p >= 0.25), n_p),
            "p_rain_ge_100in_pct": pct(sum(1 for p in prcp if p >= 1.00), n_p),
            "mean_daily_prcp_in": _f(statistics.fmean(prcp), 3) if prcp else None,
            "median_wet_day_prcp_in": _f(statistics.median(wet), 3) if wet else None,
            "max_daily_prcp_in": _f(max(prcp), 3) if prcp else None,
            "wettest_on_record": [{"year": r["year"], "prcp_in": r["prcp_in"]} for r in top_wettest],
            # wind (SFO ASOS)
            "n_years_wind": n_gsod_wind,
            "normal_mean_wind_mph": _f(statistics.fmean([v for v in d["wind"] if v is not None]) * KT_TO_MPH, 1)
            if any(v is not None for v in d["wind"]) else None,
            "normal_max_sustained_mph": _f(statistics.fmean([v for v in d["maxwind"] if v is not None]) * KT_TO_MPH, 1)
            if any(v is not None for v in d["maxwind"]) else None,
            "normal_max_gust_mph": _f(statistics.fmean([v for v in gusts if v is not None]) * KT_TO_MPH, 1)
            if gusts else None,
            "max_gust_on_record_mph": _f(rec_gust * KT_TO_MPH, 1) if rec_gust is not None else None,
            "max_gust_on_record_date": rec_gust_date,
            "p_gust_ge_25kt_pct": pct(sum(1 for v in gusts if v >= 25), len(gusts)),
            "p_gust_ge_35kt_pct": pct(sum(1 for v in gusts if v >= 35), len(gusts)),
            "p_gust_ge_45kt_pct": pct(sum(1 for v in gusts if v >= 45), len(gusts)),
            "n_years_joint": n_pairs,
            "p_wind_and_rain_pct": pct(windrain, n_pairs),
            "p_heavy_wind_and_rain_pct": pct(windrain_heavy, n_pairs),
            "n_years_gsod_prcp": n_gsod_prcp,
        })
    return daily


def build_season_statistics(ghcn, gsod_by_date, season_month_days, period, oni_series):
    """Year-by-year wet-season statistics plus their distribution.

    A season is Oct 1 (year Y) through Jan 31 (year Y+1).
    """
    y0, y1 = period
    seasons = []
    for season_year in range(y0, y1 + 1):
        dates = []
        for (month, day) in season_month_days:
            year = season_year if month >= 10 else season_year + 1
            dates.append(f"{year:04d}-{month:02d}-{day:02d}")

        prcp_series, missing = [], 0
        for iso in dates:
            rec = ghcn.get(iso)
            if rec is None:
                missing += 1
                prcp_series.append(None)
                continue
            prcp_series.append(ghcn_to_inches(rec.get("PRCP")))

        wet_flags = [1 if (p is not None and p >= 0.01) else 0 for p in prcp_series]

        # consecutive wet-day runs
        runs, cur = [], 0
        for f in wet_flags:
            if f:
                cur += 1
            else:
                if cur:
                    runs.append(cur)
                cur = 0
        if cur:
            runs.append(cur)

        monthly = {}
        for month in (10, 11, 12, 1):
            tot = 0.0
            have = False
            for iso in dates:
                if int(iso[5:7]) != month:
                    continue
                rec = ghcn.get(iso)
                if rec is None:
                    continue
                p = ghcn_to_inches(rec.get("PRCP"))
                if p is not None:
                    tot += p
                    have = True
            monthly[f"{month:02d}"] = _f(tot, 2) if have else None

        total = sum(p for p in prcp_series if p is not None)
        # wind + rain days for this season (SFO ASOS)
        jr, heavy_jr, max_gust = 0, 0, None
        for iso in dates:
            s = gsod_by_date.get(iso)
            if not s:
                continue
            p, w, g = s["prcp_in"], s["max_wind_kt"], s["gust_kt"]
            if p is not None and w is not None and p >= 0.01 and w >= 20.0:
                jr += 1
            if p is not None and g is not None and p >= 0.50 and g >= 35.0:
                heavy_jr += 1
            if g is not None and (max_gust is None or g > max_gust):
                max_gust = g

        # ENSO phase: use the Oct-Nov-Dec ONI of the season start year
        oni_key = (season_year, 11)
        oni = oni_series.get(oni_key)
        seasons.append({
            "season": f"{season_year}-{season_year + 1}",
            "total_prcp_in": _f(total, 2),
            "wet_days": sum(wet_flags),
            "missing_days": missing,
            "longest_wet_streak_days": max(runs) if runs else 0,
            "n_wet_streaks": len(runs),
            "streaks_ge_3": sum(1 for r in runs if r >= 3),
            "streaks_ge_5": sum(1 for r in runs if r >= 5),
            "streaks_ge_7": sum(1 for r in runs if r >= 7),
            "streaks_ge_10": sum(1 for r in runs if r >= 10),
            "monthly_prcp_in": monthly,
            "wind_and_rain_days": jr,
            "heavy_wind_and_rain_days": heavy_jr,
            "max_gust_kt": _f(max_gust, 1) if max_gust is not None else None,
            "max_gust_mph": _f(max_gust * KT_TO_MPH, 1) if max_gust is not None else None,
            "oni_ond": _f(oni, 2),
            "enso_phase": enso_phase(oni),
        })

    totals = [s["total_prcp_in"] for s in seasons if s["total_prcp_in"] is not None]
    oct_tot = [s["monthly_prcp_in"]["10"] for s in seasons if s["monthly_prcp_in"].get("10") is not None]
    nov_tot = [s["monthly_prcp_in"]["11"] for s in seasons if s["monthly_prcp_in"].get("11") is not None]
    dec_tot = [s["monthly_prcp_in"]["12"] for s in seasons if s["monthly_prcp_in"].get("12") is not None]
    jan_tot = [s["monthly_prcp_in"]["01"] for s in seasons if s["monthly_prcp_in"].get("01") is not None]

    ranked = sorted([s for s in seasons if s["total_prcp_in"] is not None],
                    key=lambda s: s["total_prcp_in"])

    by_phase = defaultdict(list)
    for s in seasons:
        if s["total_prcp_in"] is not None:
            by_phase[s["enso_phase"]].append(s["total_prcp_in"])

    n_seasons = len(seasons)
    return {
        "seasons": seasons,
        "distribution": {
            "season_total_prcp_in": summarise(totals, 2),
            "october_total_prcp_in": summarise(oct_tot, 2),
            "november_total_prcp_in": summarise(nov_tot, 2),
            "december_total_prcp_in": summarise(dec_tot, 2),
            "january_total_prcp_in": summarise(jan_tot, 2),
            "wet_days": summarise([s["wet_days"] for s in seasons], 1),
            "longest_wet_streak_days": summarise([s["longest_wet_streak_days"] for s in seasons], 1),
            "wind_and_rain_days": summarise([s["wind_and_rain_days"] for s in seasons], 1),
            "heavy_wind_and_rain_days": summarise([s["heavy_wind_and_rain_days"] for s in seasons], 1),
            "max_gust_mph": summarise([s["max_gust_mph"] for s in seasons], 1),
        },
        "probability_of_at_least_one_streak": {
            "ge_3_days": {"seasons": sum(1 for s in seasons if s["streaks_ge_3"] >= 1),
                          "pct": pct(sum(1 for s in seasons if s["streaks_ge_3"] >= 1), n_seasons)},
            "ge_5_days": {"seasons": sum(1 for s in seasons if s["streaks_ge_5"] >= 1),
                          "pct": pct(sum(1 for s in seasons if s["streaks_ge_5"] >= 1), n_seasons)},
            "ge_7_days": {"seasons": sum(1 for s in seasons if s["streaks_ge_7"] >= 1),
                          "pct": pct(sum(1 for s in seasons if s["streaks_ge_7"] >= 1), n_seasons)},
            "ge_10_days": {"seasons": sum(1 for s in seasons if s["streaks_ge_10"] >= 1),
                           "pct": pct(sum(1 for s in seasons if s["streaks_ge_10"] >= 1), n_seasons)},
        },
        "enso_stratified_season_total_prcp_in": {
            phase: summarise(vals, 2) for phase, vals in sorted(by_phase.items())
        },
        "wettest_seasons": [{"season": s["season"], "total_prcp_in": s["total_prcp_in"]}
                            for s in ranked[-5:]][::-1],
        "driest_seasons": [{"season": s["season"], "total_prcp_in": s["total_prcp_in"]}
                           for s in ranked[:5]],
    }
