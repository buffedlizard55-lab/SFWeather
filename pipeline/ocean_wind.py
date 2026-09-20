#!/usr/bin/env python3
"""The ocean-side wind record for 94122 — NDBC station 46026.

WHY THIS TIER EXISTS
    Every other wind figure this project publishes comes from SFO (KSFO), 11.9 mi
    away on the *bay* side of the peninsula, and the site is forbidden from calling
    those numbers a bound for the neighbourhood.  The nearest official anemometer
    on the ocean side of the Golden Gate is NOAA's National Data Buoy Center
    station 46026, a moored buoy in the open Pacific.  This module publishes that
    buoy's own 1 Oct – 31 Jan record, so the ocean side of the question has real,
    citable numbers standing beside the bay-side ones instead of a shrug.

WHAT IT IS NOT
    It is NOT 94122.  It is not a land station, it is not a measurement inside the
    ZIP, and it is not a bound on what a building in the Sunset experiences — open
    water is a different environment from a street.  That statement is published
    *with the numbers* (:data:`CAVEAT`), not bolted on by whoever renders them, and
    the claim ledger re-checks it on every run.

    It is also not a forecast.  Everything here is observation, and it never enters
    the day-by-day scoreboard.

SOURCES (all official NOAA / NWS / NDBC, HTTPS, free, no key)
    station_history.php?station=46026        which annual files NDBC lists
    data/historical/stdmet/46026hYYYY.txt.gz post-processed annual files
    data/stations/station_table.txt          position, owner, hull, name
    station_page.php?station=46026           sensor height and water depth
    faq/measdes.shtml                        units and missing-value conventions
    data/realtime2/46026.txt                 the latest observation

UNITS, TIME AND MISSING VALUES — NDBC'S OWN WORDS, QUOTED IN THE DATASET
    WSPD and GST are m/s, WVHT is m, times are UTC only, and missing values are
    "MM" in Realtime files and "a variable number of 9's ... depending on the data
    type" in Historical files.  Those sentences are copied verbatim into
    ``units_page_quotes`` with an excerpt of the page around each, so the
    conversion can be checked rather than trusted.

    Because the files are UTC only, the day counts here are UTC days, while the
    land rain and wind day counts elsewhere in this project are local (Pacific)
    days; a storm crossing midnight UTC can fall on a different date in each.  The
    dataset says so rather than pretending the two bases are interchangeable.

FORMATS CHANGE ACROSS THE RECORD
    The archive changed shape more than once (two-digit years until the 2000s, an
    optional minutes column, ``WD`` → ``WDIR``, ``BAR`` → ``PRES``, a units row
    that some eras carry and some do not).  The parser reads the header by *name*
    and proves its behaviour against the committed fixtures in
    ``tests/fixtures/ndbc/`` — a parser that trusted column order would read gusts
    as wave heights on the older files.

OFFLINE TESTING
    :func:`build` takes ``fetch_impl`` so the whole module runs without a network.
    ``python3 pipeline/ocean_wind.py --selftest`` drives it from those fixtures.

Run:  python3 pipeline/ocean_wind.py [--outdir data]
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import html as html_lib
import json
import math
import re
import statistics
import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib_fetch as fetchlib  # noqa: E402
import lib_provenance as provlib  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AREA = "ocean_wind"
STATION_ID = "46026"

# --- official sources -------------------------------------------------------
STATION_PAGE = f"https://www.ndbc.noaa.gov/station_page.php?station={STATION_ID}"
STATION_HISTORY_PAGE = f"https://www.ndbc.noaa.gov/station_history.php?station={STATION_ID}"
STATION_TABLE = "https://www.ndbc.noaa.gov/data/stations/station_table.txt"
MEASDES_PAGE = "https://www.ndbc.noaa.gov/faq/measdes.shtml"
REALTIME_URL = f"https://www.ndbc.noaa.gov/data/realtime2/{STATION_ID}.txt"
HISTORICAL_DIR = "https://www.ndbc.noaa.gov/data/historical/stdmet/"


def historical_url(year: int) -> str:
    """The canonical download URL for one annual standard-meteorological file."""
    return f"{HISTORICAL_DIR}{STATION_ID}h{int(year)}.txt.gz"


# --- the season window ------------------------------------------------------
#: The same 30 seasons the SFO wind and rain tables use (1 Oct 1991 – 31 Jan
#: 2021), so the two records can be read side by side without a period mismatch.
SEASON_YEAR_FIRST = 1991
SEASON_YEAR_LAST = 2020
SEASON_MONTHS = (10, 11, 12, 1)
SEASON_DATES = 123  # 1 Oct .. 31 Jan inclusive
WINDOW_LABEL = "1 October – 31 January, UTC dates (NDBC files are UTC only)"

#: A season that covers less than this share of the 123 dates is named in the
#: dataset as thin, and the site prints the list.  The number is published with
#: the data (``coverage_rule.thin_below_pct``) so the ledger can re-derive the
#: same list instead of hard-coding its own threshold.
THIN_COVERAGE_PCT = 95.0

#: 34 kt is gale force and 48 kt storm force in the marine warning scale, which is
#: why a *marine* record is counted at those thresholds as well as at the 40 kt
#: the land table on this site uses.
GUST_THRESHOLDS_KT = (34, 40, 48)
SUSTAINED_THRESHOLDS_KT = (20, 30)

DAY_COUNTER_KEYS = tuple(
    [f"days_gust_ge_{t}kt" for t in GUST_THRESHOLDS_KT]
    + [f"days_wind_ge_{t}kt" for t in SUSTAINED_THRESHOLDS_KT])
MAX_COUNTER_KEYS = ("max_gust_kt", "max_gust_mph", "max_wind_kt", "max_wvht_m", "max_wvht_ft")
COUNTER_KEYS = DAY_COUNTER_KEYS + MAX_COUNTER_KEYS

# --- units ------------------------------------------------------------------
#: Exact conversions, not rounded: 1 kt = 1.852 km/h = 0.514444 m/s, 1 m = 3.28084 ft.
MS_TO_KT = 1.0 / 0.5144444444444445
KT_TO_MPH = 1.852 / 1.609344
M_TO_FT = 1.0 / 0.3048

#: A missing value in a Historical file is "a variable number of 9's ... depending
#: on the data type" (NDBC, quoted in the dataset) — so the sentinel is 9s
#: followed by a run of zeros, and "9.9" or "99.5" are real readings.  Anything
#: numerically impossible for the field is ALSO treated as missing and counted, so
#: a format this parser has not seen cannot become a fake record high.
NINES = re.compile(r"^9+(\.0*)?$")
PHYSICAL_LIMITS = {"wdir": 400.0, "wspd_kt": 175.0, "gst_kt": 215.0,
                   "wvht_m": 40.0, "wtmp_c": 60.0}
MISSING_TOKENS = ("MM", "")

#: The sentences this tier publishes verbatim from NDBC's measurement page.  The
#: archive of the page is not stored, so the excerpt beside each quote (bounded to
#: < 400 characters) is what lets a reader — and the claim ledger — check that the
#: words are NDBC's and are used in the sense NDBC published them in.
UNITS_QUOTES = {
    "wspd_units": ("Wind speed (m/s) averaged over an eight-minute period for buoys and a "
                   "two-minute period for land stations."),
    "gust_definition": ("Peak 5 or 8 second gust speed (m/s) measured during the eight-minute "
                        "or two-minute period."),
    "wave_height": ("Significant wave height (meters) is calculated as the average of the "
                    "highest one-third of all of the wave heights during the 20-minute "
                    "sampling period."),
    "missing_values": ("Missing data in the Realtime files are denoted by \"MM\" while a "
                       "variable number of 9's are used to denote missing data in the "
                       "Historical files, depending on the data type (for example: 999.0 99.0)."),
    "utc_only": "Both Realtime and Historical files show times in UTC only.",
    "realtime_vs_historical": ("Real Time files generally contain the last 45 days of "
                               "\"Realtime\" data - data that went through automated quality "
                               "checks and were distributed as soon as they were received."),
    "station_id_reuse": ("ID's can be reassigned to future deployments within the same 1 "
                         "degree square."),
}

#: Published with the numbers.  It carries no figures of its own: every number a
#: reader sees comes from a parsed field standing next to this text.
CAVEAT = (
    "NOT A LAND STATION and NOT A MEASUREMENT INSIDE ZIP 94122: this is a moored buoy "
    "in the open Pacific, and its open-water wind is NOT a bound on what buildings in "
    "the Sunset experience — neither an upper nor a lower one. NDBC's own description "
    "of station IDs (quoted verbatim with this dataset) warns that an ID can be "
    "reassigned to a future deployment in the same one-degree square, so this record "
    "describes the station site over time rather than one specific hull. Read it as the "
    "nearest official ocean-side reference, standing alongside the SFO reference — "
    "neither is the neighbourhood."
)


# --------------------------------------------------------------------------- #
# parsing (pure functions — unit-tested offline)
# --------------------------------------------------------------------------- #

def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def strip_tags(page: str) -> str:
    """Page text with tags removed and entities decoded, for verbatim quotes."""
    text = re.sub(r"<script.*?</script>", " ", page or "", flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _collapse(html_lib.unescape(text))
    # Stripping a tag that wrapped a phrase ("<strong>...UTC only</strong>.") leaves a
    # space before the punctuation; undo that so NDBC's sentences match verbatim.
    return re.sub(r"\s+([.,;:])", r"\1", text)


def verbatim_excerpt(page: str, quotes: dict) -> dict:
    """Find each published sentence in the fetched page and keep an excerpt.

    Whitespace is collapsed on both sides first, so a sentence NDBC wraps across
    lines still matches — and a sentence that is *not* in the page is reported as
    not found rather than quietly dropped.
    """
    text = strip_tags(page)
    out = {}
    for key, sentence in quotes.items():
        found = bool(text) and sentence in text
        index = text.find(sentence) if found else -1
        if found:
            start = max(0, index - 80)
            excerpt = text[start:index + len(sentence) + 80]
        else:
            excerpt = text[:300]
        out[key] = {
            "quote": sentence,
            "found_verbatim": found,
            "excerpt": excerpt[:380],
            "source": MEASDES_PAGE,
        }
    return out


def num(token, field: str, counters: dict | None = None, limit: float | None = None):
    """A finite, physically possible float — or ``None`` for a missing sentinel.

    Three different things can look like a number in these files: a real reading, a
    variable number of 9's, and something this parser has never seen.  Only the
    first kind is returned; the others are counted so the build can report how many
    values were dropped and why.
    """
    if token is None:
        return None
    tok = str(token).strip()
    if tok in MISSING_TOKENS:
        return None
    if NINES.match(tok):
        if counters is not None:
            counters["sentinel"] = counters.get("sentinel", 0) + 1
        return None
    try:
        value = float(tok)
    except ValueError:
        if counters is not None:
            counters["unparseable"] = counters.get("unparseable", 0) + 1
        return None
    ceiling = limit if limit is not None else PHYSICAL_LIMITS.get(field)
    if ceiling is not None and not (-ceiling < value < ceiling):
        if counters is not None:
            counters["out_of_range"] = counters.get("out_of_range", 0) + 1
        return None
    return value


def wind_kt(token, units: str = "m/s", field: str = "gst_kt"):
    """A wind token converted to knots (3 decimals), or ``None`` when missing.

    The conversion is the whole point of the function: reading m/s as knots would
    understate every gust by a factor of two, and the self-test asserts the
    boundary case (9.9 m/s = 19.244 kt) that such a mistake would break.
    """
    value = num(token, field)
    if value is None:
        return None
    if units == "m/s":
        return round(value * MS_TO_KT, 3)
    if units == "kt":
        return round(value, 3)
    if units == "mph":
        return round(value / KT_TO_MPH, 3)
    raise ValueError(f"unknown wind unit {units!r}")


def _two_digit_year(field: str) -> int:
    """NDBC years are four digits since the mid-2000s and two before that.

    Two-digit years in this archive run 82..99 and then 00.., so the century is
    unambiguous here; a four-digit field is never reshaped.
    """
    if len(field) >= 4:
        return int(field)
    value = int(field)
    return 1900 + value if value >= 50 else 2000 + value


def _header_index(header: list) -> dict:
    """``{name: column}`` for a header whose names may repeat.

    NDBC's modern layout names its month column ``MM`` and its minutes column
    ``mm``; uppercased in the header they are the same token, so resolving columns
    by name alone silently reads the month twice and drops every row's minutes.
    (The published "strongest gust at" timestamps were hours only because of it.)
    The first occurrence keeps the bare name, later ones are suffixed ``#2`` and so
    on, which is enough for a fixed published column order and never guesses.
    """
    index: dict = {}
    seen: dict = {}
    for i, name in enumerate(header):
        seen[name] = seen.get(name, 0) + 1
        index[name if seen[name] == 1 else f"{name}#{seen[name]}"] = i
    return index



def parse_stdmet(text: str):
    """Parse an NDBC standard-meteorological file (historical or realtime).

    Returns ``(rows, meta)``.  Each row is ``{"ts", "wdir", "wspd_kt", "gst_kt",
    "wvht_m", "wtmp_c"}`` with missing values as ``None``; the header is read by
    name, so ``WD``/``WDIR``, ``BAR``/``PRES``, the optional minutes column and the
    units row are all handled by what the file says rather than by column count.
    """
    rows: list[dict] = []
    header: list[str] | None = None
    col_map: dict = {}
    units_line: str | None = None
    units_token: str | None = None
    counters: dict[str, int] = {}
    n_lines = 0
    n_malformed = 0

    def is_units_line(fields: list[str]) -> bool:
        return any(f in ("MO", "DY", "HR", "MN", "DEGT", "M/S", "HPA", "DEGC", "MI", "FT",
                         "SEC", "NMI") for f in [f.upper() for f in fields])

    for raw in (text or "").splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        n_lines += 1
        token = line.lstrip("#").strip()
        fields = token.split()
        upper = [f.upper() for f in fields]

        if header is None:
            if "WSPD" in upper and any(f in ("YY", "YYYY", "YR") for f in upper):
                header = upper
                continue
            if "WSPD" in upper and ("WDIR" in upper or "WD" in upper):
                header = upper
                continue
            continue  # anything before the header (a comment, a caption) is ignored

        if not col_map:
            col_map = _header_index(header)

        if units_line is None and is_units_line(fields):
            units_line = token
            n_malformed += 1
            if "WSPD" in header:
                idx = header.index("WSPD")
                if idx < len(fields):
                    units_token = fields[idx].strip()
            continue
        if line.startswith("#"):
            continue

        def col(*names):
            for name in names:
                idx = col_map.get(name)
                if idx is not None and idx < len(fields):
                    return fields[idx]
            return None

        units = units_token if units_token in ("m/s", "kt", "mph") else "m/s"
        year_tok = col("YYYY", "YY", "YR")
        if year_tok is None or not re.fullmatch(r"\d{2,4}", year_tok):
            n_malformed += 1
            continue
        try:
            month = int(col("MM", "MO") or "")
            day = int(col("DD", "DY") or "")
            hour = int(col("HH", "HR") or "")
            minute = int(col("MM#2", "MN", "MIN") or 0)
            stamp = dt.datetime(_two_digit_year(year_tok), month, day, hour, minute,
                                tzinfo=dt.timezone.utc)
        except (TypeError, ValueError):
            counters["bad_timestamp"] = counters.get("bad_timestamp", 0) + 1
            n_malformed += 1
            continue

        row = {
            "ts": stamp,
            "wdir": num(col("WDIR", "WD"), "wdir", counters),
            "wspd_kt": wind_kt(col("WSPD", "WS"), units, "wspd_kt"),
            "gst_kt": wind_kt(col("GST"), units),
            "wvht_m": num(col("WVHT", "WH"), "wvht_m", counters),
            "wtmp_c": num(col("WTMP"), "wtmp_c", counters),
        }
        # A report where wind, gust and wave height are all missing says nothing
        # about the weather.  Counting it as an observation would let an outage —
        # or a dead sensor writing 9s — look like a calm season.
        if row["wspd_kt"] is None and row["gst_kt"] is None and row["wvht_m"] is None:
            counters["empty_reports"] = counters.get("empty_reports", 0) + 1
            continue
        rows.append(row)

    meta = {
        "header": header,
        "units_line": units_line,
        "wind_units": units_token if units_token in ("m/s", "kt", "mph") else "m/s",
        "wind_units_basis": ("the units row in the file" if units_token
                             else "NDBC's measurement page: Standard Meteorological Data "
                                  "files are metric (m/s), and no units row is present in "
                                  "this file's era"),
        "n_lines": n_lines,
        "n_parsed": len(rows),
        "n_rows": len(rows),
        "n_malformed": n_malformed,
        "n_empty_rows": counters.get("empty_reports", 0),
        "dropped": counters,
        "first_ts": rows[0]["ts"] if rows else None,
        "last_ts": rows[-1]["ts"] if rows else None,
        "minute_column": ("the second MM column (minutes)"
                          if col_map.get("MM#2") is not None else None),
        "timestamps": ("to the minute" if col_map.get("MM#2") is not None
                       else "to the hour (this era's layout has no minutes column)"),
        "n_with_gust": sum(1 for r in rows if r["gst_kt"] is not None),
        "n_with_wave_height": sum(1 for r in rows if r["wvht_m"] is not None),
    }
    return rows, meta


def discover_historical_years(page: str, base_url: str = STATION_HISTORY_PAGE,
                              station_id: str = STATION_ID) -> dict:
    """``{year: resolved href}`` for the annual files NDBC's own page links.

    Hrefs are resolved against the page URL before matching, because a relative
    href, a root-relative one and an absolute one all appear in NDBC's markup
    (along with ``&amp;``), and a link that is not resolved is exactly how "the
    archive is complete" would go wrong.  The monthly current-year product and
    another station's files are deliberately excluded.
    """
    text = html_lib.unescape(page or "")
    out: dict[int, str] = {}
    for match in re.finditer(r"""href\s*=\s*["']([^"']+)["']""", text, re.I):
        href = match.group(1)
        resolved = urljoin(base_url, href)
        m = re.search(rf"filename={re.escape(station_id)}h(\d{{4}})\.txt\.gz", resolved)
        if m:
            out[int(m.group(1))] = resolved
            continue
        # A bare annual path is accepted too, but only for this station and only
        # when it names a year-year file rather than a month directory.
        m = re.search(rf"/{re.escape(station_id)}h(\d{{4}})\.txt(?:\.gz)?$", resolved)
        if m and not re.search(r"/stdmet/[A-Z][a-z]{2}/", resolved):
            out[int(m.group(1))] = resolved
    return dict(sorted(out.items()))


def parse_location(text: str):
    """``37.750 N 122.838 W (...)`` → ``(37.750, -122.838)``; ``(None, None)`` if absent."""
    text = html_lib.unescape(text or "")
    m = re.search(r"([0-9.]+)\s*([NS])\s+([0-9.]+)\s*([EW])", text)
    if not m:
        return None, None
    lat = float(m.group(1)) * (1 if m.group(2).upper() == "N" else -1)
    lon = float(m.group(3)) * (1 if m.group(4).upper() == "E" else -1)
    return round(lat, 3), round(lon, 3)


def parse_station_table(text: str) -> dict:
    """NDBC's machine-readable station table, keyed by station ID.

    ``LOCATION`` carries both a decimal and a degrees/minutes/seconds form; the
    decimal form is used, and the sign comes from the hemisphere letter — the
    self-test checks a southern/western row (Samoa) so a dropped sign cannot pass.
    """
    documented = ["STATION_ID", "OWNER", "TTYPE", "HULL", "NAME", "PAYLOAD", "LOCATION",
                  "TIMEZONE", "FORECAST", "NOTE"]
    header: list[str] | None = None
    out: dict[str, dict] = {}
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        fields = [f.strip() for f in line.split("|")]
        if header is None:
            candidate = [f.lstrip("#").strip().upper() for f in fields]
            if "STATION_ID" in candidate and "LOCATION" in candidate:
                header = candidate
                continue
            header = documented
        station_id = fields[0].strip()
        if not station_id or not re.fullmatch(r"[A-Za-z0-9]{4,8}", station_id):
            continue
        row = {name: (fields[i].strip() if i < len(fields) else "")
               for i, name in enumerate(header) if name}
        lat, lon = parse_location(row.get("LOCATION") or "")
        out[station_id] = {
            "station_id": station_id,
            "owner_code": row.get("OWNER") or None,
            "type": row.get("TTYPE") or None,
            "hull": row.get("HULL") or None,
            "name": html_lib.unescape(row.get("NAME") or "") or None,
            "payload": row.get("PAYLOAD") or None,
            "timezone": row.get("TIMEZONE") or None,
            "forecast_zone": row.get("FORECAST") or None,
            "location_text": html_lib.unescape(row.get("LOCATION") or "") or None,
            "lat": lat,
            "lon": lon,
            "source": STATION_TABLE,
        }
    return out


def parse_anemometer_height(page: str):
    """The station page's own anemometer height in metres, or ``None``.

    Buoy wind is reported at the sensor height, which is *not* the 10 m a land ASOS
    uses; without this number the exposure convention would be undisclosed, so it is
    published rather than assumed.
    """
    text = strip_tags(page)
    m = (re.search(r"Anemometer height:?\s*([0-9.]+)\s*m\b", text, re.I)
         or re.search(r"anemometer height[^0-9]{0,40}([0-9.]+)\s*m\b", text, re.I))
    return float(m.group(1)) if m else None


def parse_water_depth(page: str):
    m = re.search(r"Water depth:?\s*([0-9.]+)\s*m\b", strip_tags(page), re.I)
    return float(m.group(1)) if m else None


def season_of(stamp: dt.datetime):
    """``(season_year, label)`` for an Oct–Jan stamp, else ``None``.

    Season 1991-1992 is October–December 1991 plus January 1992, which is how the
    SFO tables in this project name their seasons.
    """
    if stamp.month in (10, 11, 12):
        return stamp.year, f"{stamp.year}-{stamp.year + 1}"
    if stamp.month == 1:
        return stamp.year - 1, f"{stamp.year - 1}-{stamp.year}"
    return None


def great_circle_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in statute miles (mean Earth radius 3958.7613 mi)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3958.7613 * math.asin(min(1.0, math.sqrt(a)))


def _r(value, digits):
    return None if value is None else round(value, digits)


def aggregate_seasons(rows: list, years=None) -> list:
    """Per-season gust, wind and wave counters over the Oct–Jan window.

    Day counts are UTC dates (NDBC files are UTC only) and are the number of dates
    on which the season's maximum reached the threshold.  A season nobody observed
    is published with ``dates_with_data: 0`` and ``None`` maxima — never as a season
    with no gales, which is a different statement.
    """
    years = list(years) if years else list(range(SEASON_YEAR_FIRST, SEASON_YEAR_LAST + 1))
    seasons: dict[int, dict] = {}
    for year in years:
        seasons[year] = {
            "season_year": year,
            "season": f"{year}-{year + 1}",
            "days": {},
            "observations": 0,
            "max_gust_kt": None, "max_gust_mph": None, "max_gust_at": None,
            "max_wind_kt": None, "max_wind_at": None,
            "max_wvht_m": None, "max_wvht_ft": None, "max_wvht_at": None,
        }

    for row in rows:
        got = season_of(row["ts"])
        if not got:
            continue
        season_year, _label = got
        if season_year not in seasons:
            continue
        s = seasons[season_year]
        s["observations"] += 1
        key = row["ts"].strftime("%Y-%m-%d")
        day = s["days"].setdefault(key, {"gust_kt": None, "wspd_kt": None})
        if row["gst_kt"] is not None:
            if day["gust_kt"] is None or row["gst_kt"] > day["gust_kt"]:
                day["gust_kt"] = row["gst_kt"]
            if s["max_gust_kt"] is None or row["gst_kt"] > s["max_gust_kt"]:
                s["max_gust_kt"] = row["gst_kt"]
                s["max_gust_mph"] = row["gst_kt"] * KT_TO_MPH
                s["max_gust_at"] = row["ts"].strftime("%Y-%m-%d %H:%M UTC")
        if row["wspd_kt"] is not None:
            if day["wspd_kt"] is None or row["wspd_kt"] > day["wspd_kt"]:
                day["wspd_kt"] = row["wspd_kt"]
            if s["max_wind_kt"] is None or row["wspd_kt"] > s["max_wind_kt"]:
                s["max_wind_kt"] = row["wspd_kt"]
                s["max_wind_at"] = row["ts"].strftime("%Y-%m-%d %H:%M UTC")
        if row["wvht_m"] is not None:
            if s["max_wvht_m"] is None or row["wvht_m"] > s["max_wvht_m"]:
                s["max_wvht_m"] = row["wvht_m"]
                s["max_wvht_ft"] = row["wvht_m"] * M_TO_FT
                s["max_wvht_at"] = row["ts"].strftime("%Y-%m-%d %H:%M UTC")

    out = []
    for year in sorted(seasons):
        s = seasons[year]
        days = s["days"]
        row = {
            "season": s["season"],
            "season_year": s["season_year"],
            "observations": s["observations"],
            "dates_with_data": len(days),
            "coverage_pct": round(100.0 * len(days) / SEASON_DATES, 1),
            "max_gust_kt": _r(s["max_gust_kt"], 1),
            "max_gust_mph": _r(s["max_gust_mph"], 1),
            "max_gust_at": s["max_gust_at"],
            "max_wind_kt": _r(s["max_wind_kt"], 1),
            "max_wind_at": s["max_wind_at"],
            "max_wvht_m": _r(s["max_wvht_m"], 2),
            "max_wvht_ft": _r(s["max_wvht_ft"], 1),
            "max_wvht_at": s["max_wvht_at"],
        }
        for t in GUST_THRESHOLDS_KT:
            row[f"days_gust_ge_{t}kt"] = sum(
                1 for d in days.values() if d["gust_kt"] is not None and d["gust_kt"] >= t)
        for t in SUSTAINED_THRESHOLDS_KT:
            row[f"days_wind_ge_{t}kt"] = sum(
                1 for d in days.values() if d["wspd_kt"] is not None and d["wspd_kt"] >= t)
        out.append(row)
    return out


def summarize(seasons: list) -> dict:
    """Mean / median / min / max / n for every published counter.

    Computed from the *published* season rows with plain arithmetic, so the claim
    ledger can rebuild the same numbers from the same file and compare them exactly.
    Day counters are integers, so a season with no data contributes a 0 — which is
    why the number of seasons with data and the list of seasons without it are
    published right beside the means rather than left for a reader to assume.
    """
    counters = {}
    counted = [s for s in seasons if (s.get("dates_with_data") or 0) > 0]
    for key in COUNTER_KEYS:
        # A season nobody observed is NOT a zero.  Averaging it in as one turned a
        # gale record into "0.07 gust days per season" whenever the record had
        # outages, which is a statement about the outage and not about the ocean;
        # a season covering three dates would do the same to a lesser degree.  Only
        # seasons that observed at least one Oct-Jan UTC date contribute, the
        # number used is printed with every counter, and the seasons left out are
        # named beside the means (seasons_with_no_data, thin_seasons).
        vals = [s[key] for s in counted if s.get(key) is not None]
        if not vals:
            continue
        counters[key] = {
            "mean": round(sum(vals) / len(vals), 2),
            "median": round(statistics.median(vals), 2),
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
            "n_seasons_with_value": len(vals),
        }
    with_data = [s for s in seasons if (s.get("dates_with_data") or 0) > 0]
    return {
        "counters": counters,
        "counted_seasons": [s["season"] for s in counted],
        "seasons": len(seasons),
        "seasons_with_data": len(with_data),
        "seasons_without_data": len(seasons) - len(with_data),
        "seasons_with_no_data": [s["season"] for s in seasons
                                 if (s.get("dates_with_data") or 0) == 0],
        "thin_seasons": [s["season"] for s in seasons
                         if (s.get("coverage_pct") or 0.0) < THIN_COVERAGE_PCT],
        "counter_basis": ("Every counter is counted per season from NDBC station "
                          f"{STATION_ID}'s own observations, then averaged over the "
                          f"{len(counted)} of {len(seasons)} seasons that observed at "
                          "least one Oct-Jan UTC date — a season with no data is named "
                          "in seasons_with_no_data and is never averaged in as a zero, "
                          "and the number of seasons behind each counter is printed with "
                          "it. Day counters count UTC dates; the counters' coverage cut "
                          "is published in coverage_rule."),
        "method": ("Days are counted on distinct UTC dates inside 1 Oct – 31 Jan; the "
                   "threshold is met when the day's maximum reaches it. Gusts are NDBC "
                   "peak 5- or 8-second speeds, sustained wind is the 8-minute average, "
                   "in both cases as NDBC defines them (quoted in units_page_quotes)."),
    }


# --------------------------------------------------------------------------- #
# the build
# --------------------------------------------------------------------------- #

def build(datadir: Path = Path("data"), fetch_impl=None):
    """Fetch, parse and aggregate the buoy record → ``(dataset, manifest_entries)``.

    ``fetch_impl`` lets the self-test inject a network-free fetcher with the same
    signature as :func:`lib_fetch.get`.  Writing is left to :func:`write_outputs`
    so the whole build can be exercised in a temporary directory.
    """
    datadir = Path(datadir)
    entries: list[dict] = []
    irregularities: list[dict] = []

    def _fetch(url: str, note: str | None = None, timeout: int = 180):
        res = fetch_impl(url, timeout) if fetch_impl else fetchlib.get(url, timeout=timeout)
        entries.append(res.provenance(note=note))
        return res

    # --- 1. the station's own metadata --------------------------------------
    table_res = _fetch(STATION_TABLE, "NDBC machine-readable station table (position, owner, "
                                      "hull, name)")
    stations = parse_station_table(table_res.text()) if table_res.ok else {}
    station = stations.get(STATION_ID)
    if not station:
        irregularities.append({
            "severity": "error", "source": AREA,
            "message": (f"the station table did not yield a row for station {STATION_ID} "
                        f"({STATION_TABLE}); the position of this record is unverified for "
                        f"this run"),
        })

    # --- 2. which years NDBC says it has ------------------------------------
    hist_res = _fetch(STATION_HISTORY_PAGE, "NDBC station history page: the annual files "
                                            f"listed for station {STATION_ID}")
    years_listed = discover_historical_years(hist_res.text(), STATION_HISTORY_PAGE) \
        if hist_res.ok else {}
    wanted = [y for y in sorted(years_listed)
              if SEASON_YEAR_FIRST <= y <= SEASON_YEAR_LAST + 1]
    if not years_listed:
        irregularities.append({
            "severity": "warning", "source": AREA,
            "message": (f"the NDBC station page listed no annual files ({STATION_HISTORY_PAGE}), "
                        f"so no year is assumed to exist: the record is published as not "
                        f"available rather than guessed from a year range"),
        })

    # --- 3. the annual files ------------------------------------------------
    rows: list = []
    year_files: list[dict] = []
    years_fetched: list[int] = []
    for year in wanted:
        url = historical_url(year)
        res = _fetch(url, f"NDBC historical standard meteorological file, station "
                          f"{STATION_ID}, {year}")
        info = {"year": year, "url": url, "ok": bool(res.ok),
                "listed_url": years_listed.get(year),
                "bytes": res.size if res.ok else None,
                "sha256": res.sha256 if res.ok else None,
                "error": res.error,
                "n_rows": 0, "dropped": {}}
        body: bytes | None = None
        if res.ok:
            try:
                body = gzip.decompress(res.body or b"")
            except Exception as exc:  # noqa: BLE001 - a non-gzip body is a real outcome
                body = None
                info["parse_error"] = f"{type(exc).__name__}: {exc}"
                irregularities.append({
                    "severity": "error", "source": AREA,
                    "message": f"station {STATION_ID} {year}: the annual file did not "
                               f"decompress ({info['parse_error']}); the season is published "
                               f"with whatever coverage is actually available",
                    "evidence": {"url": url, "sha256": res.sha256},
                })
        if body is not None:
            parsed_rows, meta = parse_stdmet(body.decode("utf-8", "replace"))
            info["n_rows"] = meta["n_parsed"]
            info["dropped"] = meta["dropped"]
            info["wind_units"] = meta["wind_units"]
            if parsed_rows:
                info["first_ts"] = meta["first_ts"].strftime("%Y-%m-%d %H:%M UTC")
                info["last_ts"] = meta["last_ts"].strftime("%Y-%m-%d %H:%M UTC")
                rows.extend(parsed_rows)
                years_fetched.append(year)
            else:
                # A file that arrives but yields nothing usable is published as no
                # data for its season, with an excerpt of what did arrive, because
                # "no rows" and "no storms" are different statements.
                text = body.decode("utf-8", "replace")
                info["parse_error"] = "the file contained no usable rows"
                irregularities.append({
                    "severity": "error", "source": AREA,
                    "message": (f"station {STATION_ID} {year}: the annual file arrived but "
                                f"contained no usable rows, so its season is published as no "
                                f"data rather than as a quiet one"),
                    "evidence": {"url": url, "markup_excerpt": _collapse(text)[:280],
                                 "sha256": res.sha256},
                })
        elif res.ok and "parse_error" not in info:
            info["parse_error"] = "no body"
        if not res.ok:
            irregularities.append({
                "severity": "warning", "source": AREA,
                "message": (f"station {STATION_ID} {year}: the annual file NDBC lists could "
                            f"not be retrieved ({res.error}); the season is published with "
                            f"the coverage that is actually available"),
                "evidence": {"url": url},
            })
        year_files.append(info)

    # --- 4. NDBC's own unit sentences ---------------------------------------
    measdes_res = _fetch(MEASDES_PAGE, "NDBC measurement descriptions and units")
    quotes = verbatim_excerpt(measdes_res.text(), UNITS_QUOTES) if measdes_res.ok else {}
    missing_quotes = sorted(k for k, v in quotes.items() if not v["found_verbatim"])
    if missing_quotes:
        irregularities.append({
            "severity": "error", "source": AREA,
            "message": ("NDBC's measurement page no longer contains "
                        f"{len(missing_quotes)} quoted sentence(s) verbatim "
                        f"({missing_quotes}), so the units this dataset converts are not "
                        f"re-verifiable from the fetched page on this run"),
            "evidence": {"url": MEASDES_PAGE},
        })

    # --- 5. the station page's own sensor context ---------------------------
    page_res = _fetch(STATION_PAGE, f"NDBC station page for {STATION_ID} (anemometer height, "
                                    f"water depth)")
    page_text = page_res.text() if page_res.ok else ""
    anemometer_m = parse_anemometer_height(page_text) if page_text else None
    water_depth_m = parse_water_depth(page_text) if page_text else None
    if page_text and anemometer_m is None:
        irregularities.append({
            "severity": "warning", "source": AREA,
            "message": ("the station page did not state an anemometer height, so the "
                        "exposure of the wind measurements is published as unknown"),
            "evidence": {"url": STATION_PAGE},
        })

    # --- 6. the latest observation ------------------------------------------
    latest = None
    rt_res = _fetch(REALTIME_URL, f"NDBC realtime standard meteorological file, station "
                                  f"{STATION_ID} (latest observation)")
    if rt_res.ok:
        rt_rows, _meta = parse_stdmet(rt_res.text())
        if rt_rows:
            # The realtime file lists newest first; the latest observation is the
            # one with the greatest timestamp, not simply the last line.
            row = max(rt_rows, key=lambda r: r["ts"])
            units = _meta["wind_units"]
            latest = {
                "observation_utc": row["ts"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "observed_label": row["ts"].strftime("%Y-%m-%d %H:%M UTC"),
                "wind_dir_deg": None if row["wdir"] is None else round(row["wdir"]),
                "wind_file_value": None if row["wspd_kt"] is None
                                   else round(row["wspd_kt"] / (MS_TO_KT if units == "m/s"
                                                                else 1.0), 1),
                "gust_file_value": None if row["gst_kt"] is None
                                   else round(row["gst_kt"] / (MS_TO_KT if units == "m/s"
                                                               else 1.0), 1),
                "file_wind_units": units,
                "wind_kt": _r(row["wspd_kt"], 1),
                "gust_kt": _r(row["gst_kt"], 1),
                "wave_height_ft": _r(row["wvht_m"] * M_TO_FT, 1) if row["wvht_m"] is not None
                                  else None,
                "provisional": True,
                "is_a_forecast": False,
                "source": REALTIME_URL,
                "note": ("An observation from NDBC's Realtime file — “data that went through "
                         "automated quality checks”, quoted above. It is not a forecast: it is "
                         "published for context only and never enters the day-by-day "
                         "scoreboard."),
            }
        else:
            irregularities.append({
                "severity": "warning", "source": AREA,
                "message": f"the realtime file carried no usable rows ({REALTIME_URL})",
                "evidence": {"url": REALTIME_URL},
            })

    # --- 7. distance from the ZIP centroid ----------------------------------
    centroid, distance_mi = {}, None
    try:
        run = json.loads((datadir / "run.json").read_text())
        centroid = ((run.get("target") or {}).get("centroid")) or {}
    except Exception:  # noqa: BLE001 - the centroid is an input, not a fatal dependency
        centroid = {}
    if station and centroid.get("lat") is not None and centroid.get("lon") is not None \
            and station.get("lat") is not None and station.get("lon") is not None:
        distance_mi = round(great_circle_mi(centroid["lat"], centroid["lon"],
                                            station["lat"], station["lon"]), 1)

    # --- 8. the dataset -----------------------------------------------------
    seasons = aggregate_seasons(rows)
    summary = summarize(seasons)
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dataset = {
        "area": AREA,
        "tier": "ocean-wind",
        "title": f"Ocean-side wind record — NOAA NDBC station {STATION_ID}",
        "generated_utc": generated,
        "available": bool(station) and (summary["seasons_with_data"] > 0),
        "station": {
            "id": STATION_ID,
            "name": (station or {}).get("name"),
            "owner": (station or {}).get("owner_code"),
            "type": (station or {}).get("type"),
            "hull": (station or {}).get("hull"),
            "payload": (station or {}).get("payload"),
            "timezone": (station or {}).get("timezone"),
            "lat": (station or {}).get("lat"),
            "lon": (station or {}).get("lon"),
            "location_text": (station or {}).get("location_text"),
            "anemometer_height_m": anemometer_m,
            "water_depth_m": water_depth_m,
            "distance_mi_from_centroid": distance_mi,
            "centroid": {"lat": centroid.get("lat"), "lon": centroid.get("lon"),
                         "source": centroid.get("source")},
            "station_table_url": STATION_TABLE,
            "station_page_url": STATION_PAGE,
        },
        "window": {
            "label": WINDOW_LABEL,
            "months": list(SEASON_MONTHS),
            "day_basis": "UTC dates (NDBC files are UTC only)",
            "first_season": f"{SEASON_YEAR_FIRST}-{SEASON_YEAR_FIRST + 1}",
            "last_season": f"{SEASON_YEAR_LAST}-{SEASON_YEAR_LAST + 1}",
        },
        "season_dates_expected": SEASON_DATES,
        "coverage_rule": {
            "thin_below_pct": THIN_COVERAGE_PCT,
            "note": ("A season covering less than this share of the 123 Oct–Jan dates is "
                     "named in thin_seasons and printed next to the means"),
            "counter_rule": "at least one observed Oct-Jan UTC date",
            "counter_note": ("Every mean, median, minimum and maximum is computed over the "
                             "seasons that observed at least one Oct-Jan UTC date, listed "
                             "in summary.counted_seasons; a season with no data is named "
                             "in summary.seasons_with_no_data and is never counted as a "
                             "zero. Each counter prints how many seasons stand behind it."),
        },
        "thresholds": {
            "gust_kt": list(GUST_THRESHOLDS_KT),
            "sustained_kt": list(SUSTAINED_THRESHOLDS_KT),
            "note": ("34 kt is gale force and 48 kt storm force in the marine warning scale; "
                     "40 kt is the threshold the SFO table on this site uses, so the two "
                     "records can be read at the same number"),
        },
        "units": {
            "file_wind": "m/s",
            "file_waves": "m",
            "published_wind": "kt and mph",
            "published_waves": "m and ft",
            "conversions": {"ms_to_kt": round(MS_TO_KT, 6), "kt_to_mph": round(KT_TO_MPH, 6),
                            "m_to_ft": round(M_TO_FT, 6)},
            "source": MEASDES_PAGE,
        },
        "units_page_url": MEASDES_PAGE,
        "units_page_quotes": quotes,
        "caveat": CAVEAT,
        "is_land_station": False,
        "is_measurement_inside_94122": False,
        "is_a_bound_for_94122": False,
        "seasons": seasons,
        "summary": summary,
        "year_files": year_files,
        "years_fetched": sorted(years_fetched),
        "years_listed_by_ndbc": sorted(years_listed),
        "latest_observation": latest,
        "irregularities": irregularities,
        "why_this_is_here": ("Every other wind number this project publishes is from SFO, on "
                             "the bay side. This is the nearest official anemometer on the "
                             "ocean side of the Golden Gate, published beside those numbers so "
                             "the ocean side of the question is not left to guesswork."),
        "what_this_tier_does_not_do": [
            "It does not describe any street in ZIP 94122 — see the caveat.",
            "It is not a bound, an upper limit or a lower limit for the neighbourhood.",
            "It is not a forecast, and it never enters the day-by-day scoreboard.",
            "It does not publish rain, so it cannot speak to simultaneous wind and rain.",
        ],
    }
    return dataset, entries


def write_outputs(dataset: dict, entries: list, datadir: Path = Path("data")):
    """Write the dataset, its own manifest, and its findings into the quality report."""
    datadir = Path(datadir)
    datadir.mkdir(parents=True, exist_ok=True)
    out = datadir / "ocean_wind.json"
    out.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n")
    manifest = provlib.write_manifest(
        datadir, AREA, entries, dataset["generated_utc"],
        f"NDBC station {STATION_ID} ocean-side wind record: station history, station table, "
        f"station page, the annual standard meteorological files, the realtime file and "
        f"NDBC's units page")
    if dataset.get("irregularities"):
        provlib.merge_irregularities(datadir, AREA, dataset["irregularities"])
    return out, manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").strip().splitlines()[0])
    ap.add_argument("--outdir", default="data", help="where ocean_wind.json is written")
    ap.add_argument("--datadir", default=None,
                    help="where run.json is read from (defaults to --outdir)")
    ap.add_argument("--selftest", action="store_true",
                    help="run the offline self-test against the committed fixtures")
    args = ap.parse_args(argv)

    if args.selftest:
        import selftest_ocean_wind  # noqa: PLC0415 - only needed for the self-test
        return selftest_ocean_wind.run()

    datadir = Path(args.datadir or args.outdir)
    dataset, entries = build(datadir=datadir)
    out, manifest = write_outputs(dataset, entries, datadir)
    s = dataset["summary"]
    gale = (s["counters"].get("days_gust_ge_34kt") or {})
    print(f"  wrote {out}")
    print(f"  station {STATION_ID}: {s['seasons_with_data']}/{s['seasons']} seasons with data; "
          f"gale-gust days per season mean {gale.get('mean')} (max {gale.get('max')})")
    print(f"  fetches recorded: {len(entries)} in {manifest.name}"
          + (f"; {len(dataset['irregularities'])} irregularity(ies)" if dataset["irregularities"]
             else ""))
    for item in dataset["irregularities"]:
        print(f"  [{item['severity'].upper()}] {item['message']}")
    return 0 if dataset["available"] else 1


if __name__ == "__main__":
    sys.exit(main())
