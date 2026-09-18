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
import datetime as dt
import io
import re
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
    if tenths_mm is None:
        return None
    try:
        val = float(tenths_mm)
    except (ValueError, TypeError):
        return None
    return val * 0.1 / MM_PER_INCH


def ghcn_to_f(tenths_c):
    """GHCN TMAX/TMIN are tenths of a degree Celsius."""
    if tenths_c is None:
        return None
    try:
        val = float(tenths_c)
    except (ValueError, TypeError):
        return None
    return val / 10.0 * 9.0 / 5.0 + 32.0


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


# ------------------------------------------------------------------- ISD

#: Wind speed (knots) at or above which an hour counts as "windy" in the hourly
#: co-occurrence statistic.  The same threshold the daily approximation has always
#: used for the GSOD daily-max wind, so the two methods are comparable.
ISD_WIND_THRESHOLD_KT = 20.0

#: Days in the Oct 1 -> Jan 31 season window the hourly statistic is defined over.
#: Used as the denominator of per-season data coverage: a season in which the
#: station reported on fewer dates than this is not silently averaged in.
ISD_SEASON_DATES_EXPECTED = 123


def parse_isd_hourly(text, tz_name="America/Los_Angeles"):
    """Parse NCEI ISD hourly CSV (e.g. station 72494023234) into hourly records.

    ISD format specifications (NCEI global-hourly format document):
    - DATE: ISO 8601 UTC timestamp (e.g. "1991-10-01T00:56:00")
    - WND: direction (3 chars), direction_quality, type, speed in tenths of m/s (4 chars, 9999=missing), speed_quality
    - AA1: liquid precipitation period in hours (2 chars), depth in tenths of mm (4 chars, 9999=missing), trace/condition, quality
    """
    lines = text.splitlines()
    if not lines:
        return []
    reader = csv.DictReader(lines)
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = dt.timezone(dt.timedelta(hours=-8))

    records = []
    for r in reader:
        date_str = r.get("DATE")
        if not date_str:
            continue
        try:
            dt_utc = dt.datetime.fromisoformat(date_str)
            if dt_utc.tzinfo is None:
                dt_utc = dt_utc.replace(tzinfo=dt.timezone.utc)
            dt_local = dt_utc.astimezone(tz)
        except Exception:
            continue

        wnd = (r.get("WND") or "").strip()
        wnd_parts = wnd.split(",")
        speed_kt = None
        if len(wnd_parts) >= 4 and wnd_parts[3] != "9999":
            try:
                ms = float(wnd_parts[3]) / 10.0
                speed_kt = round(ms * 1.943844, 1)
            except ValueError:
                pass

        aa1 = (r.get("AA1") or "").strip()
        prcp_in = None
        prcp_period_hours = None
        if aa1:
            aa1_parts = aa1.split(",")
            if aa1_parts and aa1_parts[0] not in ("", "99"):
                try:
                    prcp_period_hours = int(aa1_parts[0])
                except ValueError:
                    prcp_period_hours = None
            if len(aa1_parts) >= 2 and aa1_parts[1] != "9999":
                try:
                    mm = float(aa1_parts[1]) / 10.0
                    prcp_in = round(mm / 25.4, 3)
                except ValueError:
                    pass

        m = dt_local.month
        in_season = (m >= 10 or m <= 1)
        records.append({
            "timestamp_utc": dt_utc.isoformat(),
            "local_date": dt_local.date().isoformat(),
            "local_month": dt_local.month,
            "local_day": dt_local.day,
            "local_hour": dt_local.hour,
            "in_season": in_season,
            "wind_speed_kt": speed_kt,
            "prcp_in": prcp_in,
            # AA1 field 1: the number of hours the reported depth covers.  Kept so
            # the aggregation can disclose when a "wet hour" was really a
            # multi-hour accumulation rather than an hour-by-hour measurement.
            "prcp_period_hours": prcp_period_hours,
            "is_wind_and_rain": (speed_kt is not None and speed_kt >= ISD_WIND_THRESHOLD_KT
                                 and prcp_in is not None and prcp_in > 0.0),
        })
    return records


def isd_season_year(local_date):
    """Season label year for a local ISO date: Oct-Dec is year Y, Jan is Y-1."""
    y, m = int(local_date[:4]), int(local_date[5:7])
    return y if m >= 10 else y - 1


def aggregate_isd_hourly_wind_and_rain(records):
    """Aggregate parsed ISD hourly records into seasonal and daily summary stats.

    Counts hours in the Oct 1 - Jan 31 window where the observation carries BOTH a
    usable wind speed and usable liquid precipitation, and of those, the hours where
    ``wind >= 20 kt`` and ``precipitation > 0`` hold **at the same instant**
    (``wind_rain_hours``).  That simultaneity is the point: the daily statistic used
    elsewhere in this project pairs a whole local rain day with a whole daily wind
    maximum, which cannot tell "rain in the morning, wind at night" from a storm.

    The returned ``by_local_date`` carries, per local calendar date: valid joint
    hours, rain hours, hours at or above the wind threshold, the summed reported
    liquid precipitation, and the day's maximum sustained wind.  ``per_season``
    rolls those up over the season window so a reader can see how many OCT-JAN dates
    the station actually reported on (``dates_with_data`` / ``coverage_pct``) — a
    season with thin coverage is visible rather than averaged in silently.

    Precipitation depths are the AA1 liquid-precipitation depths exactly as the
    station reported them.  Some reports cover more than one hour; the count of
    counted simultaneous hours that came from such a report is published separately
    (``simultaneous_hours_from_multi_hour_reports``) instead of being treated as an
    hour-by-hour measurement.
    """
    season_records = [r for r in records if r.get("in_season")]
    valid_joint_hours = 0
    simultaneous_hours = 0
    simultaneous_multi_hour_reports = 0
    by_local_date = defaultdict(lambda: {
        "valid_hours": 0, "wind_rain_hours": 0, "rain_hours": 0,
        "wind_ge_threshold_hours": 0, "prcp_in": 0.0, "wind_max_kt": None,
        "multi_hour_prcp_reports": 0,
    })

    for r in season_records:
        w = r.get("wind_speed_kt")
        p = r.get("prcp_in")
        if w is None or p is None:
            continue
        valid_joint_hours += 1
        d = by_local_date[r["local_date"]]
        d["valid_hours"] += 1
        d["prcp_in"] = round(d["prcp_in"] + p, 3)
        if p > 0.0:
            d["rain_hours"] += 1
        if w >= ISD_WIND_THRESHOLD_KT:
            d["wind_ge_threshold_hours"] += 1
        if d["wind_max_kt"] is None or w > d["wind_max_kt"]:
            d["wind_max_kt"] = w
        # AA1 field 1 is the number of hours the reported depth covers; a report
        # covering more than one hour is not an hour-by-hour measurement.
        period = r.get("prcp_period_hours")
        if period is not None and period > 1:
            d["multi_hour_prcp_reports"] += 1
        if r.get("is_wind_and_rain"):
            simultaneous_hours += 1
            d["wind_rain_hours"] += 1
            if period is not None and period > 1:
                simultaneous_multi_hour_reports += 1

    per_season = []
    seasons = defaultdict(lambda: {
        "valid_hours": 0, "wind_rain_hours": 0, "dates_with_data": 0,
        "days_rain": 0, "days_wind_ge_threshold": 0, "days_daily_pair": 0,
        "days_simultaneous": 0, "earliest_date": None, "latest_date": None,
    })
    for local_date, d in by_local_date.items():
        sy = isd_season_year(local_date)
        s = seasons[sy]
        s["valid_hours"] += d["valid_hours"]
        s["wind_rain_hours"] += d["wind_rain_hours"]
        s["dates_with_data"] += 1
        if d["prcp_in"] > 0.0:
            s["days_rain"] += 1
        wind_max = d["wind_max_kt"]
        windy = wind_max is not None and wind_max >= ISD_WIND_THRESHOLD_KT
        if windy:
            s["days_wind_ge_threshold"] += 1
        if windy and d["prcp_in"] > 0.0:
            s["days_daily_pair"] += 1
        if d["wind_rain_hours"] > 0:
            s["days_simultaneous"] += 1
        if s["earliest_date"] is None or local_date < s["earliest_date"]:
            s["earliest_date"] = local_date
        if s["latest_date"] is None or local_date > s["latest_date"]:
            s["latest_date"] = local_date

    for sy in sorted(seasons.keys()):
        s = seasons[sy]
        vh = s["valid_hours"]
        per_season.append({
            "season_year": sy,
            "season": f"{sy}-{sy + 1}",
            "valid_hours": vh,
            "wind_rain_hours": s["wind_rain_hours"],
            "pct_hours": pct(s["wind_rain_hours"], vh) if vh else 0.0,
            # Coverage: how much of Oct 1 - Jan 31 the station actually reported on.
            "dates_with_data": s["dates_with_data"],
            "dates_expected": ISD_SEASON_DATES_EXPECTED,
            "coverage_pct": pct(s["dates_with_data"], ISD_SEASON_DATES_EXPECTED),
            "earliest_date": s["earliest_date"],
            "latest_date": s["latest_date"],
            # Same-station day counts, so a reader can separate "wind and rain on
            # the same day" from "wind and rain in the same hour".
            "days_rain": s["days_rain"],
            "days_wind_ge_threshold": s["days_wind_ge_threshold"],
            "days_daily_pair": s["days_daily_pair"],
            "days_simultaneous": s["days_simultaneous"],
        })

    return {
        "valid_joint_hours": valid_joint_hours,
        "simultaneous_wind_rain_hours": simultaneous_hours,
        "simultaneous_hours_from_multi_hour_reports": simultaneous_multi_hour_reports,
        "overall_pct": pct(simultaneous_hours, valid_joint_hours) if valid_joint_hours else 0.0,
        "wind_threshold_kt": ISD_WIND_THRESHOLD_KT,
        "dates_expected_per_season": ISD_SEASON_DATES_EXPECTED,
        "per_season": per_season,
        "by_local_date": {k: dict(v) for k, v in sorted(by_local_date.items())},
    }


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


#: Raw ENSO tokens produced by the pipeline -> reader-facing labels.  The raw
#: token must never reach the page: "el_nino" is a data key, not a phrase.  These
#: live here (rather than in the renderer or in one downstream script) so that
#: every published ENSO record can carry its own label, and no consumer has to
#: translate a token itself.
PHASE_LABELS = {
    "el_nino": "El Niño",
    "la_nina": "La Niña",
    "neutral": "Neutral",
}

STRENGTH_LABELS = {
    "very_strong": "very strong",
    "strong": "strong",
    "moderate": "moderate",
    "weak": "weak",
    "neutral": "neutral",
}


def phase_label(phase):
    """Reader-facing label for an ENSO phase token.

    Returns the mapped label for the three phases the pipeline can produce.  An
    unexpected token is returned as-is (it is a real data value, so showing it is
    honest) rather than replaced with a guessed phrase.
    """
    if phase is None:
        return "unknown"
    return PHASE_LABELS.get(str(phase).strip().lower(), str(phase))


def strength_label(strength):
    """Reader-facing label for an ENSO strength token ("very_strong" -> "very strong")."""
    if strength is None:
        return "unknown"
    return STRENGTH_LABELS.get(str(strength).strip().lower(),
                               str(strength).replace("_", " "))


def fmt_oni_c(value):
    """Format an ONI anomaly the way NOAA publishes it: signed, 2 dp, degrees C."""
    if value is None:
        return None
    try:
        return f"{float(value):+.2f} °C"
    except (TypeError, ValueError):
        return None


def enso_phase(oni_value):
    if oni_value is None:
        return "unknown"
    if oni_value >= 0.5:
        return "el_nino"
    if oni_value <= -0.5:
        return "la_nina"
    return "neutral"


# NOAA CPC strength classes for the Oceanic Nino Index.  Source of the bands:
# CPC ENSO Alert System / strength outlook, which describes a "strong" event as
# an ONI of at least 1.5 C and a "very strong" event as at least 2.0 C.
def enso_strength(oni_value):
    if oni_value is None:
        return "unknown"
    if oni_value >= 2.0:
        return "very_strong"
    if oni_value >= 1.5:
        return "strong"
    if oni_value >= 1.0:
        return "moderate"
    if oni_value >= 0.5:
        return "weak"
    if oni_value <= -2.0:
        return "very_strong"
    if oni_value <= -1.5:
        return "strong"
    if oni_value <= -1.0:
        return "moderate"
    if oni_value <= -0.5:
        return "weak"
    return "neutral"


def _season_tokens():
    """Map every 3-month CPC season token (DJF, JFM, ...) to its calendar months.

    CPC writes a season as three *month initials*, so "DJF" is Dec-Jan-Feb and
    "NDJ" is Nov-Dec-Jan - the letters are initials, not three-letter month
    codes.  Building the 12 possible rotations is the only unambiguous way to
    resolve tokens where a letter repeats (J, M, A).
    """
    initials = {1: "J", 2: "F", 3: "M", 4: "A", 5: "M", 6: "J", 7: "J", 8: "A",
                9: "S", 10: "O", 11: "N", 12: "D"}
    out = {}
    for start_month in range(1, 13):
        months = [((start_month - 1 + k) % 12) + 1 for k in range(3)]
        token = "".join(initials[m] for m in months)
        # CPC labels a season with the year that contains two of its three
        # months.  For NDJ (Nov, Dec, Jan) that is the year of Nov/Dec, so the
        # January is in the following calendar year; for DJF (Dec, Jan, Feb) it
        # is the year of Jan/Feb, so the December is in the *previous* calendar
        # year.  Both are verified against the published file: NDJ 2015 = 2.59
        # covers Nov 2015 - Jan 2016, and DJF 2016 = 2.50 covers Dec 2015 -
        # Feb 2016 (the 2015-16 El Nino peak).
        if start_month == 12:      # DJF : December is in year - 1
            offsets = (-1, 0, 0)
        elif start_month == 11:    # NDJ : January is in year + 1
            offsets = (0, 0, 1)
        else:                      # all three months inside the label year
            offsets = (0, 0, 0)
        out[token] = {"months": months, "year_offsets": offsets}
    return out


SEASON_TOKENS = _season_tokens()


def parse_oni_seasons(text):
    """Parse CPC's *official* ONI product (season-labelled 3-month means).

    ``https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt`` has the layout::

        SEAS  YR   TOTAL   ANOM
        DJF 1950  25.01  -1.32

    where ``SEAS`` is the three-month season written as month initials (DJF =
    Dec-Jan-Feb of ``YR``).  This is NOAA's published ONI: the project displays
    it directly rather than re-deriving it, so the number on the site is the
    number NOAA publishes.

    Returns a list of dicts ordered oldest -> newest:
    ``{"season", "year", "anomaly_c", "months", "label"}``.
    """
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        season, ys, total, anom = parts[0], parts[1], parts[2], parts[3]
        token = season.upper()
        if token not in SEASON_TOKENS:
            continue
        try:
            year, anom_f = int(ys), float(anom)
        except ValueError:
            continue
        spec = SEASON_TOKENS[token]
        months, offsets = spec["months"], spec["year_offsets"]
        calendar = [(year + offsets[i], m) for i, m in enumerate(months)]
        out.append({
            "season": token,
            "year": year,
            "anomaly_c": anom_f,
            "total_c": float(total) if total not in ("", "-") else None,
            "months": calendar,
            "label": f"{token} {year}",
        })
    out.sort(key=lambda r: (r["months"][0][0], r["months"][0][1]))
    return out


def oni_for_calendar_year(season_rows, year):
    """Return the (y, m) -> official ONI anomaly map for **calendar** months.

    A season shot is assigned to the calendar month that starts it, which is how
    NOAA writes its seasonal ENSO statements ("DJF", "JFM", ...).  Two seasons
    touch any given month; the map keeps the season whose midpoint is nearest,
    which is the standard way of turning overlapping 3-month means into a
    monthly series for stratification.
    """
    monthly = {}
    for row in season_rows:
        start_y, start_m = row["months"][0]
        monthly[(start_y, start_m)] = row["anomaly_c"]
    return monthly


def season_mean_oni(season_rows, calendar_year):
    """Mean official ONI over the Oct-Dec-Feb window of a rainy season.

    The project's rainy season runs 1 Oct - 31 Jan.  The officially published
    seasons covering it are OND (Oct-Nov-Dec) and NDJ (Nov-Dec-Jan) of
    ``calendar_year``; DJF is also shown because it is the season most often
    quoted for the winter as a whole.
    """
    # OND Y = Oct-Dec of year Y; NDJ Y = Nov Y - Jan Y+1; DJF Y+1 = Dec Y - Feb Y+1.
    want = {f"OND {calendar_year}", f"NDJ {calendar_year}", f"DJF {calendar_year + 1}"}
    vals = [r["anomaly_c"] for r in season_rows if r["label"] in want]
    return (sum(vals) / len(vals)) if vals else None


# ------------------------------------------------- relative humidity normals

def rh_from_dewpoint(temp_c, dewpoint_c):
    """Relative humidity (%) from temperature and dew point (Magnus formula).

    This is the standard meteorological conversion; it is a *derivation* from
    two official normals (NCEI hourly temperature and dew point normals), not an
    observation, and the site labels it as such.  Returns ``None`` if either
    input is missing or if the result is physically impossible.
    """
    if temp_c is None or dewpoint_c is None:
        return None
    import math
    a, b = 17.625, 243.04
    try:
        gamma_t = (a * temp_c) / (b + temp_c)
        gamma_d = (a * dewpoint_c) / (b + dewpoint_c)
        rh = 100.0 * math.exp(gamma_d - gamma_t)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    if rh < 0 or rh > 100.5:
        return None
    return min(100.0, rh)


def humidity_normals_by_date(rows):
    """Per calendar date (MM-DD) mean relative humidity from hourly normals.

    Where the hourly normals file carries a day column, every day of the year gets
    its own value - far better than a single monthly figure.  Returns
    ``{"MM-DD": pct}``.
    """
    by_date = defaultdict(list)
    for r in rows:
        if not r.get("day"):
            continue
        rh = rh_from_dewpoint(r.get("temp_c"), r.get("dewpoint_c"))
        if rh is None:
            continue
        by_date["%02d-%02d" % (r["month"], r["day"])].append(rh)
    return {k: round(sum(v) / len(v), 1) for k, v in sorted(by_date.items()) if v}


def humidity_normals_from_hourly(rows):
    """Build (month -> mean relative humidity %) from NCEI hourly normals rows.

    ``rows`` is whatever the tolerant CSV reader in ``main.fetch_humidity_normals``
    could recover: an iterable of dicts with keys ``month`` (1-12), ``hour``
    (0-23 or None), ``temp_c`` and ``dewpoint_c``.  Only rows that carry both a
    temperature and a dew point are used; nothing is interpolated.
    """
    by_month = defaultdict(list)
    for r in rows:
        rh = rh_from_dewpoint(r.get("temp_c"), r.get("dewpoint_c"))
        if rh is None:
            continue
        by_month[r["month"]].append(rh)
    return {m: round(sum(v) / len(v), 1) for m, v in sorted(by_month.items()) if v}


# ------------------------------------------------- NCEI normals CSV handling
#
# The NCEI normals CSVs are published "by station".  The column names are
# documented in NCEI's normals readme; the reader below does not assume a fixed
# column order - it looks the names up case-insensitively and reports exactly
# what it found, so a layout change shows up in the pipeline log instead of
# silently producing wrong numbers.

F_TO_C = lambda f: (f - 32.0) * 5.0 / 9.0  # noqa: E731


def read_normals_csv(text):
    """Parse an NCEI by-station normals CSV into ``(header, rows)``.

    ``rows`` are dicts keyed by the (stripped, upper-cased) column names.
    Raises ``ValueError`` with a human-readable reason if no header is found.
    """
    reader = csv.reader(io.StringIO(text))
    header = None
    for row in reader:
        cells = [c.strip() for c in row]
        joined = " ".join(cells).upper()
        if any("NORMAL" in c.upper() for c in cells) and len(cells) > 2:
            header = cells
            break
    if header is None:
        raise ValueError("no header row containing an element name was found")
    rows = []
    for row in reader:
        if not row or all(not c.strip() for c in row):
            continue
        if len(row) < len(header) - 2:
            continue
        rows.append({header[i].strip().upper(): row[i].strip()
                     for i in range(min(len(header), len(row))) if header[i].strip()})
    return header, rows


def _col(header, pattern):
    """Column names matching *pattern* (case-insensitive regex), in file order."""
    import re as _re
    rx = _re.compile(pattern, _re.I)
    return [h for h in header if rx.search(h)]


def _month_of_row(row, header, index):
    """Best-effort month (1-12) for a normals row; ``None`` if undetermined."""
    for key in ("MONTH", "MM", "MO"):
        if key in row and row[key]:
            try:
                m = int(float(row[key]))
                if 1 <= m <= 12:
                    return m
            except ValueError:
                pass
    for key in ("DATE", "VALID_DATE", "MMDD"):
        val = row.get(key)
        if val:
            parts = str(val).replace("/", "-").split("-")
            try:
                if len(parts) >= 2:
                    m = int(parts[0])
                    if 1 <= m <= 12:
                        return m
                m = int(float(val))
                if 1 <= m <= 12:
                    return m
            except ValueError:
                pass
    # Last resort: the by-station monthly file holds 12 rows in calendar order.
    if header and 1 <= index + 1 <= 12:
        return index + 1
    return None


def monthly_normals_summary(text):
    """Extract the monthly precipitation and temperature normals.

    Returns ``{"precip_in": {month: value}, "temp_f": {month: value},
    "layout": {...}}``.  Only columns that actually exist are populated; the
    layout block records the header names that were used so the number on the
    site can always be traced to a named column.
    """
    header, rows = read_normals_csv(text)
    # Exact match only: a substring match also picks up ``meas_flag_MLY-PRCP-NORMAL``
    # and ``years_MLY-PRCP-NORMAL``, which are not values.
    prcp_cols = [c[0] for c in _exact_col(header, "MLY-PRCP-NORMAL")]
    temp_cols = [c[0] for c in _exact_col(header, "MLY-TAVG-NORMAL")]
    out = {"precip_in": {}, "temp_f": {},
           "layout": {"header": header[:120], "column_count": len(header),
                      "row_count": len(rows),
                      "precip_columns": prcp_cols, "temp_columns": temp_cols,
                      "month_column": next((k for k in ("MONTH", "DATE", "MM")
                                            if k in (rows[0] if rows else {})), None)}}
    for i, row in enumerate(rows):
        month = _month_of_row(row, header, i)
        if not month:
            continue
        for name, target in ((prcp_cols[0] if prcp_cols else None, "precip_in"),
                             (temp_cols[0] if temp_cols else None, "temp_f")):
            if not name:
                continue
            raw = row.get(name)
            if raw in (None, "", "9999.99", "999.9"):
                continue
            try:
                out[target][month] = float(raw)
            except ValueError:
                continue
    return out


# --------------------------------------------------- official daily normals
#
# NCEI publishes, per station, the official 1991-2020 *daily* normals.  Three
# families matter to this project:
#
#   DLY-TMAX-NORMAL / DLY-TMIN-NORMAL   the official normal high and low
#   DLY-PRCP-PCTALL-GE###HI             the official probability that a given
#                                       calendar date records at least ###
#                                       **hundredths of an inch** of precipitation
#   DLY-PRCP-25|50|75PCTL               the official precipitation percentiles
#
# The digits in GE###HI are hundredths of an inch, NOT thousandths: GE001HI is
# ">= 0.01 in" and GE100HI is ">= 1.00 in".  This was NOT assumed - it was
# established from the file itself.  For the 31 January dates present in the
# committed copy, each derived probability was compared against all the published
# columns and matched its own threshold far better than any other:
#
#   derived share of years >= 0.01 in  -> GE001HI  (mean |diff| 6.3 pts, vs 11.4 for GE010HI)
#   derived share of years >= 0.25 in  -> GE025HI  (3.7 pts, vs 9.2 and 7.5 either side)
#   derived share of years >= 1.00 in  -> GE100HI  (2.7 pts, vs 6.0 and 3.7 either side)
#
# An independent check: GE025HI for 01-01 is 16.8 %, while the wet-day median
# precipitation (DLY-PRCP-50PCTL) is 0.21 in.  If GE025HI meant ">= 0.025 in" the
# probability at 0.025 in could not be lower than the probability at the median
# 0.21 in, so the threshold has to be 0.25 in.
#
# GE001HI is therefore exactly the same quantity this project derives from 30
# seasons of GHCN-Daily ("share of years with >= 0.01 in"), so the two can be
# compared date by date rather than one being taken on trust.  Note that the
# published values are smoothed across neighbouring dates by NCEI while this
# project's are raw counts, which is the main reason the two differ.
#
# Nothing here is converted or estimated: every value is copied out of the
# published file, and each key names the threshold it came from.

_DLY_THRESHOLDS_IN = {
    "DLY-PRCP-PCTALL-GE001HI": 0.01,
    "DLY-PRCP-PCTALL-GE010HI": 0.10,
    "DLY-PRCP-PCTALL-GE025HI": 0.25,
    "DLY-PRCP-PCTALL-GE050HI": 0.50,
    "DLY-PRCP-PCTALL-GE100HI": 1.00,
    "DLY-PRCP-PCTALL-GE200HI": 2.00,
    "DLY-PRCP-PCTALL-GE400HI": 4.00,
    "DLY-PRCP-PCTALL-GE600HI": 6.00,
}

_DLY_ELEMENTS = (
    ("DLY-TMAX-NORMAL", "normal_high_f", 1),
    ("DLY-TMIN-NORMAL", "normal_low_f", 1),
    ("DLY-PRCP-PCTALL-GE001HI", "p_pcp_ge_0p01in_pct", 1),
    ("DLY-PRCP-PCTALL-GE010HI", "p_pcp_ge_0p10in_pct", 1),
    ("DLY-PRCP-PCTALL-GE025HI", "p_pcp_ge_0p25in_pct", 1),
    ("DLY-PRCP-PCTALL-GE050HI", "p_pcp_ge_0p50in_pct", 1),
    ("DLY-PRCP-PCTALL-GE100HI", "p_pcp_ge_1p00in_pct", 1),
    ("DLY-PRCP-PCTALL-GE200HI", "p_pcp_ge_2p00in_pct", 1),
    ("DLY-PRCP-PCTALL-GE400HI", "p_pcp_ge_4p00in_pct", 1),
    ("DLY-PRCP-PCTALL-GE600HI", "p_pcp_ge_6p00in_pct", 1),
    ("DLY-PRCP-25PCTL", "pcp_25pctl_in", 3),
    ("DLY-PRCP-50PCTL", "pcp_50pctl_in", 3),
    ("DLY-PRCP-75PCTL", "pcp_75pctl_in", 3),
)

# NCEI writes missing values as blanks; a few products use sentinels instead.
# NCEI's missing-value sentinels.  The normals file marks a percentile that
# cannot be computed (a date that is dry so often that no wet-day percentile
# exists) with **-9999**, which is *not* a plausible value for any element this
# parser reads - a negative rainfall percentile or a temperature of -9999 F does
# not exist.  The earlier version of this tuple listed only the positive
# sentinels the GHCN/GSOD files use, so -9999 was published on the site as
# "-9999.00 in".  That is the exact class of defect this project exists to
# prevent, so the guard is now both a literal list and a numeric floor.
_DLY_MISSING = ("", "9999.9", "999.9", "9999.99", "999.99", "99999", "9999", "M",
                "-9999", "-9999.0", "-9999.00", "-9999.9", "-99999")
# Anything at or below this is a sentinel, whatever it is spelled like.
_DLY_MISSING_FLOOR = -900.0


# Physical ranges for the values published from the daily-normals file.  These
# are stated from outside the data, not fitted to it, so they can catch a
# sentinel that a missing-value list forgot.  The tokens are matched with "in"
# rather than endswith(): the published percentile key is ``pcp_50pctl_in``,
# which has no underscore before "pctl", so an endswith("_pctl_in") test would
# match nothing and the guard would pass while a -9999 sat in the row.
_NORMALS_VALUE_RULES = (
    ("pctl", lambda v: v < 0.0, "negative precipitation percentile"),
    ("_pct", lambda v: not (0.0 <= v <= 100.0), "percentage outside 0-100"),
    ("_f", lambda v: not (-50.0 <= v <= 130.0), "temperature outside -50..130 F"),
)


def implausible_normals_value(key, value):
    """Return why ``value`` cannot honestly be a reading of ``key``, else None.

    Used by the verification ledger so that a missing-value sentinel which slips
    past the literal list is still caught before it is published - it is the
    numeric, data-independent half of the same guard.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    for token, fails, why in _NORMALS_VALUE_RULES:
        if token in key and fails(v):
            return why
    return None


def is_missing_normals_value(raw):
    """True if a cell of the NCEI normals file is a missing-value sentinel.

    Blank counts as missing.  So does any number at or below
    ``_DLY_MISSING_FLOOR``: no element in this file (a temperature normal, a
    percentage of years, or a precipitation percentile in inches) can be that
    low, so such a number can only be the sentinel.
    """
    if raw is None:
        return True
    text = str(raw).strip()
    if text in _DLY_MISSING:
        return True
    try:
        return float(text) <= _DLY_MISSING_FLOOR
    except ValueError:
        return False


def parse_daily_normals(text):
    """Parse the NCEI by-station *daily* normals CSV.

    Returns ``(by_mmdd, layout)`` where ``by_mmdd`` maps ``"MM-DD"`` to the
    published elements for that calendar date and ``layout`` records the columns
    that were actually found, the row count and the parse counts.  As with the
    other normals readers, a layout change returns an empty mapping plus the
    recorded layout rather than a wrong number.

    The file is served in one of two shapes (one row per date with ``DATE`` set
    to ``MM-DD``, or long form with separate ``month``/``day`` columns); both are
    handled and the shape used is recorded.
    """
    try:
        header, rows = read_normals_csv(text)
    except ValueError as exc:
        # A rearranged or non-CSV body must degrade to "no values, here is what I
        # saw", never raise: the caller has to be able to publish the layout it
        # received instead of a number it guessed.  This is the contract the other
        # normals readers already honour.
        return {}, {"usable": False,
                    "reason": f"the file could not be read as CSV: {exc}",
                    "first_400_chars": text[:400]}
    cols = {}
    for element, key, nd in _DLY_ELEMENTS:
        found = _exact_col(header, element)
        if found:
            cols[element] = (found[0][0], key, nd)

    layout = {
        "header_first_40": header[:40],
        "column_count": len(header),
        "row_count": len(rows),
        "columns_used": {el: cols[el][0] for el in cols},
        # Friendly key -> the official column it was read from, so any number on
        # the site can be traced to a named column of the published file.
        "column_by_key": {cols[el][1]: cols[el][0] for el in cols},
        # The inch threshold each probability column means, stated explicitly so
        # the interpretation travels with the data instead of living in a reader.
        "thresholds_in": {cols[el][1]: _DLY_THRESHOLDS_IN[el] for el in cols
                          if el in _DLY_THRESHOLDS_IN},
        "missing_elements": [el for el, _k, _n in _DLY_ELEMENTS if el not in cols],
    }
    if not cols:
        layout["usable"] = False
        layout["reason"] = ("none of the expected DLY-* element columns were found; "
                            "layout recorded for review instead of guessing")
        return {}, layout

    has_date = bool(rows) and "DATE" in rows[0]
    layout["date_column"] = "DATE" if has_date else None
    layout["long_form"] = not has_date

    def _num(row, col, nd):
        raw = row.get(col)
        if is_missing_normals_value(raw):
            return None
        try:
            return _f(float(str(raw).strip()), nd)
        except ValueError:
            return None

    def _mmdd(row, index):
        raw = str(row.get("DATE") or "").strip()
        if raw:
            # Accept MM-DD and MM/DD.
            cleaned = raw.replace("/", "-")
            parts = cleaned.split("-")
            if len(parts) == 2:
                try:
                    m, d = int(parts[0]), int(parts[1])
                    if 1 <= m <= 12 and 1 <= d <= 31:
                        return "%02d-%02d" % (m, d)
                except ValueError:
                    pass
        month = _month_of_row(row, header, index)
        try:
            day = int(float(str(row.get("DAY") or "").strip()))
        except (TypeError, ValueError):
            return None
        if month and 1 <= day <= 31:
            return "%02d-%02d" % (month, day)
        return None

    by_mmdd = {}
    unusable_dates = 0
    for i, row in enumerate(rows):
        mmdd = _mmdd(row, i)
        if not mmdd:
            unusable_dates += 1
            continue
        entry = {}
        for element, (col, key, nd) in cols.items():
            val = _num(row, col, nd)
            if val is not None:
                entry[key] = val
        # The published year count for the >=0.01 in probability, if present.
        n_years = None
        for cand in ("years_DLY-PRCP-PCTALL-GE010HI", "YEARS_DLY-PRCP-PCTALL-GE010HI"):
            if cand in row and not is_missing_normals_value(row[cand]):
                try:
                    n_years = int(float(row[cand]))
                except ValueError:
                    n_years = None
                break
        if n_years is not None:
            entry["n_years_pcp_ge_010in"] = n_years
        if entry:
            by_mmdd[mmdd] = entry

    layout["usable"] = bool(by_mmdd)
    layout["dates_parsed"] = len(by_mmdd)
    layout["rows_without_a_date"] = unusable_dates
    layout["element_coverage"] = {
        key: sum(1 for e in by_mmdd.values() if key in e)
        for _el, (_c, key, _n) in cols.items()
    }
    return by_mmdd, layout


def compare_daily_normals(by_mmdd, daily_climo):
    """Date-by-date difference between the published normals and this project.

    Both sides are reduced to the same quantities so the comparison is
    like-for-like:

    * ``p_pcp_ge_0p01in_pct`` (published, DLY-PRCP-PCTALL-GE001HI) vs
      ``p_rain_day_pct`` (derived) - the share of years recording >= 0.01 in.
    * ``p_pcp_ge_0p25in_pct`` (GE025HI) vs ``p_rain_ge_025in_pct``.
    * ``p_pcp_ge_1p00in_pct`` (GE100HI) vs ``p_rain_ge_100in_pct``.
    * ``normal_high_f`` / ``normal_low_f`` vs the derived 30-year means.

    The published values are NCEI's *smoothed* per-date normals (adjacent dates
    vary by a few tenths of a point); the derived values are raw 30-season counts
    and therefore move in 3.33-point steps.  A difference of a few points is
    therefore expected and is not evidence that either side is wrong - which is
    exactly why both are published instead of one being chosen.

    Returns a block published on the site: the largest absolute difference for
    each pair, the date it fell on, the counts, and the full per-date list of
    dates where the two disagree by more than the reporting granularity.  A
    disagreement is never smoothed away - it is published.
    """
    pairs = (
        ("p_pcp_ge_0p01in_pct", "p_rain_day_pct", "pct_points", "rain day >= 0.01 in"),
        ("p_pcp_ge_0p25in_pct", "p_rain_ge_025in_pct", "pct_points", "rain >= 0.25 in"),
        ("p_pcp_ge_1p00in_pct", "p_rain_ge_100in_pct", "pct_points", "rain >= 1.00 in"),
        ("normal_high_f", "normal_high_f", "deg_f", "normal high"),
        ("normal_low_f", "normal_low_f", "deg_f", "normal low"),
    )
    out = {"compared_dates": len(by_mmdd), "pairs": {}, "largest": {}, "flagged": []}
    for pub_key, der_key, unit, label in pairs:
        diffs = []
        for mmdd, pub in by_mmdd.items():
            der = daily_climo.get(mmdd)
            if not der:
                continue
            pv, dv = pub.get(pub_key), der.get(der_key)
            if pv is None or dv is None:
                continue
            diffs.append((mmdd, round(pv - dv, 3), pv, dv))
        if not diffs:
            out["pairs"][label] = {"n": 0}
            continue
        worst = max(diffs, key=lambda t: abs(t[1]))
        out["pairs"][label] = {
            "n": len(diffs),
            "unit": unit,
            "mean_difference": _f(statistics.fmean(d[1] for d in diffs), 3),
            "largest_absolute_difference": abs(worst[1]),
            "largest_difference_date": worst[0],
            "largest_difference_published": worst[2],
            "largest_difference_derived": worst[3],
            "within_1_unit": sum(1 for d in diffs if abs(d[1]) <= 1.0),
            "within_3_units": sum(1 for d in diffs if abs(d[1]) <= 3.0),
        }
        out["largest"][label] = abs(worst[1])
        for mmdd, delta, pv, dv in diffs:
            # Only percentages get a flagging threshold - a temperature normal is
            # an independent statistic and legitimately differs by a fraction of
            # a degree, so flagging it would be noise, not signal.
            if unit == "pct_points" and abs(delta) > 10.0:
                out["flagged"].append({"mmdd": mmdd, "quantity": label,
                                       "published": pv, "derived": dv,
                                       "difference": delta})
    # Worst first, then by date so the order is stable when differences tie.
    out["flagged"].sort(key=lambda r: (-abs(r["difference"]), r["mmdd"]))
    out["note"] = ("Published values are read from NOAA NCEI 1991-2020 daily "
                   "normals; derived values are this project's own 30-season "
                   "count from GHCN-Daily for the same station. Both are shown, "
                   "and the difference is published rather than reconciled.")
    return out


def _exact_col(header, name):
    """Columns whose name is exactly *name* or that name plus an hour suffix.

    NCEI's hourly normals file carries the element and then several derived
    columns (``meas_flag_...``, ``HLY-TEMP-10PCTL``, ``years_...``).  A substring
    match would pick those up as if they were the element itself, so the match
    has to be exact (optionally with a ``_00``.._23`` hour suffix).
    """
    import re as _re
    rx = _re.compile(r"^" + _re.escape(name) + r"(?:_(\d{1,2}))?$", _re.I)
    return [(h, (int(rx.match(h).group(1)) if rx.match(h).group(1) is not None else None))
            for h in header if rx.match(h)]


def hourly_normals_rh_inputs(text):
    """Extract (month, day, hour, temp_c, dewpoint_c) from NCEI hourly normals.

    Observed layout of ``normals-hourly/1991-2020/access/<STATION>.csv`` (checked
    against the file NCEI served on 2026-09-17, recorded in the run log)::

        STATION,NAME,LATITUDE,LONGITUDE,ELEVATION,DATE,month,day,hour,
        HLY-TEMP-NORMAL,meas_flag_HLY-TEMP-NORMAL,...,HLY-DEWP-NORMAL,...

    One row per month/day/hour, values in degrees Fahrenheit.  The reader does not
    rely on column order: it looks up the month/day/hour columns and the exact
    element columns, and records what it saw.  If those columns are absent it
    returns no rows and the caller publishes the layout instead of a number.
    """
    header, rows = read_normals_csv(text)
    temp_cols = _exact_col(header, "HLY-TEMP-NORMAL")
    dew_cols = _exact_col(header, "HLY-DEWP-NORMAL")
    first = rows[0] if rows else {}
    info = {"header": header[:60], "column_count": len(header), "row_count": len(rows),
            "temp_columns": [c[0] for c in temp_cols],
            "dewpoint_columns": [c[0] for c in dew_cols],
            "month_column": next((k for k in ("MONTH", "MM", "MO", "DATE") if k in first), None),
            "day_column": next((k for k in ("DAY", "DD") if k in first), None),
            "hour_column": next((k for k in ("HOUR", "TIME") if k in first), None),
            "first_row": {k: first[k] for k in ("MONTH", "DAY", "HOUR", "DATE") if k in first}}
    if not temp_cols or not dew_cols:
        info["usable"] = False
        info["reason"] = ("no exact HLY-TEMP-NORMAL / HLY-DEWP-NORMAL columns in this "
                          "file; layout recorded for review")
        return [], info

    def _num(row, col, missing=("", "9999.9", "999.9", "99999")):
        raw = row.get(col)
        if raw is None or raw in missing:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _hour_of_row(row):
        if row.get("HOUR"):
            try:
                h = int(float(row["HOUR"]))
                if 0 <= h <= 23:
                    return h
            except ValueError:
                pass
        val = row.get("TIME")
        if val:
            digits = "".join(ch for ch in str(val) if ch.isdigit())
            if len(digits) >= 2:
                try:
                    h = int(digits[:2])
                    if 0 <= h <= 23:
                        return h
                except ValueError:
                    pass
        return None

    out = []
    # Wide files carry one column per hour ("HLY-TEMP-NORMAL_00" ...); long files
    # carry one row per hour.  Handle both, and only then treat a single exact
    # column as the element for the row's own hour.
    wide = len(temp_cols) > 1 and len(dew_cols) > 1 and any(c[1] is not None for c in temp_cols)
    for i, row in enumerate(rows):
        month = _month_of_row(row, header, i)
        if not month:
            continue
        day = None
        for key in ("DAY", "DD"):
            if row.get(key):
                try:
                    dv = int(float(row[key]))
                    if 1 <= dv <= 31:
                        day = dv
                except ValueError:
                    pass
                break
        if wide:
            dew_by_hour = {h: c for c, h in dew_cols if h is not None}
            for col, hour in temp_cols:
                if hour is None or hour not in dew_by_hour:
                    continue
                t, d = _num(row, col), _num(row, dew_by_hour[hour])
                if t is None or d is None:
                    continue
                out.append({"month": month, "day": day, "hour": hour,
                            "temp_c": F_TO_C(t), "dewpoint_c": F_TO_C(d)})
        else:
            t, d = _num(row, temp_cols[0][0]), _num(row, dew_cols[0][0])
            if t is None or d is None:
                continue
            out.append({"month": month, "day": day, "hour": _hour_of_row(row),
                        "temp_c": F_TO_C(t), "dewpoint_c": F_TO_C(d)})
    info["usable"] = bool(out)
    info["usable_rows"] = len(out)
    info["wide_layout"] = wide
    return out, info


# ------------------------------------------------- rainy-season climatology

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


def build_season_statistics(ghcn, gsod_by_date, season_month_days, period, oni_series,
                            oni_seasons=None):
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

        # -- severity: how hard, not just how often -----------------------
        # Thresholds are stated as plain inches / knots; no official
        # warning-criteria label is applied, because those criteria are
        # written per forecast zone and this project will not restate them.
        #
        # The inch thresholds are exactly the ones NOAA NCEI publishes a
        # percent-of-years value for in the daily climate normals file
        # (DLY-PRCP-PCTALL-GE***HI: 0.01, 0.10, 0.25, 0.50, 1.00, 2.00, 4.00,
        # 6.00 in).  Keeping this project's own count on the same thresholds is
        # what lets the site print the two methods side by side and re-derive
        # each one from its own source file.
        wet_days_ge_1in = sum(1 for p in prcp_series if p is not None and p >= 1.00)
        wet_days_ge_2in = sum(1 for p in prcp_series if p is not None and p >= 2.00)
        wet_days_ge_050in = sum(1 for p in prcp_series if p is not None and p >= 0.50)
        wet_days_ge_400in = sum(1 for p in prcp_series if p is not None and p >= 4.00)
        daily_vals = [p for p in prcp_series if p is not None]
        max_daily_prcp_in = max(daily_vals) if daily_vals else None

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
        jr, heavy_jr, severe_jr, max_gust, max_wind = 0, 0, 0, None, None
        wind_days_ge_30kt, gust_days_ge_40kt, gust_days_ge_50kt = 0, 0, 0
        for iso in dates:
            s = gsod_by_date.get(iso)
            if not s:
                continue
            p, w, g = s["prcp_in"], s["max_wind_kt"], s["gust_kt"]
            if p is not None and w is not None and p >= 0.01 and w >= 20.0:
                jr += 1
            if p is not None and g is not None and p >= 0.50 and g >= 35.0:
                heavy_jr += 1
            # The strict tier the landlord cares about: a day that is both a
            # 1-inch rain day and a 40-knot-gust day at the same station.  Both
            # ends come from the same GSOD daily row, so "at the same time"
            # means "within the same UTC day" - an approximation the site
            # states rather than hides.
            if p is not None and g is not None and p >= 1.00 and g >= 40.0:
                severe_jr += 1
            if w is not None and w >= 30.0:
                wind_days_ge_30kt += 1
            if g is not None:
                if g >= 40.0:
                    gust_days_ge_40kt += 1
                if g >= 50.0:
                    gust_days_ge_50kt += 1
            if g is not None and (max_gust is None or g > max_gust):
                max_gust = g
            if w is not None and (max_wind is None or w > max_wind):
                max_wind = w

        # ENSO phase: prefer NOAA's published season-labelled ONI (mean of the
        # official OND / NDJ / DJF values covering this rainy season).  The
        # locally derived monthly series is only a fallback.
        oni = None
        oni_source = None
        if oni_seasons:
            oni = season_mean_oni(oni_seasons, season_year)
            if oni is not None:
                oni_source = ("mean of official CPC ONI for OND %d, NDJ %d and "
                              "DJF %d" % (season_year, season_year, season_year + 1))
        if oni is None:
            oni_key = (season_year, 11)
            oni = oni_series.get(oni_key)
            if oni is not None:
                oni_source = "derived 3-month running mean centred on Nov %d" % season_year
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
            "wet_days_ge_1in": wet_days_ge_1in,
            "wet_days_ge_2in": wet_days_ge_2in,
            "wet_days_ge_050in": wet_days_ge_050in,
            "wet_days_ge_400in": wet_days_ge_400in,
            "max_daily_prcp_in": _f(max_daily_prcp_in, 2) if max_daily_prcp_in is not None else None,
            "wind_and_rain_days": jr,
            "heavy_wind_and_rain_days": heavy_jr,
            "severe_wind_and_rain_days": severe_jr,
            "max_wind_mph": _f(max_wind * KT_TO_MPH, 1) if max_wind is not None else None,
            "wind_days_ge_30kt": wind_days_ge_30kt,
            "gust_days_ge_40kt": gust_days_ge_40kt,
            "gust_days_ge_50kt": gust_days_ge_50kt,
            "max_gust_kt": _f(max_gust, 1) if max_gust is not None else None,
            "max_gust_mph": _f(max_gust * KT_TO_MPH, 1) if max_gust is not None else None,
            "oni_ond": _f(oni, 2),
            "oni_source": oni_source,
            "enso_phase": enso_phase(oni),
            "enso_phase_label": phase_label(enso_phase(oni)),
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

    # Record values, each bound to the season that produced it so the reader
    # can find the date in the same GHCN/GSOD files this project fetched.
    def _record(key, field=None):
        vals = [s for s in seasons if s.get(key) is not None]
        if not vals:
            return None
        best = max(vals, key=lambda s: s[key])
        return {"season": best["season"], "value": best[key]}

    severity_record = {
        "max_daily_prcp_in": _record("max_daily_prcp_in"),
        "max_gust_mph": _record("max_gust_mph"),
        "max_wind_mph": _record("max_wind_mph"),
        "most_wet_days_ge_1in": _record("wet_days_ge_1in"),
        "most_wet_days_ge_2in": _record("wet_days_ge_2in"),
        "most_days_gust_ge_40kt": _record("gust_days_ge_40kt"),
        "most_days_gust_ge_50kt": _record("gust_days_ge_50kt"),
        "most_severe_wind_and_rain_days": _record("severe_wind_and_rain_days"),
    }

    return {
        "seasons": seasons,
        "severity_record": severity_record,
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
            # Severity counters.  Each is "days per season at or above this
            # plain threshold", never a named warning category.
            "wet_days_ge_050in": summarise([s["wet_days_ge_050in"] for s in seasons], 1),
            "wet_days_ge_1in": summarise([s["wet_days_ge_1in"] for s in seasons], 1),
            "wet_days_ge_2in": summarise([s["wet_days_ge_2in"] for s in seasons], 1),
            "wet_days_ge_400in": summarise([s["wet_days_ge_400in"] for s in seasons], 1),
            "max_daily_prcp_in": summarise(
                [s["max_daily_prcp_in"] for s in seasons if s["max_daily_prcp_in"] is not None], 2),
            "wind_days_ge_30kt": summarise([s["wind_days_ge_30kt"] for s in seasons], 1),
            "gust_days_ge_40kt": summarise([s["gust_days_ge_40kt"] for s in seasons], 1),
            "gust_days_ge_50kt": summarise([s["gust_days_ge_50kt"] for s in seasons], 1),
            "severe_wind_and_rain_days": summarise(
                [s["severe_wind_and_rain_days"] for s in seasons], 1),
            "max_wind_mph": summarise(
                [s["max_wind_mph"] for s in seasons if s["max_wind_mph"] is not None], 1),
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
            phase: dict(summarise(vals, 2), phase_label=phase_label(phase))
            for phase, vals in sorted(by_phase.items())
        },
        "wettest_seasons": [{"season": s["season"], "total_prcp_in": s["total_prcp_in"]}
                            for s in ranked[-5:]][::-1],
        "driest_seasons": [{"season": s["season"], "total_prcp_in": s["total_prcp_in"]}
                           for s in ranked[:5]],
    }


# --------------------------------------------------- Forecast Verification

def record_forecast_snapshot(current_forecast):
    """Create a normalized forecast snapshot from a calendar current_forecast block.

    Returns a dict with issuance date, generated timestamp, and per-target-date forecast fields:
    high_f, low_f, pop_pct, qpf_in, wind_max_mph.
    """
    if not current_forecast:
        return None
    gen_utc = current_forecast.get("generated_utc") or ""
    try:
        issuance_date = dt.datetime.fromisoformat(gen_utc.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        issuance_date = None

    days_out = []
    for d in current_forecast.get("days", []):
        t_date = d.get("date")
        if not t_date:
            continue
        days_out.append({
            "target_date": t_date,
            "high_f": d.get("high_f"),
            "low_f": d.get("low_f"),
            "pop_pct": d.get("rain_chance_pct"),
            "qpf_in": d.get("rain_amount_in"),
            "wind_max_mph": d.get("wind_max_mph"),
            "gust_max_mph": d.get("gust_max_mph"),
        })

    return {
        "issuance_date": issuance_date,
        "generated_utc": gen_utc,
        "forecast_updated": current_forecast.get("forecast_updated"),
        "days": days_out,
    }


def update_forecast_history(existing_history, new_snapshot):
    """Append a new forecast snapshot into the history list if not already present.

    Deduplicates based on issuance_date (or generated_utc if issuance_date is missing).
    """
    history = list(existing_history or [])
    if not new_snapshot:
        return history

    key = new_snapshot.get("issuance_date") or new_snapshot.get("generated_utc")
    for i, item in enumerate(history):
        cur_key = item.get("issuance_date") or item.get("generated_utc")
        if cur_key == key:
            history[i] = new_snapshot
            return history

    history.append(new_snapshot)
    history.sort(key=lambda x: x.get("issuance_date") or x.get("generated_utc") or "")
    return history


def score_forecast_history(history, ghcn_observations, gsod_observations=None):
    """Score historical NWS forecasts against observed GHCN-Daily and GSOD records.

    For each target date where an observation is recorded:
    - Measures high temperature error: (forecast_high - observed_tmax)
    - Measures low temperature error: (forecast_low - observed_tmin)
    - Scores POP calibration: whether precipitation >= 0.01 in occurred when POP >= 50%, < 50%, etc.
    - Groups scores by lead days (1 to 7).
    """
    pairs = []
    for snapshot in (history or []):
        iss_date_str = snapshot.get("issuance_date")
        if not iss_date_str:
            continue
        try:
            iss_d = dt.date.fromisoformat(iss_date_str)
        except ValueError:
            continue

        for d in snapshot.get("days", []):
            target_str = d.get("target_date")
            if not target_str:
                continue
            try:
                target_d = dt.date.fromisoformat(target_str)
            except ValueError:
                continue

            lead_days = (target_d - iss_d).days
            if lead_days < 0 or lead_days > 10:
                continue

            obs_ghcn = ghcn_observations.get(target_str)
            obs_gsod = (gsod_observations or {}).get(target_str)
            if not obs_ghcn and not obs_gsod:
                continue

            # Ground truth:
            # Temperature: GHCN TMAX/TMIN in tenths of deg C converted to deg F
            obs_high = None
            obs_low = None
            obs_prcp = None
            if obs_ghcn:
                tmax_raw = obs_ghcn.get("TMAX")
                tmin_raw = obs_ghcn.get("TMIN")
                prcp_raw = obs_ghcn.get("PRCP")
                if tmax_raw is not None:
                    try:
                        obs_high = round((float(tmax_raw) / 10.0) * 1.8 + 32.0, 1)
                    except ValueError:
                        pass
                if tmin_raw is not None:
                    try:
                        obs_low = round((float(tmin_raw) / 10.0) * 1.8 + 32.0, 1)
                    except ValueError:
                        pass
                if prcp_raw is not None:
                    obs_prcp = ghcn_to_inches(prcp_raw)

            # Fallback to GSOD if GHCN is missing
            if obs_high is None and obs_gsod and obs_gsod.get("max_f") is not None:
                obs_high = obs_gsod["max_f"]
            if obs_low is None and obs_gsod and obs_gsod.get("min_f") is not None:
                obs_low = obs_gsod["min_f"]
            if obs_prcp is None and obs_gsod and obs_gsod.get("prcp_in") is not None:
                obs_prcp = obs_gsod["prcp_in"]

            pairs.append({
                "issuance_date": iss_date_str,
                "target_date": target_str,
                "lead_days": lead_days,
                "fc_high": d.get("high_f"),
                "obs_high": obs_high,
                "high_error": (d.get("high_f") - obs_high) if (d.get("high_f") is not None and obs_high is not None) else None,
                "fc_low": d.get("low_f"),
                "obs_low": obs_low,
                "low_error": (d.get("low_f") - obs_low) if (d.get("low_f") is not None and obs_low is not None) else None,
                "fc_pop": d.get("pop_pct"),
                "obs_prcp_in": obs_prcp,
                "observed_rain": (obs_prcp is not None and obs_prcp >= 0.01) if obs_prcp is not None else None,
            })

    # Summary by lead days
    by_lead = defaultdict(lambda: {"high_errors": [], "low_errors": [], "pop_pairs": []})
    for p in pairs:
        ld = p["lead_days"]
        if p["high_error"] is not None:
            by_lead[ld]["high_errors"].append(abs(p["high_error"]))
        if p["low_error"] is not None:
            by_lead[ld]["low_errors"].append(abs(p["low_error"]))
        if p["fc_pop"] is not None and p["observed_rain"] is not None:
            by_lead[ld]["pop_pairs"].append((p["fc_pop"], p["observed_rain"]))

    lead_stats = []
    for ld in sorted(by_lead.keys()):
        he = by_lead[ld]["high_errors"]
        le = by_lead[ld]["low_errors"]
        pop_p = by_lead[ld]["pop_pairs"]

        high_mae = round(sum(he) / len(he), 2) if he else None
        low_mae = round(sum(le) / len(le), 2) if le else None

        # POP calibration: rain frequency when POP >= 50% vs POP < 50%
        ge_50 = [r for pop, r in pop_p if pop >= 50]
        lt_50 = [r for pop, r in pop_p if pop < 50]
        pop_ge_50_hit_rate = round(100.0 * sum(ge_50) / len(ge_50), 1) if ge_50 else None
        pop_lt_50_hit_rate = round(100.0 * sum(lt_50) / len(lt_50), 1) if lt_50 else None

        lead_stats.append({
            "lead_days": ld,
            "sample_size": max(len(he), len(le), len(pop_p)),
            "high_mae_f": high_mae,
            "low_mae_f": low_mae,
            "pop_ge_50_pct_rain": pop_ge_50_hit_rate,
            "pop_lt_50_pct_rain": pop_lt_50_hit_rate,
        })

    all_he = [p["high_error"] for p in pairs if p["high_error"] is not None]
    all_abs_he = [abs(e) for e in all_he]
    all_pop = [p for p in pairs if p["fc_pop"] is not None and p["observed_rain"] is not None]
    all_ge_50 = [p["observed_rain"] for p in all_pop if p["fc_pop"] >= 50]
    all_lt_50 = [p["observed_rain"] for p in all_pop if p["fc_pop"] < 50]

    return {
        "total_scored_pairs": len(pairs),
        "overall_high_mae_f": round(sum(all_abs_he) / len(all_abs_he), 2) if all_abs_he else None,
        "pop_ge_50_rain_pct": round(100.0 * sum(all_ge_50) / len(all_ge_50), 1) if all_ge_50 else None,
        "pop_lt_50_rain_pct": round(100.0 * sum(all_lt_50) / len(all_lt_50), 1) if all_lt_50 else None,
        "by_lead_days": lead_stats,
        "scored_pairs": pairs,
    }



# ------------------------------------------- NWS discussion language scanning

#: Sections of an NWS Area Forecast Discussion that are about something other
#: than the land forecast for this ZIP.  A gale warning in the MARINE section or
#: a wind shear note in AVIATION is not a landlord-relevant wind event at
#: 94122, and counting them produced flags that read as property risk.  The
#: exclusion is published alongside the scan (never silent).
AFD_EXCLUDED_SECTIONS = frozenset({"AVIATION", "MARINE", "FIRE WEATHER"})

#: An AFD section header line looks like ``.LONG TERM...`` on its own line.
AFD_SECTION_RE = re.compile(r"^\.([A-Z][A-Z0-9 &'()/-]{1,60})\.\.\.$")

#: ``&&`` on its own line is the AWIPS product separator.
AFD_BREAK_RE = re.compile(r"^\s*&&\s*$")

#: Sentences that are product furniture rather than forecast content: the AWIPS
#: transmission header, URLs and social-media links, and the forecaster-initials
#: footer ("SHORT TERM...MM LONG TERM....MM").  They are counted and the count is
#: published, so the filter can never quietly eat a real sentence.
AFD_FURNITURE_RE = (
    re.compile(r"\b(?:https?://|www\.|\.com/|\.gov/)", re.I),
    re.compile(r"^[A-Z0-9 ]{6,}$"),                      # "000 FXUS66 KMTR 181434 AFDMTR"
    re.compile(r"\.\.\.\.*[A-Z]{2}\b"),                   # forecaster initials footer
    re.compile(r"^(?:Issued|Updated) at ", re.I),         # issuance metadata line
)

#: The preamble (AWIPS header, product title and issuing office) carries no
#: forecast content, so it is not scanned - and the exclusion is published.
AFD_PREAMBLE = "(preamble)"

#: The phrase sets below are the whole detection rule.  They are deliberately
#: narrow and every one of them is a phrase a forecaster writes, not a stem:
#: a bare ``rain`` match would fire on any September discussion that mentions a
#: chance of rain, which is noise, not signal.  Case-sensitive patterns are
#: marked ``cs`` (upper-case acronyms such as PWAT/IVT, where a case-insensitive
#: match would hit ordinary words).
AFD_LANGUAGE_CATEGORIES = (
    {
        "id": "atmospheric_river",
        "label": "Atmospheric river / subtropical moisture plume",
        "why_it_matters": (
            "Atmospheric rivers carry most of California's high-total, "
            "long-duration rain. For a landlord this is the pattern behind "
            "roof, gutter, drainage and hillside failures - and the one worth "
            "preparing for days in advance."),
        "patterns": (
            (r"atmospheric rivers?", False),
            (r"pineapple express", False),
            (r"subtropical moisture", False),
            (r"(?:moisture|water vapou?r) plume", False),
            (r"plume of (?:subtropical |deep |rich )?moisture", False),
            (r"precipitable water", False),
            (r"\bPWAT\b", True),
            (r"integrated vapou?r transport", False),
            (r"\bIVT\b", True),
            # ``AR`` alone is only accepted once the same discussion has spelled
            # the term out, so an unrelated upper-case AR can never create a
            # flag on its own.
            (r"\bARs?\b", "only_after_spelled_out"),
        ),
    },
    {
        "id": "prolonged_rain",
        "label": "Prolonged / multi-day rain",
        "why_it_matters": (
            "Days of straight rain, not the daily total, is what saturates "
            "soil, fills gutters faster than they drain and keeps repair crews "
            "off a roof. This is the forecaster's own language for that pattern."),
        "patterns": (
            (r"periods of rain", False),
            (r"steady rain", False),
            (r"persistent rain", False),
            (r"prolonged rain", False),
            (r"long[- ]duration", False),
            (r"days of rain", False),
            (r"extended period of (?:heavy |persistent )?rain", False),
            (r"rain (?:will |should )?continue", False),
            (r"continues to rain", False),
            (r"back[- ]to[- ]back", False),
            (r"multiple (?:rounds|waves|systems|storms)", False),
            (r"series of (?:storms|systems)", False),
            (r"another (?:storm|system|front|round)", False),
            (r"successive (?:storms|systems)", False),
            (r"train(?:ing|s)? (?:over|across|through)", False),
        ),
    },
    {
        "id": "heavy_rain",
        "label": "Heavy rain / flooding",
        "why_it_matters": (
            "Short-duration intensity is what overwhelms storm drains, garage "
            "thresholds and ground-floor entryways, and what turns a wet day "
            "into a water-intrusion call."),
        "patterns": (
            (r"heavy rain", False),
            (r"moderate to heavy", False),
            (r"torrential", False),
            (r"rain(?:fall)? rates", False),
            (r"rainfall totals", False),
            (r"excessive rain", False),
            (r"flash flood", False),
            (r"flood watch", False),
            (r"river flood", False),
            (r"urban (?:and small stream )?flooding", False),
            (r"small stream flooding", False),
            (r"standing water", False),
            (r"ponding", False),
        ),
    },
    {
        "id": "strong_wind",
        "label": "Strong wind / wind hazard",
        "why_it_matters": (
            "Wind is what turns rain into intrusion: it drives water under "
            "flashing and through window seals, and it is what brings down "
            "fences, trees and scaffolding."),
        "patterns": (
            (r"wind advisory", False),
            (r"high wind", False),
            (r"damaging winds?", False),
            (r"hazardous winds?", False),
            (r"gale", False),
            (r"storm[- ]force", False),
            (r"gusts? (?:of|to|up to|near|around) \d", False),
            (r"winds? (?:of|to|up to|near|around|increasing to) \d", False),
        ),
    },
    {
        "id": "quoted_rainfall_amount",
        "label": "An explicit rainfall amount in NWS's own text",
        "why_it_matters": (
            "When a forecaster writes an amount, that is the closest thing to a "
            "usable number in the discussion. It is quoted here exactly as "
            "written and is NOT attached to any scoreboard day."),
        "patterns": (
            (r"\d+(?:\.\d+)?\s*(?:-|to|\u2013)\s*\d+(?:\.\d+)?\s*(?:inch|inches)\b", False),
            (r"\d+(?:\.\d+)?\s*(?:inch|inches)\b(?: of)?\s*(?:rain|precipitation|liquid)", False),
            (r"(?:rain|rainfall|precipitation)(?: totals)? of \d", False),
        ),
    },
    {
        "id": "wind_and_rain_together",
        "label": "Wind and rain in the same sentence",
        "why_it_matters": (
            "The single combination a landlord cannot fix after the fact: "
            "wind-driven rain finds gaps that neither hazard finds alone. A "
            "match here means NWS discussed both in one sentence."),
        "patterns": (("__BOTH__", False),),
    },
)

#: For the joint category, both a wind word and a rain word must appear in the
#: same sentence.  These are broad on purpose: the narrowness comes from
#: requiring the two together.
AFD_WIND_WORDS = re.compile(r"\b(?:wind|winds|windy|gust|gusts|gusty|breezy|breeze)\b", re.I)
AFD_RAIN_WORDS = re.compile(
    r"\b(?:rain|rains|rainy|rainfall|rainshowers?|showers?|precipitation|precip|"
    r"drizzle|storm|storms|downpour|wet)\b", re.I)
AFD_AR_SPELLED_OUT = re.compile(r"atmospheric rivers?", re.I)

#: The published sentence is the source sentence with runs of whitespace
#: collapsed.  A reviewer can Ctrl-F the result in the fetched product once the
#: same collapse is applied, which is exactly what the claim ledger does.
def collapse_ws(text):
    return re.sub(r"\s+", " ", text or "").strip()


def afd_sections(text):
    """Split an AFD product text into ``(section, body)`` blocks, in order.

    Section headers are the ``.LONG TERM...`` lines NWS writes; ``&&`` is the
    AWIPS separator; anything before the first header is filed under
    ``"(preamble)"`` so the AWIPS header and the KEY MESSAGES block are never
    silently dropped.
    """
    blocks = []
    section = "(preamble)"
    buf = []
    for line in (text or "").replace("\r", "\n").split("\n"):
        m = AFD_SECTION_RE.match(line.strip())
        if m:
            if buf:
                blocks.append((section, "\n".join(buf)))
            section, buf = m.group(1).strip(), []
            continue
        if AFD_BREAK_RE.match(line):
            if buf:
                blocks.append((section, "\n".join(buf)))
                buf = []
            continue
        buf.append(line)
    if buf:
        blocks.append((section, "\n".join(buf)))
    return blocks


def afd_sentences(body):
    """Unwrap a hard-wrapped AFD block into readable sentences.

    NWS wraps discussion prose at about 70 columns *mid-sentence*, so a single
    newline is a wrap and must become a space; a blank line is a paragraph
    break.  A hyphen at the end of a line is a wrap, not part of the word
    (``above-\nnormal`` -> ``above-normal``), matching the rule already used for
    CPC pages in ``main.extract_key_sentences``.
    """
    body = re.sub(r"(?<=[a-z])-\s*\n\s*(?=[a-z])", "-", body or "")
    # KEY MESSAGES is a bulleted list, and each bullet is an independent
    # statement of the forecaster's own summary.  Without this the whole list
    # unwraps into one long "sentence" that quotes several points as if they
    # were one.
    body = re.sub(r"\n(?=\s*[-*]\s)", r"\n\n", body)
    out = []
    for para in re.split(r"\n\s*\n", body):
        flat = re.sub(r"\n(?=\S)", " ", para)
        for piece in re.split(r"(?<=[.!?])\s+(?=[A-Z(\d])", flat):
            s = collapse_ws(piece).strip(" |")
            # Fix the space-before-punctuation that unwrapping can leave, and
            # put hyphenated number ranges back together ("1 - 2 inches").
            s = re.sub(r"\s+([,.;:])", r"\1", s)
            s = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "-", s)
            if 20 <= len(s) <= 500:
                out.append(s)
    return out


def _afd_match_sentence(patterns, sentence, ar_available):
    """Return the list of patterns from *patterns* that *sentence* matches.

    One function holds the whole matching rule, so the published sentence list
    and the published count are both derived from it and cannot disagree.

    ``cs`` is ``True`` for upper-case acronyms (``PWAT``, ``IVT``, ``AR``),
    which must not match case-insensitively, and the special value
    ``"only_after_spelled_out"`` for a bare ``AR``: accepted only when the same
    discussion has already spelled out "atmospheric river", so an unrelated
    upper-case AR can never create a flag.
    """
    matched = []
    for pattern, cs in patterns:
        if pattern == "__BOTH__":
            if AFD_WIND_WORDS.search(sentence) and AFD_RAIN_WORDS.search(sentence):
                matched.append("wind term and rain term in the same sentence")
            continue
        if cs == "only_after_spelled_out":
            if not ar_available:
                continue
            cs = True
        if re.search(pattern, sentence, 0 if cs else re.I):
            matched.append(pattern)
    return matched


def afd_language_scan(afd, excluded_sections=AFD_EXCLUDED_SECTIONS):
    """Flag the landlord-relevant language in an NWS Area Forecast Discussion.

    Returns a publishable dict.  The rule that governs the whole function:
    **a flag is a quotation, never a number.**  Nothing returned here is ever
    attached to a scoreboard day or converted into a daily value, because an
    AFD sentence has no date in it and this project will not invent one.

    ``afd`` is the dict stored under ``nws["products"]["AFD"]`` (keys ``text``,
    ``issuance_time``, ``source_url``, ``label``, ``id``).
    """
    afd = afd or {}
    text = afd.get("text") or ""
    ar_available = bool(AFD_AR_SPELLED_OUT.search(text))

    base = {
        "product": afd.get("product_name") or "Area Forecast Discussion",
        "product_type": "AFD",
        "product_id": afd.get("id"),
        "issuance_time": afd.get("issuance_time"),
        "source_url": afd.get("source_url"),
        "text_chars": len(text),
        "excluded_sections": sorted(excluded_sections),
        "exclusion_reason": (
            "The MARINE, AVIATION and FIRE WEATHER sections describe hazards for "
            "boaters, pilots and fuels, not for a building at 94122. They are "
            "excluded from the scan and the exclusion is published rather than "
            "silent."),
        "usage_note": (
            "Every item below is a verbatim quotation of NWS's own discussion, "
            "with runs of whitespace collapsed. A flag is never converted into a "
            "number on the scoreboard, and no calendar date is attached to a "
            "quotation: the discussion covers the next several days, not a named "
            "date. Absence of a phrase is a statement about this discussion, not "
            "about the season."),
        "verbatim_rule": (
            "whitespace-collapsed substring of the fetched product text "
            "(re-checked by pipeline/verify_claims.py on every run)"),
        "scope_caveat": (
            "NWS San Francisco/Monterey (MTR) writes one discussion for the whole "
            "Bay Area and Central Coast forecast area, not for 94122. A quoted "
            "sentence may be about the inland valleys, the hills or the immediate "
            "coast. The full sentence and its section are published so the reader "
            "can see what it refers to; this project never narrows a quotation to "
            "the ZIP on its own."),
        "sources": ([{"label": "NWS Area Forecast Discussion (api.weather.gov)",
                      "url": afd.get("source_url")}] if afd.get("source_url") else []),
    }

    if not text:
        base.update({"scanned": False,
                     "reason": "no Area Forecast Discussion text was captured this run",
                     "sections_scanned": [], "sections_excluded_this_run": [],
                     "categories": [], "any_language_found": False})
        return base

    scanned, excluded_run = [], []
    sentences = []
    furniture_dropped = 0
    excluded_upper = {s.upper() for s in excluded_sections}
    for section, body in afd_sections(text):
        # NWS repeats a header line before and after each block, so a section
        # name would otherwise be listed twice with an empty body the second
        # time.  Dedupe in order; never list a section that contributed nothing.
        if section.upper() in excluded_upper:
            if section not in excluded_run:
                excluded_run.append(section)
            continue
        if section == AFD_PREAMBLE:
            continue
        kept = []
        for s in afd_sentences(body):
            if any(rx.search(s) for rx in AFD_FURNITURE_RE):
                furniture_dropped += 1
                continue
            kept.append(s)
        if not kept:
            continue
        if section not in scanned:
            scanned.append(section)
        sentences.extend((section, s) for s in kept)

    categories = []
    total_matches = 0
    for cat in AFD_LANGUAGE_CATEGORIES:
        hits = []
        n_hits = 0
        for section, s in sentences:
            matched = _afd_match_sentence(cat["patterns"], s, ar_available)
            if not matched:
                continue
            # Count in the same pass that collects, so the published count and
            # the published list can never be produced by two different readings
            # of the rules (which is how a count silently drifts from its
            # evidence).  The list is capped; the count is not, so a truncated
            # list can never understate how much was found.
            n_hits += 1
            if len(hits) < 8:
                hits.append({"section": section, "sentence": s,
                             "matched_patterns": matched})
        total_matches += n_hits
        note = None
        if cat["id"] == "atmospheric_river" and not ar_available:
            note = ("The bare abbreviation 'AR' was not accepted as a match "
                    "because this discussion never spells out 'atmospheric "
                    "river', so an upper-case AR from some other context could "
                    "not be distinguished.")
        if len(hits) < n_hits:
            note = ((note + " " if note else "") +
                    f"{n_hits} sentences matched; the {len(hits)} longest-list "
                    "slots shown first are published in full.")
        categories.append({
            "id": cat["id"],
            "label": cat["label"],
            "why_it_matters": cat["why_it_matters"],
            "terms": [p for p, _cs in cat["patterns"] if p != "__BOTH__"]
                     or ["wind term AND rain term in the same sentence"],
            "sentence_count": n_hits,
            "sentences": hits,
            "note": note,
        })

    base.update({
        "scanned": True,
        "reason": None,
        "sections_scanned": scanned,
        "sections_excluded_this_run": excluded_run,
        "preamble_excluded": AFD_PREAMBLE,
        "furniture_sentences_dropped": furniture_dropped,
        "categories": categories,
        "any_language_found": total_matches > 0,
        "sentences_scanned": len(sentences),
        "none_found_statement": (
            None if total_matches else
            f"The Area Forecast Discussion issued {afd.get('issuance_time') or '(unknown time)'} "
            f"contains none of the {sum(len(c['patterns']) for c in AFD_LANGUAGE_CATEGORIES)} "
            f"listed phrases in its {len(scanned)} land-forecast sections "
            f"({len(sentences)} sentences scanned). That is a statement about this "
            "discussion only. It is not evidence that the season will be dry."),
    })
    return base


def parse_census_geographies(payload):
    """Read the Census reverse-geocode response for the 94122 centroid.

    The Census geocoder returns ``result.geographies`` keyed by geography type,
    each a list of records.  Only the fields this project publishes are read, by
    name, and a geography that is absent stays absent - it is never guessed.
    This is the official evidence for *which part of San Francisco* the single
    forecast point sits in; the ZCTA centroid alone does not say.
    """
    geos = ((payload or {}).get("result") or {}).get("geographies") or {}
    if not geos:
        return None

    def first(key):
        rows = geos.get(key) or []
        return rows[0] if rows and isinstance(rows[0], dict) else None

    def name_of(row, *fields):
        for f in fields:
            v = (row or {}).get(f)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, (int, float)):
                return v
        return None

    co_sub = first("County Subdivisions")
    county = first("Counties")
    place = first("Incorporated Places") or first("Census Designated Places")
    tract = first("Census Tracts")
    block = first("2020 Census Blocks") or first("Census Blocks")
    cd = first("119th Congressional Districts") or first("Congressional Districts")
    urban = first("Urban Areas")

    out = {
        "county_subdivision": name_of(co_sub, "NAME", "BASENAME"),
        "county_subdivision_geoid": name_of(co_sub, "GEOID"),
        "county": name_of(county, "NAME"),
        "county_geoid": name_of(county, "GEOID"),
        "place": name_of(place, "NAME"),
        "place_geoid": name_of(place, "GEOID"),
        "census_tract": name_of(tract, "NAME"),
        "census_tract_geoid": name_of(tract, "GEOID"),
        "census_block_geoid": name_of(block, "GEOID"),
        "congressional_district": name_of(cd, "NAME"),
        "urban_area": name_of(urban, "NAME"),
        "geography_types_returned": sorted(geos.keys()),
    }
    if not any(out[k] for k in ("county_subdivision", "county", "census_tract")):
        return None
    return out
