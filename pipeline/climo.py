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
            "wind_and_rain_days": jr,
            "heavy_wind_and_rain_days": heavy_jr,
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
            phase: dict(summarise(vals, 2), phase_label=phase_label(phase))
            for phase, vals in sorted(by_phase.items())
        },
        "wettest_seasons": [{"season": s["season"], "total_prcp_in": s["total_prcp_in"]}
                            for s in ranked[-5:]][::-1],
        "driest_seasons": [{"season": s["season"], "total_prcp_in": s["total_prcp_in"]}
                           for s in ranked[:5]],
    }
