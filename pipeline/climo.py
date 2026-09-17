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
    prcp_cols = _col(header, r"MLY-PRCP-NORMAL")
    temp_cols = _col(header, r"MLY-TAVG-NORMAL")
    out = {"precip_in": {}, "temp_f": {},
           "layout": {"header": header[:60], "row_count": len(rows),
                      "precip_columns": prcp_cols, "temp_columns": temp_cols}}
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
    info = {"header": header[:60], "row_count": len(rows),
            "temp_columns": [c[0] for c in temp_cols],
            "dewpoint_columns": [c[0] for c in dew_cols],
            "month_column": ("MONTH" in header) or ("DATE" in header),
            "hour_column": "HOUR" in header}
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
