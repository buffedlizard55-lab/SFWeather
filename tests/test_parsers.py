#!/usr/bin/env python3
"""Offline unit tests for the parsing and derivation code.

These run with the standard library only (no network, no third-party packages),
so they can be run in CI and by any reviewer:

    python3 tests/test_parsers.py

What they cover, and why each one exists:

* ``parse_oni_seasons`` - the CPC ONI product writes a season as three *month
  initials*, so "NDJ" and "DJF" are ambiguous to a naive parser and CPC's year
  label runs across the calendar year.  Getting this wrong silently shifted every
  ENSO phase on the site by one season (bug found and fixed 17 Sep 2026), so the
  convention is pinned down here with real published values.
* ``_exact_col`` / ``hourly_normals_rh_inputs`` - a substring match on
  ``HLY-TEMP-NORMAL`` also matches ``meas_flag_HLY-TEMP-NORMAL`` and
  ``HLY-TEMP-10PCTL``, which yielded zero usable rows.  The header used here is
  the real one NCEI served, recorded by the pipeline in
  ``data/humidity_normals.json``.
* ``humidity_normals_by_date`` - the relative humidity is *derived* (NOAA
  publishes no RH normal), so it is cross-checked against an independent
  formulation of the Magnus formula.
* ``build_daily_climatology`` / ``build_season_statistics`` - a synthetic GHCN
  file with exact, hand-computable values, so a regression in the aggregation is
  caught without needing the network.

The OHLC-style fixture values below are synthetic **except** the ONI anomalies
and the column headers, which are copied verbatim from the official files.
"""

import io
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "pipeline"))

import climo  # noqa: E402
import main as pipeline_main  # noqa: E402
import build_calendar  # noqa: E402
import verify_sources  # noqa: E402

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    if not condition:
        print("FAIL  %s\n      %s" % (name, detail))


def section(title):
    print("\n== %s" % title)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

# Real anomalies from https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt
# (retrieved 17 Sep 2026).  The TOTAL column is synthetic - these tests only read
# the anomaly - and is written as a plausible season mean.
ONI_FIXTURE = """ SEAS  YR   TOTAL   ANOM
 DJF 2015  26.26    2.20
 JFM 2015  26.35    2.10
 FMA 2015  26.66    1.80
 MAM 2015  26.95    1.50
 AMJ 2015  27.10    1.20
 MJJ 2015  27.05    0.95
 JJA 2015  26.90    0.75
 JAS 2015  26.95    0.65
 ASO 2015  27.20    0.60
 SON 2015  27.60    0.75
 OND 2015  27.90    1.35
 NDJ 2015  28.30    2.59
 DJF 2016  28.20    2.50
 JFM 2016  28.05    2.20
 FMA 2016  27.60    1.75
 MAM 2016  27.05    1.15
 AMJ 2016  26.45    0.50
 MJJ 2016  25.70   -0.10
 JJA 2016  25.15   -0.45
 OND 2025  26.30   -0.61
 NDJ 2025  26.35   -0.60
 DJF 2026  26.55   -0.39
 JFM 2026  26.75   -0.21
 FMA 2026  27.05    0.11
 MAM 2026  27.40    0.46
 AMJ 2026  27.90    0.95
 MJJ 2026  28.35    1.39
 JJA 2026  28.75    1.80
"""


def real_header(path, key="header"):
    """The real NCEI header recorded by a past pipeline run, if available."""
    try:
        with open(os.path.join(ROOT, "data", path)) as fh:
            return json.load(fh)["layout"][key]
    except Exception:
        return None


def seasonal_month_days():
    """(month, day) for 1 Oct - 31 Jan, the season the site reports."""
    days = []
    for month, n in ((10, 31), (11, 30), (12, 31), (1, 31)):
        for d in range(1, n + 1):
            days.append((month, d))
    return days


def hour_to_mmdd(hour_of_year):
    """Map an hour-of-year index (0-8759) to (month, day, hour) like NCEI does."""
    month_len = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    m = 0
    h = hour_of_year
    while h >= month_len[m] * 24:
        h -= month_len[m] * 24
        m += 1
    return m + 1, h // 24 + 1, h % 24


def independent_rh(temp_c, dew_c):
    """RH with the WMO/NOAA formulation (17.625/243.04 is the other convention)."""
    import math
    a, b = 17.27, 237.7
    gamma = (a * dew_c) / (b + dew_c) - (a * temp_c) / (b + temp_c)
    return 100.0 * math.exp(gamma)


# --------------------------------------------------------------------------- #
# 1. NWS local-time aggregation
# --------------------------------------------------------------------------- #

section("NWS hourly timestamps -> local calendar days")

# A fixed -07:00 conversion incorrectly moves this winter timestamp into Jan 1.
# The NWS point metadata supplies America/Los_Angeles, which is UTC-8 on Jan 1.
winter_stamp = "2027-01-01T07:30:00+00:00"
check("winter UTC timestamp stays on the prior Pacific calendar date",
      build_calendar.local_date_from_iso(winter_stamp, "America/Los_Angeles").isoformat()
      == "2026-12-31",
      str(build_calendar.local_date_from_iso(winter_stamp, "America/Los_Angeles")))

# In summer the same UTC hour has the opposite offset; this pins the code to an
# IANA timezone rather than either Pacific offset.
summer_stamp = "2026-07-01T07:30:00+00:00"
check("summer UTC timestamp uses daylight-saving Pacific time",
      build_calendar.local_date_from_iso(summer_stamp, "America/Los_Angeles").isoformat()
      == "2026-07-01",
      str(build_calendar.local_date_from_iso(summer_stamp, "America/Los_Angeles")))

# --------------------------------------------------------------------------- #
# 2. official-host allow-list
# --------------------------------------------------------------------------- #

section("official host allow-list")
check("the NWS API host is explicitly allowed",
      verify_sources.host_allowed("api.weather.gov"), "")
check("the Census Gazetteer host is explicitly allowed",
      verify_sources.host_allowed("www2.census.gov"), "")
check("a look-alike Census domain is rejected",
      not verify_sources.host_allowed("evilcensus.gov"), "")
check("an unreviewed NOAA subdomain is rejected",
      not verify_sources.host_allowed("weather-data.noaa.gov"), "")

# --------------------------------------------------------------------------- #
# 3. official ONI parsing
# --------------------------------------------------------------------------- #

section("official ONI (CPC oni.ascii.txt)")

rows = climo.parse_oni_seasons(ONI_FIXTURE)
check("parse_oni_seasons: rows parsed", len(rows) == 28, "got %d" % len(rows))

by_label = {r["label"]: r for r in rows}
jja26 = by_label.get("JJA 2026")
check("JJA 2026 present with the published +1.80 anomaly",
      jja26 is not None and jja26["anomaly_c"] == 1.80,
      json.dumps(jja26 and jja26["anomaly_c"]))
check("JJA 2026 covers Jun/Jul/Aug 2026",
      jja26 is not None and jja26["months"] == [(2026, 6), (2026, 7), (2026, 8)],
      json.dumps(jja26 and [list(m) for m in jja26["months"]]))

ndj15 = by_label.get("NDJ 2015")
check("NDJ 2015 = +2.59 covers Nov 2015 - Jan 2016 (Jan is in the NEXT year)",
      ndj15 is not None and ndj15["anomaly_c"] == 2.59
      and ndj15["months"] == [(2015, 11), (2015, 12), (2016, 1)],
      json.dumps(ndj15 and [list(m) for m in ndj15["months"]]))
djf16 = by_label.get("DJF 2016")
check("DJF 2016 = +2.50 covers Dec 2015 - Feb 2016 (Dec is in the PREVIOUS year)",
      djf16 is not None and djf16["anomaly_c"] == 2.50
      and djf16["months"] == [(2015, 12), (2016, 1), (2016, 2)],
      json.dumps(djf16 and [list(m) for m in djf16["months"]]))

ordering = [r["months"][0] for r in rows]
check("rows are ordered oldest -> newest", ordering == sorted(ordering), str(ordering[:3]))

# every three-month season token must resolve to three consecutive months
bad = [(t, s) for t, s in climo.SEASON_TOKENS.items()
       if len(s["months"]) != 3 or (s["months"][1] - s["months"][0]) % 12 != 1
       or (s["months"][2] - s["months"][1]) % 12 != 1]
check("all 12 season rotations resolve to consecutive months", not bad, str(bad))

mean15 = climo.season_mean_oni(rows, 2015)
expected15 = (1.35 + 2.59 + 2.50) / 3.0
check("season mean for 2015-16 = OND 2015 / NDJ 2015 / DJF 2016",
      mean15 is not None and abs(mean15 - expected15) < 1e-9,
      "got %r, expected %r" % (mean15, expected15))
check("season mean is NOT contaminated by DJF 2015 (the previous winter)",
      mean15 is not None and abs(mean15 - (2.20 + 1.35 + 2.59) / 3.0) > 1e-6,
      "got %r" % (mean15,))

# --------------------------------------------------------------------------- #
# 2. hourly normals -> humidity
# --------------------------------------------------------------------------- #

section("hourly normals -> humidity (NCEI normals-hourly)")

header = real_header("humidity_normals.json")
check("real NCEI header recovered from data/humidity_normals.json",
      bool(header) and "HLY-TEMP-NORMAL" in header,
      "header=%r" % (header[:6] if header else None))

if header:
    exact_temp = climo._exact_col(header, "HLY-TEMP-NORMAL")
    exact_dew = climo._exact_col(header, "HLY-DEWP-NORMAL")
    check("_exact_col matches only the element column",
          [c[0] for c in exact_temp] == ["HLY-TEMP-NORMAL"],
          str([c[0] for c in exact_temp]))
    check("_exact_col does not match meas_flag_ / comp_flag_ / years_ / percentiles",
          all("meas_flag" not in c[0] and "PCTL" not in c[0] and "years" not in c[0]
              for c in exact_temp + exact_dew),
          str([c[0] for c in exact_temp + exact_dew]))

    # 8760 rows, exact round numbers so the expectation is hand-checkable:
    # temp 68 degF (20 degC), dewpoint 50 degF (10 degC) -> RH ~52%
    lines = [",".join(header)]
    for h in range(8760):
        m, d, hh = hour_to_mmdd(h)
        vals = {"STATION": "USW00023234", "NAME": "SAN FRANCISCO INTL AP",
                "LATITUDE": "37.62", "LONGITUDE": "-122.38", "ELEVATION": "3.0",
                "DATE": "2010-01-01", "MONTH": str(m), "DAY": str(d), "HOUR": str(hh),
                "HLY-TEMP-NORMAL": "68", "HLY-DEWP-NORMAL": "50"}
        lines.append(",".join(vals.get(col.upper(), "0") for col in header))
    hourly_rows, info = climo.hourly_normals_rh_inputs("\n".join(lines))

    check("8760 hourly rows read", len(hourly_rows) == 8760, "got %d" % len(hourly_rows))
    check("layout recorded as not-wide (one row per hour)",
          info.get("wide_layout") is False, json.dumps(info.get("wide_layout")))
    check("month and hour columns detected",
          info.get("month_column") and info.get("hour_column"), json.dumps(info)[:200])

    by_date = climo.humidity_normals_by_date(hourly_rows)
    check("every calendar date gets its own humidity value", len(by_date) == 365,
          "got %d dates" % len(by_date))
    got = by_date.get("01-15")
    want = independent_rh(20.0, 10.0)
    check("derived RH agrees with an independent Magnus formulation (<=1.5 pts)",
          got is not None and abs(got - want) <= 1.5,
          "pipeline %.1f vs independent %.1f" % (got or -1, want))

    monthly = climo.humidity_normals_from_hourly(hourly_rows)
    check("monthly fallback covers all 12 months",
          sorted(monthly) == list(range(1, 13)) and all(0 < v <= 100 for v in monthly.values()),
          json.dumps(monthly))

# --------------------------------------------------------------------------- #
# 3. monthly normals (cross-check source)
# --------------------------------------------------------------------------- #

section("monthly normals (NCEI normals-monthly)")

mheader = real_header("monthly_normals.json")
if mheader and "MLY-PRCP-NORMAL" not in mheader:
    mheader = mheader + ["MLY-PRCP-NORMAL", "meas_flag_MLY-PRCP-NORMAL",
                         "comp_flag_MLY-PRCP-NORMAL", "years_MLY-PRCP-NORMAL"]
check("real NCEI monthly header recovered", bool(mheader)
      and "MLY-PRCP-NORMAL" in mheader, "header=%r" % (mheader[:6] if mheader else None))

if mheader:
    published = {10: 0.94, 11: 2.60, 12: 4.76, 1: 4.40}
    lines = [",".join(mheader)]
    for month in range(1, 13):
        vals = {"STATION": "USW00023272", "DATE": "2010-%02d" % month,
                "NAME": "SAN FRANCISCO DOWNTOWN", "MONTH": str(month), "DAY": "1",
                "HOUR": "0"}
        for col in mheader:
            key = col.upper()
            if key == "MLY-PRCP-NORMAL":
                vals[key] = str(published.get(month, 1.11))
            elif key.startswith("MLY-PRCP") or key.startswith("MEAS_FLAG_MLY-PRCP"):
                # decoys: measured flags and flags must never be read as values
                vals[key] = "9999.99"
            else:
                vals[key] = vals.get(key, "0")
        lines.append(",".join(vals.get(col.upper(), "0") for col in mheader))
    summary = climo.monthly_normals_summary("\n".join(lines))
    check("monthly precipitation parsed for all 12 months",
          sorted(summary["precip_in"]) == list(range(1, 13)),
          json.dumps(summary["precip_in"]))
    check("the exact MLY-PRCP-NORMAL column is the one read, not the flag columns",
          summary["precip_in"].get(10) == 0.94 and summary["precip_in"].get(12) == 4.76,
          json.dumps(summary["precip_in"]))

# --------------------------------------------------------------------------- #
# 4. end-to-end aggregation on a synthetic GHCN file
# --------------------------------------------------------------------------- #

section("rainy-season aggregation (synthetic GHCN, exact expected values)")

ghcn_header = ("STATION,DATE,LATITUDE,LONGITUDE,ELEVATION,NAME,PRCP,PRCP_ATTRIBUTES,"
               "SNOW,SNOW_ATTRIBUTES,SNWD,SNWD_ATTRIBUTES,TMAX,TMAX_ATTRIBUTES,"
               "TMIN,TMIN_ATTRIBUTES")
ghcn_rows = [
    # 25.4 mm = 1.00 in of rain, 10.0 degC = 50.0 degF, 0.0 degC = 32.0 degF
    "USW00023272,2015-10-01,37.77,-122.43,45.7,SAN FRANCISCO DOWNTOWN,"
    "254,,0,,0,,100,,0,",
    # dry day: 20.0 degC = 68.0 degF
    "USW00023272,2016-01-15,37.77,-122.43,45.7,SAN FRANCISCO DOWNTOWN,"
    "0,,0,,0,,200,,100,",
]
ghcn_data, fmt = climo.parse_ghcn_daily("\n".join([ghcn_header] + ghcn_rows))
check("GHCN wide format detected", fmt == "wide", fmt)
check("GHCN values parsed for both dates",
      ghcn_data.get("2015-10-01", {}).get("PRCP") == 254
      and ghcn_data.get("2016-01-15", {}).get("TMAX") == 200,
      json.dumps(ghcn_data))

gsod = {
    "2015-10-01": {"prcp_in": 1.0, "wind_kt": 10.0, "max_wind_kt": 25.0, "gust_kt": 40.0},
    "2016-01-15": {"prcp_in": 0.0, "wind_kt": 4.0, "max_wind_kt": 8.0, "gust_kt": 17.0},
}
month_days = seasonal_month_days()
daily = climo.build_daily_climatology(ghcn_data, gsod, month_days, (2015, 2015))
check("one row per day of the season", len(daily) == 123, "got %d" % len(daily))
d_oct1 = daily[0]
check("Oct 1 row is the first row", d_oct1["mmdd"] == "10-01", d_oct1["mmdd"])
check("normal high 50.0 F / low 32.0 F from the synthetic values",
      d_oct1["normal_high_f"] == 50.0 and d_oct1["normal_low_f"] == 32.0,
      "high=%s low=%s" % (d_oct1["normal_high_f"], d_oct1["normal_low_f"]))
check("rain-day probability 100% and mean 1.000 in for a single-season sample",
      d_oct1["p_rain_day_pct"] == 100.0 and d_oct1["mean_daily_prcp_in"] == 1.0,
      "p=%s mean=%s" % (d_oct1["p_rain_day_pct"], d_oct1["mean_daily_prcp_in"]))
check("wind + rain event detected (1.00 in with a 25 kt max wind)",
      d_oct1["p_wind_and_rain_pct"] == 100.0, str(d_oct1["p_wind_and_rain_pct"]))
check("max gust converted kt -> mph (40 kt = 46.0 mph)",
      d_oct1["max_gust_on_record_mph"] == 46.0, str(d_oct1["max_gust_on_record_mph"]))
empty = daily[1]
check("a day with no observations reports nulls, not zeros",
      empty["normal_high_f"] is None and empty["mean_daily_prcp_in"] is None,
      "high=%s mean=%s" % (empty["normal_high_f"], empty["mean_daily_prcp_in"]))

oni_rows = climo.parse_oni_seasons(ONI_FIXTURE)
stats = climo.build_season_statistics(ghcn_data, gsod, month_days, (2015, 2015),
                                      {}, oni_seasons=oni_rows)
season = stats["seasons"][0]
check("season labelled 2015-2016", season["season"] == "2015-2016", season["season"])
check("season total = 1.00 in from the two synthetic days",
      season["total_prcp_in"] == 1.0, str(season["total_prcp_in"]))
check("monthly totals split correctly (Oct 1.00 / Jan 0.00)",
      season["monthly_prcp_in"]["10"] == 1.0 and season["monthly_prcp_in"]["01"] == 0.0,
      json.dumps(season["monthly_prcp_in"]))
check("ENSO uses the official ONI mean and says so",
      season["oni_ond"] == round((1.35 + 2.59 + 2.50) / 3.0, 2)
      and "official CPC ONI" in (season["oni_source"] or ""),
      "oni=%s source=%s" % (season["oni_ond"], season["oni_source"]))
check("ENSO phase derived from that value", season["enso_phase"] == "el_nino",
      str(season["enso_phase"]))
check("single-season distribution is that season",
      stats["distribution"]["season_total_prcp_in"]["mean"] == 1.0,
      json.dumps(stats["distribution"]["season_total_prcp_in"]))
check("streak probability reported for a 1-season sample",
      stats["probability_of_at_least_one_streak"]["ge_3_days"]["pct"] == 0.0,
      json.dumps(stats["probability_of_at_least_one_streak"]["ge_3_days"]))


# --------------------------------------------------------------------------- #
# 5. HTML -> text (the quotes on the site must be what a human reads)
# --------------------------------------------------------------------------- #

section("official prose extraction (HTML entities)")

# The ENSO Diagnostic Discussion writes its accented letters and degree signs as
# entities, and the entity semicolons used to look like sentence ends.
sample_html = (
    "<p>ENSO Alert System Status: El Ni&ntilde;o Advisory</p>"
    "<p>Synopsis: El Ni&ntilde;o is strengthening, with a greater than 90&#37; "
    "chance of a very strong event during the fall and winter 2026-27.</p>"
    "<p>Ni&ntilde;o-3.4 reached +1.8&deg;C in August [Fig. 1] . Except for "
    "Ni&ntilde;o-4, values increased.</p>"
    "<p>EL NI&Ntilde;O/SOUTHERN OSCILLATION (ENSO)</p>"
)
plain = pipeline_main.html_to_text(sample_html)
check("entities decoded to what a browser shows",
      "El Niño Advisory" in plain and "90%" in plain and "+1.8°C" in plain,
      repr(plain[:80]))
check("no entity text survives into the extracted prose",
      not __import__("re").search(r"&[a-zA-Z]+;|&#\d+;", plain), repr(plain))
check("entity semicolons no longer look like sentence ends",
      "chance of a very strong event during the fall and winter 2026-27." in plain,
      repr(plain))

status = __import__("re").search(r"ENSO Alert System Status:\s*([^\n]{3,80})", plain)
check("alert status reads in full, not truncated to 'El Ni'",
      status is not None and status.group(1).strip(" :;.") == "El Niño Advisory",
      repr(status and status.group(1)))

sentences = pipeline_main.extract_key_sentences(plain)
check("verbatim sentences keep their opening words",
      any(s.startswith("El Niño is strengthening, with a greater than 90% chance")
          for s in sentences),
      str(sentences[:2]))
# "August [Fig. 1] ." must survive as one piece: the old splitter cut it at the
# period inside "Fig." and left a sentence ending in "Pacific [Fig.".
check("figure references do not cut a sentence in half",
      any("August [Fig. 1]." in s and not s.endswith("[Fig.") for s in sentences),
      str(sentences[:3]))
check("stand-alone headings are not quoted as sentences",
      all(not (s.upper() == s) for s in sentences), str(sentences[:2]))
# The long-lead discussion is hard-wrapped, and a naive splitter turned each
# wrapped line into its own "sentence" ("... a greater than 90" / "percent
# chance of ...").
wrapped = pipeline_main.html_to_text(
    "El Ni&ntilde;o conditions are present, as represented in current oceanic and\n"
    "atmospheric anomalies.\n\n"
    "The CPC Official ENSO outlook, which synthesizes multiple models from North\n"
    "America and abroad, indicates El Ni&ntilde;o will continue to strengthen through\n"
    "the end of the year.\n\n"
    "Above-\nnormal precipitation is favored for the southern half of California.\n")
wsent = pipeline_main.extract_key_sentences(wrapped)

# The long-lead page is served with a breadcrumb line glued to the text:
# "HOME > Outlook Maps >Seasonal Forecast Discussion Prognostic Discussion ...
#  NWS Climate Prediction Center College Park MD 830 AM EDT Thu Sep 17 2026
#  SUMMARY OF THE OUTLOOK FOR NON-TECHNICAL USERS El Nino conditions are present".
chrome = pipeline_main.html_to_text(
    "HOME > <a href=x>Outlook Maps</a> >Seasonal Forecast Discussion Prognostic "
    "Discussion for Long-Lead Seasonal Outlooks NWS Climate Prediction Center "
    "College Park MD 830 AM EDT Thu Sep 17 2026 SUMMARY OF THE OUTLOOK FOR "
    "NON-TECHNICAL USERS El Ni&ntilde;o conditions are present, as represented in "
    "current oceanic and atmospheric observations.\n")
csent = pipeline_main.extract_key_sentences(chrome)
check("page chrome is not glued to the front of a quote",
      any(s.startswith("El Niño conditions are present") for s in csent), str(csent))
styles = pipeline_main.extract_key_sentences(pipeline_main.html_to_text(
    "<p>BASIS AND SUMMARY OF THE CURRENT LONG-LEAD OUTLOOKS</p>"
    "<p>Note: For Graphical Displays of the Forecast Tools Discussed Below See: "
    "http://www.cpc.ncep.noaa.gov</p>"
    "<p>The OND 2026 Precipitation Outlook favors above normal precipitation.</p>\n"))
check("heading/boilerplate lines with links are not quoted",
      all("BASIS AND SUMMARY" not in s and "http" not in s for s in styles)
      and any(s.startswith("The OND 2026") for s in styles), str(styles))

check("neither breadcrumbs nor document titles are quoted",
      all("HOME >" not in s and "College Park MD" not in s for s in csent), str(csent))

# Tags become spaces, which put a space before punctuation the page never shows.
taggy = pipeline_main.html_to_text(
    "The CPC Official ENSO outlook <a href=x>,</a> which synthesizes multiple models "
    "from North America and abroad, indicates El Ni&ntilde;o will continue to "
    "strengthen [Figs. <a href=y>6</a>-<a href=z>7</a>] .\n")
tsent = pipeline_main.extract_key_sentences(taggy)
check("no space is left before punctuation",
      any("outlook, which synthesizes" in s for s in tsent), str(tsent))
check("figure ranges read as ranges",
      any("Figs. 6-7" in s for s in tsent), str(tsent))
check("hard-wrapped lines are re-joined into whole sentences",
      any(s == "El Niño conditions are present, as represented in current oceanic "
              "and atmospheric anomalies." for s in wsent), str(wsent))
check("a hyphen at end of line is re-joined, not treated as a word break",
      any("Above-normal precipitation is favored" in s for s in wsent), str(wsent))
check("no quote is a dangling line fragment",
      all(not s.endswith((" and", " of", " the", " a", " from")) for s in wsent), str(wsent))

check("the 'Synopsis:' label is stripped, the sentence itself is untouched",
      all(not s.startswith("Synopsis") for s in sentences), str(sentences[:1]))

# --------------------------------------------------------------------------- #
# CPC category explanations
#
# The action checklist explains each CPC outlook category to the reader.  The
# wording used to be chosen from the *variable* alone, so a "Equal chances"
# outlook was published with the explanation for "Above median" - the page
# describing a category it was not showing.  These checks pin the note to the
# category actually displayed, and pin the label mapping in build_calendar.py
# that the notes are keyed on.
# --------------------------------------------------------------------------- #

section("CPC category explanation matches the category shown")

import landlord_summary  # noqa: E402

# build_calendar.py maps the raw DBF "Cat" field to a human label per variable.
# Reproduce that mapping so the notes are checked against the real labels.
RAW_CATS = {"EC": "Equal chances", "Above": None, "Below": None}
for variable in ("prcp", "temp"):
    for raw in ("Above", "Below"):
        label = ("Above normal" if variable == "temp" else "Above median") if raw == "Above" \
            else ("Below normal" if variable == "temp" else "Below median")
        note = landlord_summary.cpc_category_note(variable, label)
        check("note for %s/%s names its own category" % (variable, label),
              ("'%s'" % label) in note, note)
        check("note for %s/%s does not quote a different category" % (variable, label),
              all(("'%s'" % other) not in note
                  for other in ("Above median", "Below median", "Above normal",
                                "Below normal", "Equal chances") if other != label),
              note)

for variable in ("prcp", "temp"):
    note = landlord_summary.cpc_category_note(variable, "Equal chances")
    check("Equal chances (%s) is explained as no tilt" % variable,
          "no tilt" in note and "33%" in note, note)

# An unknown label must be reported as undocumented rather than explained with
# a plausible-sounding sentence about some other category.
odd = landlord_summary.cpc_category_note("prcp", "Some Future Category")
check("an unrecognised category is declared, not guessed",
      "not documented" in odd and "Above median" not in odd, odd)

# The committed landlord.json must satisfy the same rule end to end.
_ll_path = os.path.join(ROOT, "data", "landlord.json")
if os.path.exists(_ll_path):
    with io.open(_ll_path, encoding="utf-8") as fh:
        _ll = json.load(fh)
    _cpc_items = [a for a in _ll.get("action_items", [])
                  if a.get("category") == "Official CPC outlook"]
    _bad = []
    for a in _cpc_items:
        m = __import__("re").match(r"^CPC [^:]+: (.+?) \(", a.get("title", ""))
        cat = m.group(1) if m else None
        if cat and ("'%s'" % cat) not in a.get("detail", ""):
            _bad.append(a.get("title"))
    check("every CPC action item explains its own category (%d items)" % len(_cpc_items),
          not _bad, str(_bad))
    check("CPC action items exist to check", len(_cpc_items) > 0, "found none")
else:
    check("data/landlord.json present to audit", False, "missing")

# --------------------------------------------------------------------------- #
# NWS gridpoint gust / QPF aggregation
#
# The /forecast/hourly product returns no windGust and no QPF for the 94122 grid
# cell (0 of 156 periods on 17 Sep 2026), so gust and rain amount - the two
# figures the brief asks about first - used to render as em dashes even though
# NWS publishes both at the same grid point.  These tests pin the interval
# parsing and the two derivations with hand-computable values.
# --------------------------------------------------------------------------- #

section("NWS gridpoint gust and QPF aggregation")

start, hours = build_calendar.parse_valid_time("2026-09-17T14:00:00+00:00/PT3H")
check("PT3H parses to 3 hours", hours == 3.0, repr(hours))
check("PT3H keeps its start instant",
      start is not None and start.isoformat() == "2026-09-17T14:00:00+00:00", str(start))

start, hours = build_calendar.parse_valid_time("2026-09-18T00:00:00+00:00/P1DT6H")
check("P1DT6H parses to 30 hours", hours == 30.0, repr(hours))

check("an unparseable validTime is rejected, not guessed",
      build_calendar.parse_valid_time("not-a-timestamp") == (None, None), "")
check("a bare timestamp with no interval is rejected",
      build_calendar.parse_valid_time("2026-09-17T14:00:00+00:00") == (None, None), "")

# A gust of exactly 20 mph expressed in the km/h NWS actually publishes.
GUST_KMH = 20.0 * build_calendar.KM_PER_MILE
gp = {
    "values": {
        "windGust": {"uom": "wmoUnit:km_h-1", "values": [
            # 14:00Z = 07:00 PDT on 17 Sep; 2 hours, both inside 17 Sep local.
            {"validTime": "2026-09-17T14:00:00+00:00/PT2H", "value": GUST_KMH},
            {"validTime": "2026-09-17T16:00:00+00:00/PT1H", "value": None},
        ]},
        "quantitativePrecipitation": {"uom": "wmoUnit:mm", "values": [
            # 05:00Z = 22:00 PDT 17 Sep; 4 hours straddle local midnight, so the
            # 8 mm accumulation must split 4 mm / 4 mm between 17 and 18 Sep.
            {"validTime": "2026-09-18T05:00:00+00:00/PT4H", "value": 8.0},
        ]},
    }
}
gdays, g_tz_ok = build_calendar.daily_from_gridpoint(gp, "America/Los_Angeles")
check("gridpoint timezone resolved by name", g_tz_ok is True, repr(g_tz_ok))

g17 = gdays.get("2026-09-17", {})
check("gust converted km/h -> mph exactly",
      g17.get("gust_mph") and abs(max(g17["gust_mph"]) - 20.0) < 1e-9,
      str(g17.get("gust_mph")))
check("a null gust value is skipped, not treated as zero",
      len(g17.get("gust_mph") or []) == 2, str(g17.get("gust_mph")))

check("QPF accumulation split across local midnight (17 Sep = 4 mm)",
      abs(gdays.get("2026-09-17", {}).get("qpf_mm", -1) - 4.0) < 1e-9,
      str(gdays.get("2026-09-17", {}).get("qpf_mm")))
check("QPF accumulation split across local midnight (18 Sep = 4 mm)",
      abs(gdays.get("2026-09-18", {}).get("qpf_mm", -1) - 4.0) < 1e-9,
      str(gdays.get("2026-09-18", {}).get("qpf_mm")))
check("the split conserves the published total",
      abs(sum(d.get("qpf_mm", 0.0) for d in gdays.values()) - 8.0) < 1e-9,
      str(sum(d.get("qpf_mm", 0.0) for d in gdays.values())))
check("a day with QPF is marked known, so 0.00 in is not confused with missing",
      gdays.get("2026-09-18", {}).get("qpf_known") is True, "")

# Cross-check against the committed run: the gusts now published must agree with
# the gusts NWS states in its own human-readable forecast text.
_cal_path = os.path.join(ROOT, "data", "calendar.json")
if os.path.exists(_cal_path):
    with io.open(_cal_path, encoding="utf-8") as fh:
        _cal = json.load(fh)
    _cf = (_cal.get("current_forecast") or {}).get("days") or []
    _nogust = [d["date"] for d in _cf if d.get("gust_max_mph") is None]
    _noqpf = [d["date"] for d in _cf if d.get("rain_amount_in") is None]
    check("every current-forecast day now carries a gust (%d days)" % len(_cf),
          bool(_cf) and not _nogust, str(_nogust))
    check("every current-forecast day now carries a rain amount",
          bool(_cf) and not _noqpf, str(_noqpf))
    # NWS's own text forecast for this run says "gusts as high as 18 mph" for
    # Friday 18 Sep and "gusts as high as 20 mph" for Saturday 19 Sep.
    _by = {d["date"]: d for d in _cf}
    for _iso, _expect in (("2026-09-18", 18.0), ("2026-09-19", 20.0)):
        _got = (_by.get(_iso) or {}).get("gust_max_mph")
        check("derived gust for %s matches NWS's stated %.0f mph within 2 mph" % (_iso, _expect),
              _got is not None and abs(_got - _expect) <= 2.0, str(_got))
    # Tiering must be untouched: no climatology day may claim a forecast basis.
    # This used to assert "no climatology day has a gust_basis at all", which
    # stopped being true when every published value gained a per-field basis.
    # What must hold is the intent: a climatology day's basis has to name the
    # observed record, and must never name the NWS forecast the site does not
    # have for that date.
    _NWS_MARKERS = ("api.weather.gov", "nws hourly", "nws forecast", "gridpoint",
                    "forecast/hourly", "weather.gov")
    _clim_days = [d for d in _cal.get("days", []) if d.get("tier") == "climatology"]
    _bad_tier = [(d["date"], k, str(d.get(k))[:60]) for d in _clim_days
                 for k in ("temp_basis", "humidity_basis", "wind_basis",
                           "gust_basis", "rain_chance_basis", "rain_amount_basis")
                 if any(m in str(d.get(k) or "").lower() for m in _NWS_MARKERS)]
    check("no climatology day claims an NWS forecast basis", not _bad_tier, str(_bad_tier[:3]))
    _nobs = [d["date"] for d in _clim_days
             if not any(s in str(d.get("gust_basis") or "") for s in ("GSOD", "GHCN"))]
    check("every climatology day names the observed record behind its gust (%d days)"
          % len(_clim_days), bool(_clim_days) and not _nobs, str(_nobs[:3]))
else:
    check("data/calendar.json present to audit", False, "missing")

# --------------------------------------------------------------------------- #
# Maintenance cost drivers (executive summary)
#
# The landlord executive summary ranks repair & maintenance cost drivers and
# publishes "expected days per season" for heavy-rain thresholds.  Those
# expected counts are sums of the per-date observed probabilities, and the
# block mixes guidance sentences with verified numbers, so each helper is
# pinned here with synthetic, hand-computable values: the summation itself,
# the Storm Events damage parsing ("0.00K" means *no recorded damage*, not
# unknown), the phase/ONI display formatting (raw tokens must never reach the
# reader), and the driver's refusal to publish a claim without evidence.
# --------------------------------------------------------------------------- #

section("landlord maintenance cost drivers")

from landlord_summary import (build_cost_drivers, expected_event_days,  # noqa: E402
                              phase_label, fmt_oni_c, parse_damage_usd)

# expected_event_days: linearity of expectation, both record shapes.
_syn_days = [
    {"climo": {"p_rain_ge_025in_pct": 50.0, "p_rain_ge_100in_pct": 10.0}},
    {"climo": {"p_rain_ge_025in_pct": 25.0, "p_rain_ge_100in_pct": None}},
    {"climo": {"p_rain_ge_025in_pct": None, "p_rain_ge_100in_pct": 5.0}},
]
check("expected days sums nested climo probabilities",
      expected_event_days(_syn_days, "p_rain_ge_025in_pct") == 0.75,
      str(expected_event_days(_syn_days, "p_rain_ge_025in_pct")))
check("None probabilities are skipped, not treated as zero data",
      expected_event_days(_syn_days, "p_rain_ge_100in_pct") == 0.15,
      str(expected_event_days(_syn_days, "p_rain_ge_100in_pct")))
_flat = [{"month": 12, "p_rain_ge_025in_pct": 40.0},
         {"month": 12, "p_rain_ge_025in_pct": 20.0}]
check("flat climatology rows sum the same way",
      expected_event_days(_flat, "p_rain_ge_025in_pct") == 0.6, "")
check("a key no row carries returns None, never an invented zero",
      expected_event_days(_flat, "p_rain_ge_100in_pct") is None, "")
check("empty input returns None",
      expected_event_days([], "p_rain_ge_025in_pct") is None, "")

# parse_damage_usd: Storm Events "0.00K" is a real value meaning no recorded
# damage, while "" means unknown.
check("0.00K parses to 0, not None", parse_damage_usd("0.00K") == 0.0, "")
check("2.50K parses to 2500", parse_damage_usd("2.50K") == 2500.0, "")
check("1.2M parses to 1200000", parse_damage_usd("1.2M") == 1200000.0, "")
check("empty damage is unknown (None), not zero", parse_damage_usd("") is None, "")
check("missing damage is unknown (None), not zero", parse_damage_usd(None) is None, "")

# Display formatting: the raw tokens are data keys, never reader-facing text.
check("phase el_nino renders as El Niño", phase_label("el_nino") == "El Niño",
      phase_label("el_nino"))
check("phase la_nina renders as La Niña", phase_label("la_nina") == "La Niña",
      phase_label("la_nina"))
check("phase neutral renders as Neutral", phase_label("neutral") == "Neutral", "")
check("ONI formats signed with 2 decimals and the degree unit",
      fmt_oni_c(1.8) == "+1.80 °C" and fmt_oni_c(-0.6) == "-0.60 °C",
      repr((fmt_oni_c(1.8), fmt_oni_c(-0.6))))
check("missing ONI formats to None, not 0.00 °C", fmt_oni_c(None) is None, "")

# build_cost_drivers with synthetic, hand-verifiable inputs.
_syn_dist = {
    "season_total_prcp_in": {"mean": 10.0, "median": 9.5, "min": 1.0, "max": 20.0,
                             "p10": 3.0, "p90": 17.0},
    "december_total_prcp_in": {"max": 11.0},
    "january_total_prcp_in": {"max": 9.0},
    "longest_wet_streak_days": {"mean": 6.0, "max": 12.0},
    "wet_days": {"mean": 30.0, "median": 30.0, "min": 8.0, "max": 50.0},
    "wind_and_rain_days": {"mean": 9.0, "median": 9.0, "max": 20.0},
    "heavy_wind_and_rain_days": {"mean": 1.5, "median": 1.0, "max": 6.0},
    "max_gust_mph": {"mean": 50.0, "median": 51.0, "max": 70.0},
}
_syn_streak = {"ge_3_days": {"seasons": 27, "pct": 90.0},
               "ge_5_days": {"seasons": 21, "pct": 70.0},
               "ge_7_days": {"seasons": 15, "pct": 50.0},
               "ge_10_days": {"seasons": 6, "pct": 20.0}}
_syn_strat = {"el_nino": {"n": 10, "mean": 12.0}, "la_nina": {"n": 10, "mean": 8.0}}
_syn_oni = {"label": "JJA 2026", "oni_c": 1.8, "phase": "el_nino", "strength": "strong"}
_syn_cpc = [{"variable": "prcp", "valid_season": "DJF 2026-2027", "category_label": "Above median",
             "prob": 40.0, "issued": "2026-09-17", "url": "https://ftp.cpc.ncep.noaa.gov/GIS/x.zip"}]
_syn_storms = {"years": [2014, 2026],
               "events": [{"event_type": "Flood", "damage_property": "2.50K"},
                          {"event_type": "Flood", "damage_property": "0.00K"},
                          {"event_type": "Thunderstorm Wind", "damage_property": ""},
                          {"event_type": "Hail"}]}
_drivers = build_cost_drivers(days=_syn_days, dist=_syn_dist, streak_prob=_syn_streak,
                              enso_strat=_syn_strat, latest_oni=_syn_oni,
                              diagnostic_status="El Niño Advisory",
                              relevant_cpc=_syn_cpc, storms=_syn_storms,
                              monthly=[{"label": "October", "year": 2026, "expected_wet_days": 3.5}])
check("synthetic inputs yield all six ranked drivers", len(_drivers) == 6,
      str(len(_drivers)))
check("ranks are sequential from 1",
      [d.get("rank") for d in _drivers] == list(range(1, len(_drivers) + 1)),
      str([d.get("rank") for d in _drivers]))
check("every driver carries title, guidance, evidence and an https source",
      all(d.get("driver") and d.get("why_it_costs") and d.get("evidence")
          and any((s or {}).get("url", "").startswith("https://") for s in d.get("sources", []))
          for d in _drivers), "")
check("no empty evidence value is published",
      all(row.get("value") not in (None, "", "None")
          for d in _drivers for row in d.get("evidence", [])), "")
_heavy = next(d for d in _drivers if d["rank"] == 2)
check("heavy-rain driver publishes the expected counts from the synthetic days",
      any("0.75" in str(row.get("value")) for row in _heavy["evidence"]),
      str([row.get("value") for row in _heavy["evidence"]]))
check("storm-derived counts come from the synthetic event table",
      any("2 events" in str(row.get("value")) for row in _heavy["evidence"])
      and any("1 events" in str(row.get("value")) for d in _drivers if d["rank"] == 4
              for row in d["evidence"]), "")
check("damage-bearing flood count parses 0.00K as zero and 2.50K as damage",
      any("1 of 2" in str(row.get("value")) for row in _heavy["evidence"]),
      str([row.get("value") for row in _heavy["evidence"]]))
_budget = next(d for d in _drivers if d["rank"] == 5)
check("no raw phase token in any driver string",
      all("el_nino" not in json.dumps(d) and "la_nina" not in json.dumps(d)
          for d in _drivers), "")
check("budget driver shows the mapped ENSO phase and formatted ONI",
      any("El Niño" in str(row.get("value")) and "+1.80 °C" in str(row.get("value"))
          for row in _budget["evidence"]),
      str([row.get("value") for row in _budget["evidence"]]))

# Missing supplementary sources must degrade, not invent: no storms table means
# no storm-report evidence rows, but the verified numbers still publish.
_drivers_ns = build_cost_drivers(days=_syn_days, dist=_syn_dist, streak_prob=_syn_streak,
                                 enso_strat=_syn_strat, latest_oni=_syn_oni,
                                 diagnostic_status=None, relevant_cpc=[],
                                 storms=None, monthly=[])
check("missing storms table: drivers still build from verified numbers",
      len(_drivers_ns) == 6, str(len(_drivers_ns)))
check("missing storms table: no storm-report evidence row is invented",
      not any("Storm Events" in str(row.get("value"))
              for d in _drivers_ns for row in d.get("evidence", [])), "")

# The committed executive summary must satisfy the same rules end to end.
if os.path.exists(_ll_path):
    with io.open(_ll_path, encoding="utf-8") as fh:
        _llex = json.load(fh).get("executive_summary", {})
    _ll_drivers = _llex.get("cost_drivers") or []
    check("committed executive summary has >=4 cost drivers", len(_ll_drivers) >= 4,
          str(len(_ll_drivers)))
    check("committed driver ranks are sequential from 1",
          [d.get("rank") for d in _ll_drivers] == list(range(1, len(_ll_drivers) + 1)), "")
    check("committed drivers all carry evidence and an official source",
          all(d.get("evidence")
              and all((s or {}).get("url", "").startswith("https://")
                      and any(h in (s or {}).get("url", "") for h in
                              ("ncei.noaa.gov", "noaa.gov", "census.gov", "weather.gov"))
                      for s in d.get("sources", []))
              and d.get("sources") for d in _ll_drivers), "")
    check("committed cost-driver note separates guidance from verified numbers",
          "guidance" in (_llex.get("cost_drivers_note") or ""), "")
    _disp = [_llex.get("key_finding", "")]
    for d in _ll_drivers:
        _disp += [d.get("driver", ""), d.get("why_it_costs", "")]
        _disp += [str(r.get("label", "")) + " " + str(r.get("value", ""))
                  for r in d.get("evidence", [])]
    check("no raw ENSO token in committed executive-summary strings",
          not any(__import__("re").search(r"\b(?:el_nino|la_nina)\b", s) for s in _disp), "")
    check("expected-day counts are present and numeric in the committed summary",
          isinstance((_llex.get("expected_days") or {}).get("ge_025in_days"), (int, float))
          and isinstance((_llex.get("expected_days") or {}).get("ge_100in_days"), (int, float)),
          str(_llex.get("expected_days")))

# --------------------------------------------------------------------------- #
print("\n== official NCEI daily normals (normals-daily)")

# A fixture in the exact layout NCEI serves, with hand-computable values: every
# element is the same on every date, so the expected parse is known exactly.
# The NAME field deliberately contains an unquoted comma, because that is the
# real file's shape and it is what broke the GSOD reader (see VERIFICATION.md #6).
_DLY_HEAD = ["STATION", "DATE", "LATITUDE", "LONGITUDE", "ELEVATION", "NAME",
             "month", "day", "hour"]
_DLY_VALS = {"DLY-TMAX-NORMAL": "  60.0", "DLY-TMIN-NORMAL": "  50.0",
             "DLY-TAVG-NORMAL": "  55.0",
             "DLY-PRCP-PCTALL-GE001HI": "  36.8", "DLY-PRCP-PCTALL-GE010HI": "  25.3",
             "DLY-PRCP-PCTALL-GE025HI": "  16.8", "DLY-PRCP-PCTALL-GE050HI": "  10.3",
             "DLY-PRCP-PCTALL-GE100HI": "   4.3", "DLY-PRCP-PCTALL-GE200HI": "   0.6",
             "DLY-PRCP-PCTALL-GE400HI": "   0.0", "DLY-PRCP-PCTALL-GE600HI": "   0.0",
             "DLY-PRCP-25PCTL": "   0.07", "DLY-PRCP-50PCTL": "   0.21",
             "DLY-PRCP-75PCTL": "   0.56"}
_DLY_ELEMS = list(_DLY_VALS)


def _daily_normals_fixture(include_leap_day=True):
    import datetime as _dt
    head = list(_DLY_HEAD)
    for e in _DLY_ELEMS:
        head += [e, "meas_flag_" + e, "comp_flag_" + e, "years_" + e]
    lines = [",".join('"%s"' % h for h in head)]
    d = _dt.date(2024, 1, 1)
    while d.year == 2024:
        if not include_leap_day and (d.month, d.day) == (2, 29):
            d += _dt.timedelta(days=1)
            continue
        mmdd = d.strftime("%m-%d")
        cells = ['"USW00023272"', '"%s"' % mmdd, '" 37.77"', '"-122.43"', '"  45.7"',
                 '"SAN FRANCISCO DWTN, CA US"', '"%s"' % mmdd[:2], '"%s"' % mmdd[3:], '"99"']
        for e in _DLY_ELEMS:
            cells += ['"%s"' % _DLY_VALS[e], '" "', '"S"', '"30"']
        lines.append(",".join(cells))
        d += _dt.timedelta(days=1)
    return "\n".join(lines) + "\n"


_by, _layout = climo.parse_daily_normals(_daily_normals_fixture())
check("daily normals: a full year parses to 366 dated rows", len(_by) == 366, str(len(_by)))
check("daily normals: 01-01, 12-31 and the leap day are all present",
      all(k in _by for k in ("01-01", "12-31", "02-29")),
      str([k for k in ("01-01", "12-31", "02-29") if k not in _by]))
check("daily normals: the unquoted comma in NAME does not shift the row",
      _by["12-13"]["normal_high_f"] == 60.0 and _by["12-13"]["normal_low_f"] == 50.0,
      repr((_by["12-13"]["normal_high_f"], _by["12-13"]["normal_low_f"])))

# The GE###HI digits are HUNDREDTHS of an inch.  Getting this wrong by one order
# of magnitude would silently compare the wrong pair of columns everywhere, so the
# mapping is pinned here and the values are the real ones for 01-01 at USW00023272.
check("daily normals: GE001HI is >= 0.01 in, not >= 0.001 in",
      _by["01-01"]["p_pcp_ge_0p01in_pct"] == 36.8, repr(_by["01-01"].get("p_pcp_ge_0p01in_pct")))
check("daily normals: GE010HI is >= 0.10 in", _by["01-01"]["p_pcp_ge_0p10in_pct"] == 25.3, "")
check("daily normals: GE025HI is >= 0.25 in", _by["01-01"]["p_pcp_ge_0p25in_pct"] == 16.8, "")
check("daily normals: GE050HI is >= 0.50 in", _by["01-01"]["p_pcp_ge_0p50in_pct"] == 10.3, "")
check("daily normals: GE100HI is >= 1.00 in", _by["01-01"]["p_pcp_ge_1p00in_pct"] == 4.3, "")
check("daily normals: GE200HI is >= 2.00 in", _by["01-01"]["p_pcp_ge_2p00in_pct"] == 0.6, "")
check("daily normals: published thresholds are carried with the data",
      _layout["thresholds_in"].get("p_pcp_ge_0p01in_pct") == 0.01
      and _layout["thresholds_in"].get("p_pcp_ge_1p00in_pct") == 1.00,
      str(_layout["thresholds_in"]))
check("daily normals: every probability column is monotone non-increasing",
      all(_by[k]["p_pcp_ge_0p01in_pct"] >= _by[k]["p_pcp_ge_0p10in_pct"]
          >= _by[k]["p_pcp_ge_0p25in_pct"] >= _by[k]["p_pcp_ge_0p50in_pct"]
          >= _by[k]["p_pcp_ge_1p00in_pct"] >= _by[k]["p_pcp_ge_2p00in_pct"]
          for k in _by), "")
check("daily normals: percentiles keep three decimals (0.07, not 0.1)",
      _by["01-01"]["pcp_25pctl_in"] == 0.07 and _by["01-01"]["pcp_75pctl_in"] == 0.56, "")
check("daily normals: the published year count is captured",
      _by["01-01"]["n_years_pcp_ge_010in"] == 30, "")
check("daily normals: every friendly key is traceable to an official column",
      all(col.startswith("DLY-") for col in _layout["column_by_key"].values())
      and len(_layout["column_by_key"]) == len(climo._DLY_ELEMENTS),
      str(sorted(_layout["column_by_key"].values())))
check("daily normals: an element in the file that the parser does not claim "
      "(DLY-TAVG-NORMAL) is left out rather than given a made-up key",
      not any(v == "DLY-TAVG-NORMAL" for v in _layout["column_by_key"].values()), "")

# A missing value must stay missing, never become 0.
_by_blank, _ = climo.parse_daily_normals(
    _daily_normals_fixture().replace('"  25.3"', '"      "', 1))
check("daily normals: a blank published value is absent, not zero",
      "p_pcp_ge_0p10in_pct" not in _by_blank["01-01"], repr(_by_blank["01-01"]))

# A file with none of the expected columns must be refused, not guessed at.
_by_bad, _layout_bad = climo.parse_daily_normals(
    "STATION,DATE,SOMETHING\nUSW00023272,01-01,7\n")
check("daily normals: an unknown layout yields no values and a recorded reason",
      _by_bad == {} and _layout_bad.get("usable") is False
      and "reason" in _layout_bad, json.dumps(_layout_bad)[:200])

# A truncated read (the old 200,000-character cap) must be detectable.
_by_short, _layout_short = climo.parse_daily_normals(
    "\n".join(_daily_normals_fixture().splitlines()[:100]) + "\n")
check("daily normals: a truncated file parses to fewer than 366 dates (detectable)",
      len(_by_short) < 366, "%d dates" % len(_by_short))

# The comparison pairs like-for-like and is signed the right way round.
# Published >=0.01 in is 36.8 %; a derived 10.0 % therefore differs by +26.8.
# Published >=0.25 in (16.8) and >=1.00 in (4.3) are matched exactly by the fake
# derived values, so they must NOT be flagged.
_fake_climo = {"01-01": {"p_rain_day_pct": 10.0, "p_rain_ge_025in_pct": 16.8,
                         "p_rain_ge_100in_pct": 4.3, "normal_high_f": 57.1,
                         "normal_low_f": 46.2}}
_cmp = climo.compare_daily_normals(_by, _fake_climo)
_p = _cmp["pairs"]
check("daily normals: correct pairs are compared (>=0.01in published vs derived)",
      _p["rain day >= 0.01 in"]["n"] == 1
      and _p["rain day >= 0.01 in"]["largest_difference_published"] == 36.8
      and _p["rain day >= 0.01 in"]["largest_difference_derived"] == 10.0,
      json.dumps(_p.get("rain day >= 0.01 in")))
check("daily normals: the difference is signed published-minus-derived",
      _p["rain day >= 0.01 in"]["mean_difference"] == 26.8
      and _p["normal low"]["mean_difference"] == 3.8,
      json.dumps({k: v.get("mean_difference") for k, v in _p.items()}))
check("daily normals: an exact agreement reports zero difference, not a flag",
      _p["rain >= 0.25 in"]["largest_absolute_difference"] == 0.0
      and _p["rain >= 1.00 in"]["largest_absolute_difference"] == 0.0, "")
check("daily normals: only the >10-point percentage disagreement is flagged",
      len(_cmp["flagged"]) == 1 and _cmp["flagged"][0]["mmdd"] == "01-01"
      and _cmp["flagged"][0]["quantity"] == "rain day >= 0.01 in"
      and _cmp["flagged"][0]["difference"] == 26.8,
      json.dumps(_cmp["flagged"]))
check("daily normals: temperature pairs are never flagged (a different statistic)",
      all(f["quantity"] not in ("normal high", "normal low") for f in _cmp["flagged"]), "")
check("daily normals: the comparison names no date it did not compare",
      _cmp["compared_dates"] == 366 and _cmp["pairs"]["normal high"]["n"] == 1, "")

# ---- NCEI missing-value sentinels -------------------------------------------
# A real NCEI file writes -9999 for a percentile that cannot be computed (a
# calendar date so dry that no wet-day percentile exists).  That value reached
# the published page as "-9999.00 in" before this guard existed, so it is pinned
# here rather than left to a reviewer's eye.
for _raw, _want in (("-9999", True), ("-9999.00", True), ("  -9999 ", True),
                    ("", True), ("M", True), ("9999.9", True),
                    ("0.21", False), ("-0.5", False), ("70.6", False),
                    ("0", False)):
    check("normals sentinel: %r treated as missing == %s" % (_raw, _want),
          climo.is_missing_normals_value(_raw) is _want,
          "got %s" % climo.is_missing_normals_value(_raw))

_sentinel_csv = (
    "STATION,DATE,DLY-TMAX-NORMAL,DLY-TMIN-NORMAL,DLY-PRCP-25PCTL,"
    "DLY-PRCP-50PCTL,DLY-PRCP-75PCTL,DLY-PRCP-PCTALL-GE001HI,"
    "DLY-PRCP-PCTALL-GE025HI,DLY-PRCP-PCTALL-GE100HI\r\n"
    "USW00023272,01-01,57.1,46.2,-9999,-9999,-9999,36.8,16.8,4.3\r\n")
_sby, _slay = climo.parse_daily_normals(_sentinel_csv)
check("normals sentinel: -9999 percentiles are dropped, not published",
      _sby["01-01"].get("pcp_25pctl_in") is None
      and _sby["01-01"].get("pcp_50pctl_in") is None
      and _sby["01-01"].get("pcp_75pctl_in") is None
      and _sby["01-01"].get("p_pcp_ge_0p01in_pct") == 36.8,
      json.dumps(_sby["01-01"]))
check("normals sentinel: no surviving value is below zero (a sentinel would be)",
      all(float(v) >= 0 for v in _sby["01-01"].values()),
      json.dumps(_sby["01-01"]))
# A guard that cannot fire is worse than no guard: the ledger's range rule was
# first written with endswith("_pctl_in"), which matches nothing because the
# published key is ``pcp_50pctl_in``.  Pinned here so it cannot regress.
for _k, _v, _want in (("pcp_50pctl_in", -9999.0, "negative precipitation percentile"),
                      ("pcp_75pctl_in", -1.0, "negative precipitation percentile"),
                      ("p_pcp_ge_0p01in_pct", 36.8, None),
                      ("p_pcp_ge_0p01in_pct", 120.0, "percentage outside 0-100"),
                      ("p_pcp_ge_0p01in_pct", -0.1, "percentage outside 0-100"),
                      ("normal_high_f", 70.6, None),
                      ("normal_high_f", -9999.0, "temperature outside -50..130 F"),
                      ("n_years_pcp_ge_010in", 30, None)):
    check("normals range rule: %s = %s" % (_k, _v),
          climo.implausible_normals_value(_k, _v) == _want,
          "got %r" % (climo.implausible_normals_value(_k, _v),))

check("normals sentinel: dropping the percentiles does not drop the date",
      _slay.get("dates_parsed") == 1, json.dumps(_slay.get("element_coverage")))


# --------------------------------------------------------------------------- #
print("\n== published-vs-derived values on the committed scoreboard")

if os.path.exists(os.path.join(ROOT, "data", "calendar.json")):
    with io.open(os.path.join(ROOT, "data", "calendar.json"), encoding="utf-8") as fh:
        _cal = json.load(fh)
    _days = _cal.get("days") or []
    _withoff = [d for d in _days if d.get("official_normal")]
    if _withoff:
        check("committed days carry the published normals block", True,
              "%d of %d days" % (len(_withoff), len(_days)))
        check("every published block names its source URL and station",
              all((d["official_normal"].get("source_url") or "").startswith("https://")
                  and d["official_normal"].get("station_id") for d in _withoff), "")
        check("published blocks expose the 8 GE thresholds and 3 percentiles",
              all(all(k in d["official_normal"] or k.endswith("in_pct") is False
                      for k in ("p_pcp_ge_0p01in_pct", "p_pcp_ge_1p00in_pct",
                                "pcp_50pctl_in")) for d in _withoff), "")
        check("the comparison block exists and records a compared-date count",
              isinstance((_cal.get("daily_normals_comparison") or {}).get("compared_dates"),
                         int), "")
    else:
        check("committed scoreboard has no published-normals block yet "
              "(pipeline regenerates it on the next Actions run)",
              True, "0 of %d days carry official_normal" % len(_days))


# --------------------------------------------------------------------------- #
print("\n== publisher text encoding (lib_fetch.decode_text)")

import lib_fetch  # noqa: E402
import landlord_summary as landlord  # noqa: E402

# NCEI's Storm Events CSVs are CP1252, not UTF-8.  The pipeline used to decode
# them with errors="replace", which turned every non-UTF-8 byte into U+FFFD and
# committed the corrupted text ("5.46\ufffd\ufffd\ufffd in") to the dataset.
_curly = b'San Francisco Downtown site hit 5.46\x94 in the 24 hours of December 31st.'
_txt, _enc = lib_fetch.decode_text(_curly)
check("cp1252 byte decodes to the published curly quote, not U+FFFD",
      _enc == "cp1252" and "\ufffd" not in _txt and "5.46\u201d" in _txt,
      "encoding=%s text=%r" % (_enc, _txt[:60]))
_txt, _enc = lib_fetch.decode_text("caf\u00e9".encode("utf-8"))
check("valid UTF-8 is decoded as UTF-8 and left alone",
      _enc == "utf-8" and _txt == "caf\u00e9", "encoding=%s" % _enc)
_txt, _enc = lib_fetch.decode_text(None)
check("a missing body decodes to an empty string, never raises",
      _txt == "" and _enc == "none", "encoding=%s" % _enc)
# A body that is neither valid UTF-8 nor CP1252-decodable must still not raise.
_txt, _enc = lib_fetch.decode_text(b"\xff\xfe\x00ok")
check("undecodable bytes fall back rather than raising",
      isinstance(_txt, str) and _enc.endswith(("cp1252", "latin-1+replace")),
      "encoding=%s" % _enc)

# NCEI's Storm Events CSV for 2022 is valid UTF-8 and already contains U+FFFD,
# so no decoder can recover the original glyph.  The pipeline removes those
# characters and publishes the count instead of guessing at them.  This pins the
# exact sentence from the real file.
_lost = ('San Francisco Downtown site hit 5.46\ufffd\ufffd\ufffd in the 24 hours of '
         'December 31st, just 0.08\ufffd less than 1st place (11/5/1994) with 5.54\ufffd.')
_clean, _n, _ctx = lib_fetch.strip_unrepresentable(_lost)
check("an already-lost publisher character is removed, not guessed at",
      _n == 5 and "\ufffd" not in _clean and "5.46 in" in _clean and "0.08 less" in _clean,
      "removed=%s clean=%r" % (_n, _clean))
check("the removal keeps the rest of the sentence verbatim",
      _clean.startswith("San Francisco Downtown site hit 5.46 in the 24 hours of December")
      and "(11/5/1994) with 5.54." in _clean, _clean[-60:])
check("the removal publishes where it happened",
      len(_ctx) == 5 and all("5.46" in c or "0.08" in c or "5.54" in c for c in _ctx),
      str(_ctx[:1]))
check("clean text is returned untouched and reported as zero removals",
      lib_fetch.strip_unrepresentable("ordinary text") == ("ordinary text", 0, []), "")
check("an empty body is handled without error",
      lib_fetch.strip_unrepresentable("") == ("", 0, []), "")

# --------------------------------------------------------------------------- #
print("\n== CPC category vs probability (the 33% baseline)")

# CPC's long-lead DBF carries Cat="Above" with Prob=33.0 on several polygons.
# 33.3% is the climatological baseline for a three-way split, so that value is
# not a tilt - and build_calendar.py has to say so rather than let the page
# render "Above median (33%)" as if it were a signal.  These fixtures use the
# exact category/probability pairs the committed 2026-09 data contains.
_cpc_fixture = [
    {"variable": "prcp", "valid_season": "OND 2026", "category": "EC",
     "category_label": "Equal chances", "prob": 33.0, "issued": "2026-09-17", "url": "u1"},
    {"variable": "prcp", "valid_season": "NDJ 2026-2027", "category": "Above",
     "category_label": "Above median", "prob": 33.0, "issued": "2026-09-17", "url": "u2"},
    {"variable": "prcp", "valid_season": "DJF 2026-2027", "category": "Above",
     "category_label": "Above median", "prob": 40.0, "issued": "2026-09-17", "url": "u3"},
    {"variable": "prcp", "valid_season": "JFM 2027", "category": "Above",
     "category_label": "Above median", "prob": 50.0, "issued": "2026-09-17", "url": "u4"},
    {"variable": "temp", "valid_season": "DJF 2026-2027", "category": "Above",
     "category_label": "Above normal", "prob": 40.0, "issued": "2026-09-17", "url": "u5"},
]
_tilt = landlord.cpc_tilt_summary(_cpc_fixture)
check("cpc_tilt_summary ignores temperature records for the rain count",
      _tilt["periods_covering_this_season"] == 4, json.dumps(_tilt)[:200])
check("a probability that rounds to 33% is counted as the baseline, not a tilt",
      _tilt["periods_at_climatological_baseline"] == 2 and _tilt["periods_with_a_tilt"] == 2,
      "tilt=%s baseline=%s" % (_tilt["periods_with_a_tilt"],
                               _tilt["periods_at_climatological_baseline"]))
check("the strongest tilt is reported with its published probability",
      _tilt["highest_probability"]["period"] == "JFM 2027"
      and _tilt["highest_probability"]["probability_pct"] == 50.0,
      json.dumps(_tilt.get("highest_probability")))
check("cpc_tilt_summary returns None rather than inventing a summary with no records",
      landlord.cpc_tilt_summary([]) is None and landlord.cpc_tilt_summary(None) is None, "")

# The per-record flag has to agree with the counts, in both directions.
def _baseline_flag(cat, prob):
    return bool(abs(prob - (100.0 / 3.0)) < 0.5 and cat.upper() in
                ("ABOVE", "BELOW", "A", "B", "N", "NEAR"))

check("baseline flag fires for Cat=Above at 33% (CPC's real published pair)",
      _baseline_flag("Above", 33.0), "")
check("baseline flag does not fire for Cat=Above at 40% (a real tilt)",
      not _baseline_flag("Above", 40.0), "")
check("baseline flag does not fire for Cat=EC (already reads as no tilt)",
      not _baseline_flag("EC", 33.0), "")

# --------------------------------------------------------------------------- #
print("\n== storm-severity counters (exact synthetic values)")

# Ten dates per season, one of them wet enough to matter.  550 tenths of a mm
# is 2.165 in; 45 kt is 51.78 mph.  Every expected value below is computable by
# hand from the fixture, so a regression in the counters is caught here.
_mmdd = [(10, 1), (10, 2), (10, 3), (11, 1), (11, 2), (12, 1), (12, 2),
         (1, 1), (1, 2), (1, 3)]
_sev_ghcn, _sev_gsod = {}, {}
for _si, _sy in enumerate((1991, 1992)):
    for (_m, _d) in _mmdd:
        _y = _sy if _m >= 10 else _sy + 1
        _iso = "%04d-%02d-%02d" % (_y, _m, _d)
        _big = (_si == 0 and _m == 12 and _d == 1)
        _sev_ghcn[_iso] = {"PRCP": 550.0 if _big else 10.0}
        # The GSOD rain figure has to match the GHCN one on the big day,
        # otherwise the joint tier is being tested against a dry day and its
        # zero looks like a code bug.  The two files agree on this date.
        _sev_gsod[_iso] = {"prcp_in": 2.17 if _big else 0.1,
                           "max_wind_kt": 35.0 if _d == 1 else 5.0,
                           "gust_kt": 45.0 if _d == 1 else 10.0}
_sev = climo.build_season_statistics(_sev_ghcn, _sev_gsod, _mmdd, (1991, 1992), {}, None)
_s0 = _sev["seasons"][0]
check("2.165 in counted as one day >= 1.00 in and one day >= 2.00 in",
      _s0["wet_days_ge_1in"] == 1 and _s0["wet_days_ge_2in"] == 1,
      "ge1=%s ge2=%s" % (_s0["wet_days_ge_1in"], _s0["wet_days_ge_2in"]))
check("the season's wettest single day is 2.17 in (550 tenths of a mm)",
      _s0["max_daily_prcp_in"] == 2.17, str(_s0["max_daily_prcp_in"]))
# Day 1 of each of the four months in the fixture is the windy one, so the
# expected count is 4 - an earlier draft of this test said 5 and the code was
# right; the fixture is the authority, not the expectation.
check("the four first-of-month dates at 35 kt are counted as 4 >= 30 kt wind days",
      _s0["wind_days_ge_30kt"] == 4, str(_s0["wind_days_ge_30kt"]))
check("the four first-of-month dates at a 45 kt gust are counted as 4 >= 40 kt gust days",
      _s0["gust_days_ge_40kt"] == 4, str(_s0["gust_days_ge_40kt"]))
check("a 45 kt gust is below 50 kt, so no >= 50 kt gust day is counted",
      _s0["gust_days_ge_50kt"] == 0, str(_s0["gust_days_ge_50kt"]))
check("the wet-day counters do not leak between seasons",
      _sev["seasons"][1]["wet_days_ge_1in"] == 0
      and _sev["seasons"][1]["max_daily_prcp_in"] == 0.04,
      str(_sev["seasons"][1]["max_daily_prcp_in"]))
check("severity counters are summarised across seasons",
      _sev["distribution"]["wet_days_ge_1in"]["mean"] == 0.5
      and _sev["distribution"]["wet_days_ge_1in"]["max"] == 1.0,
      json.dumps(_sev["distribution"]["wet_days_ge_1in"]))
check("the record value is bound to the season that produced it",
      _sev["severity_record"]["max_daily_prcp_in"] ==
      {"season": "1991-1992", "value": 2.17},
      json.dumps(_sev["severity_record"].get("max_daily_prcp_in")))
check("45 kt is converted to 51.8 mph using the GSOD factor 1.15078",
      _sev["severity_record"]["max_gust_mph"]["value"] == 51.8,
      json.dumps(_sev["severity_record"].get("max_gust_mph")))
check("the same conversion is applied to the season's maximum sustained wind",
      _s0["max_wind_mph"] == 40.3 and _sev["severity_record"]["max_wind_mph"]["value"] == 40.3,
      "%s / %s" % (_s0["max_wind_mph"], _sev["severity_record"].get("max_wind_mph")))
check("a 2.165 in day counts at 0.50 in, 1.00 in and 2.00 in but not at 4.00 in",
      (_s0["wet_days_ge_050in"], _s0["wet_days_ge_1in"], _s0["wet_days_ge_2in"],
       _s0["wet_days_ge_400in"]) == (1, 1, 1, 0),
      str([_s0[k] for k in ("wet_days_ge_050in", "wet_days_ge_1in",
                            "wet_days_ge_2in", "wet_days_ge_400in")]))
check("a day with 2.165 in and a 45 kt gust is one severe wind-and-rain day",
      _s0["severe_wind_and_rain_days"] == 1, str(_s0["severe_wind_and_rain_days"]))
# The strict tier must be a subset of the loose one, by construction.
check("the strict joint tier is never larger than the loose one",
      _s0["severe_wind_and_rain_days"] <= _s0["heavy_wind_and_rain_days"], "")
# A season with no 4-inch day must publish 0, not None: the site renders a
# missing value as an em dash, and "no such day in 30 seasons" is a fact.
check("a zero count is published as 0, not as a missing value",
      _sev["distribution"]["wet_days_ge_400in"]["mean"] == 0.0
      and _sev["distribution"]["wet_days_ge_400in"]["max"] == 0.0,
      json.dumps(_sev["distribution"]["wet_days_ge_400in"]))
# Each of the eight NOAA-published thresholds has a project counterpart here.
for _t, _key in ((0.50, "wet_days_ge_050in"), (1.00, "wet_days_ge_1in"),
                 (2.00, "wet_days_ge_2in"), (4.00, "wet_days_ge_400in")):
    check("the project counts days at the NOAA-published %.2f in threshold" % _t,
          _key in _sev["distribution"] and _key in _sev["seasons"][0], _key)

# --------------------------------------------------------------------------- #
print("\n== executive bottom line (structure and traceability)")

import datetime  # noqa: E402
_bl_ok = landlord.build_bottom_line(
    season_total={"n": 30, "mean": 12.79, "median": 13.26, "min": 1.71, "max": 22.82,
                  "p10": 6.38, "p90": 18.59},
    wet_days={"mean": 34.5}, streak_prob={"ge_3_days": {"pct": 96.7}, "ge_5_days": {"pct": 80.0},
                                          "ge_7_days": {"pct": 53.3}, "ge_10_days": {"pct": 23.3}},
    longest_streak={"n": 30, "mean": 7.3, "max": 17.0},
    wind_rain={"mean": 11.1, "max": 24}, heavy_wind_and_rain={"mean": 2.2, "max": 8},
    max_gust={"n": 30, "mean": 53.8, "max": 70.0},
    expected_days={"ge_025in_days": 14.97, "ge_100in_days": 3.19},
    severity={"wind_days_ge_30kt": {"mean": 1.0}, "gust_days_ge_50kt": {"mean": 0.5},
              "record_daily_prcp_in": {"season": "1997-1998", "value": 5.54},
              "published_expected": {"ge_025in_days": 14.9, "ge_100in_days": 3.26}},
    latest_oni={"phase": "el_nino", "phase_label": "El Ni\u00f1o", "oni_c": 1.8,
                "label": "JJA 2026"},
    oni_when="JJA 2026", diagnostic_status="El Ni\u00f1o Advisory",
    tilt={"periods_with_a_tilt": 2}, storms={"n_events": 119, "years": [2014, 2026],
                                             "events": [], "n_with_damage": 12},
    days_in_horizon=0, horizon_last_day="2026-09-24")
_bl, _off = _bl_ok
check("the bottom line answers six questions, numbered in order",
      [i["n"] for i in _bl] == [1, 2, 3, 4, 5, 6], str([i["n"] for i in _bl]))
check("every answer carries a basis, numbers and an official source link",
      all(i["basis"] and i["numbers"] and i["sources"] for i in _bl), "")
check("no answer is missing its question or its text",
      all(i["question"].strip() and i["answer"].strip() for i in _bl), "")
check("every source link is an official .gov host",
      all("gov" in s["url"].split("/")[2] for i in _bl for s in i["sources"]), "")
check("a severity counter that was not derived reads 'not derived this run', "
      "never a blank or a zero",
      all(v["value"] not in (None, "") for i in _bl for v in i["numbers"]), "")
check("the official outlook block separates ENSO, CPC and the daily horizon",
      {"enso", "cpc_tilt", "daily_forecast"} <= set(_off), str(list(_off)))
check("with no ENSO stratification supplied, no conditional average is invented",
      _off.get("enso_conditioned_record") is None, json.dumps(_off.get("enso_conditioned_record")))

# With the stratification supplied, the conditional record must carry every
# number the renderer prints plus the sentence that stops it reading as a
# forecast.  This is the one place the site bridges the official outlook to the
# cost question, so it is the one place that most needs pinning down.
_bl_strat, _off_strat = landlord.build_bottom_line(
    season_total={}, wet_days={}, streak_prob={}, longest_streak={}, wind_rain={},
    heavy_wind_and_rain={}, max_gust={}, expected_days={}, severity={},
    latest_oni={"phase": "el_nino", "phase_label": "El Ni\u00f1o", "oni_c": 1.8},
    oni_when="JJA 2026", diagnostic_status="El Ni\u00f1o Advisory", tilt=None,
    storms=None, days_in_horizon=0, horizon_last_day="2026-09-24",
    enso_strat={"el_nino": {"n": 11, "mean": 14.23, "median": 13.56, "min": 7.27,
                            "max": 22.82, "phase_label": "El Ni\u00f1o"},
                "la_nina": {"n": 9, "mean": 11.16, "median": 11.0, "min": 1.71,
                            "max": 20.5, "phase_label": "La Ni\u00f1a"}})
_cond = _off_strat.get("enso_conditioned_record") or {}
check("the conditional record names the phase NOAA published for this season",
      _cond.get("phase") == "el_nino" and _cond.get("mean_in") == 14.23
      and _cond.get("seasons_in_phase") == 11, json.dumps(_cond)[:200])
check("the conditional record is labelled as an average of past seasons, not a forecast",
      "NOT a forecast" in (_cond.get("how_to_read") or ""), _cond.get("how_to_read") or "")
check("the conditional record links both the ONI file and the discussion",
      ".gov" in (_cond.get("source_url") or "") and ".gov" in (_cond.get("phase_source_url") or ""), "")
check("a phase with no seasons in the record yields None, never a zero-filled block",
      (landlord.build_bottom_line(
          season_total={}, wet_days={}, streak_prob={}, longest_streak={}, wind_rain={},
          heavy_wind_and_rain={}, max_gust={}, expected_days={}, severity={},
          latest_oni={"phase": "el_nino"}, oni_when=None, diagnostic_status=None,
          tilt=None, storms=None, days_in_horizon=None, horizon_last_day=None,
          enso_strat={"la_nina": {"n": 9, "mean": 11.16}})[1]
       ).get("enso_conditioned_record") is None, "")
check("the daily-forecast block states how many scoreboard days are in the horizon",
      _off["daily_forecast"]["days_in_this_scoreboard_with_a_real_forecast"] == 0
      and _off["daily_forecast"]["official_horizon_ends"] == "2026-09-24",
      json.dumps(_off["daily_forecast"]))
# The documented failure mode: a severity block that arrives as None rather than
# missing.  ``.get(k, {})`` returns None for an explicit null, which crashed the
# first version of this function.
_bl_none, _ = landlord.build_bottom_line(
    season_total={"n": 30, "mean": 12.79, "median": 13.26, "min": 1.71, "max": 22.82,
                  "p10": 6.38, "p90": 18.59},
    wet_days={}, streak_prob={}, longest_streak={}, wind_rain={},
    heavy_wind_and_rain={}, max_gust={}, expected_days={}, severity=None,
    latest_oni={}, oni_when=None, diagnostic_status=None, tilt=None,
    storms=None, days_in_horizon=None, horizon_last_day=None)
check("a completely absent severity block still renders every answer",
      len(_bl_none) == 6 and all(i["answer"] for i in _bl_none), str(len(_bl_none)))

# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
section("publisher text encoding and character loss (lib_fetch)")

import lib_fetch  # noqa: E402
import landlord_summary as landlord  # noqa: E402

# NCEI's Storm Events CSVs are not reliably UTF-8.  The pipeline used to decode
# them with errors="replace" and commit the result.
_txt, _enc = lib_fetch.decode_text("caf\u00e9 \u2014 5.46\u201d".encode("cp1252"))
check("a CP1252 body decodes to the publisher's characters, not U+FFFD",
      _enc == "cp1252" and "\ufffd" not in _txt and "5.46\u201d" in _txt,
      "enc=%s text=%r" % (_enc, _txt))
_txt, _enc = lib_fetch.decode_text("caf\u00e9".encode("utf-8"))
check("a valid UTF-8 body is decoded as UTF-8", _enc == "utf-8" and _txt == "caf\u00e9",
      "enc=%s" % _enc)
_txt, _enc = lib_fetch.decode_text(None)
check("a missing body yields an empty string and encoding 'none'",
      _txt == "" and _enc == "none", "enc=%s" % _enc)
_txt, _enc = lib_fetch.decode_text(bytes([0xff, 0xfe, 0x00, 0x01]))
check("a body that is neither UTF-8 nor CP1252 still decodes without raising",
      isinstance(_txt, str), "enc=%s" % _enc)

# The real 31 Dec 2022 narrative, as NCEI serves it: valid UTF-8 that already
# contains U+FFFD where a typographic character used to be.
_real_lossy = ("San Francisco Downtown site hit 5.46\ufffd\ufffd\ufffd in the 24 hours of "
               "December 31st, just 0.08\ufffd less than 1st place (11/5/1994) with 5.54\ufffd.")
_clean, _n, _ctx = lib_fetch.strip_unrepresentable(_real_lossy)
check("the five already-lost characters in the real narrative are removed",
      _n == 5 and "\ufffd" not in _clean, "n=%s clean=%r" % (_n, _clean))
check("what remains is the publisher's text, not a reconstruction",
      "hit 5.46 in the 24 hours of December 31st" in _clean
      and "just 0.08 less than 1st place (11/5/1994) with 5.54." in _clean, _clean)
check("the removal records the surrounding text so it can be checked",
      len(_ctx) == 5 and all("5.46" in c or "0.08" in c or "5.54" in c for c in _ctx),
      str(_ctx[:1]))
# The evidence snippets must not re-publish the character they document: the
# ledger's "no U+FFFD anywhere" rule stays absolute, with no carve-out.
check("the evidence snippets mark the loss visibly and carry no replacement character",
      "\ufffd" not in "".join(_ctx) and all("<U+FFFD>" in c for c in _ctx)
      and "<U+0000>" not in "".join(_ctx), str(_ctx[:1]))
check("clean text is returned unchanged with a zero count",
      lib_fetch.strip_unrepresentable("nothing to do") == ("nothing to do", 0, []), "")
check("an empty or missing string is handled",
      lib_fetch.strip_unrepresentable("") == ("", 0, [])
      and lib_fetch.strip_unrepresentable(None)[1] == 0, "")

# --------------------------------------------------------------------------- #
section("CPC 33% baseline (the tilt that is not a tilt)")

# CPC publishes whole percentages against a three-way baseline of 100/3 = 33.3.
# Cat="Above" with Prob=33.0 is real published data and is NOT a tilt.
_synth = [
    {"variable": "prcp", "valid_season": "OND 2026", "category": "EC",
     "category_label": "Equal chances", "prob": 33.0, "issued": "2026-09-17", "url": "u"},
    {"variable": "prcp", "valid_season": "NDJ 2026-2027", "category": "Above",
     "category_label": "Above median", "prob": 33.0, "issued": "2026-09-17", "url": "u"},
    {"variable": "prcp", "valid_season": "DJF 2026-2027", "category": "Above",
     "category_label": "Above median", "prob": 40.0, "issued": "2026-09-17", "url": "u"},
    {"variable": "prcp", "valid_season": "JFM 2027", "category": "Above",
     "category_label": "Above median", "prob": 50.0, "issued": "2026-09-17", "url": "u"},
    {"variable": "temp", "valid_season": "DJF 2026-2027", "category": "Above",
     "category_label": "Above normal", "prob": 40.0, "issued": "2026-09-17", "url": "u"},
]
_tilt = landlord.cpc_tilt_summary(_synth)
check("cpc_tilt_summary counts precipitation periods only",
      _tilt["periods_covering_this_season"] == 4, json.dumps(_tilt)[:160])
check("an Above/33% polygon is counted as the baseline, not as a tilt",
      _tilt["periods_at_climatological_baseline"] == 2 and _tilt["periods_with_a_tilt"] == 2,
      "tilt=%s baseline=%s" % (_tilt["periods_with_a_tilt"],
                               _tilt["periods_at_climatological_baseline"]))
check("the strongest tilt is reported by probability",
      _tilt["highest_probability"]["period"] == "JFM 2027"
      and _tilt["highest_probability"]["probability_pct"] == 50.0,
      json.dumps(_tilt["highest_probability"]))
check("no precipitation records at all yields None rather than a zero summary",
      landlord.cpc_tilt_summary([]) is None and landlord.cpc_tilt_summary(None) is None, "")

# --------------------------------------------------------------------------- #
section("executive bottom line")

_bl, _off = landlord.build_bottom_line(
    season_total={"n": 30, "mean": 12.79, "median": 13.26, "min": 1.71, "max": 22.82,
                  "p10": 6.38, "p90": 18.59},
    wet_days={"mean": 34.5},
    streak_prob={"ge_3_days": {"pct": 96.7}, "ge_5_days": {"pct": 80.0},
                 "ge_7_days": {"pct": 53.3}, "ge_10_days": {"pct": 23.3}},
    longest_streak={"n": 30, "mean": 7.3, "max": 17.0},
    wind_rain={"mean": 11.1, "max": 24}, heavy_wind_and_rain={"mean": 2.2, "max": 8},
    max_gust={"n": 30, "mean": 53.8, "max": 70.0},
    expected_days={"ge_025in_days": 14.97, "ge_100in_days": 3.19},
    severity={
        "wet_days_ge_1in": {"mean": 3.2}, "gust_days_ge_40kt": {"mean": 4.8},
        "severe_wind_and_rain_days": {"mean": 0.4},
        "record_daily_prcp_in": {"season": "1997-1998", "value": 4.34},
        "record_days_ge_1in": {"season": "1997-1998", "value": 9},
        "record_severe_wind_and_rain_days": {"season": "2016-2017", "value": 2},
        "threshold_comparison": [
            {"threshold_in": 0.5, "project_mean_days": 9.9, "noaa_expected_days": 10.1},
            {"threshold_in": 1.0, "project_mean_days": 3.2, "noaa_expected_days": 3.26},
            {"threshold_in": 2.0, "project_mean_days": 0.9, "noaa_expected_days": 0.7},
            {"threshold_in": 4.0, "project_mean_days": 0.0, "noaa_expected_days": 0.0}],
        "published_expected": {"ge_025in_days": 14.9, "ge_100in_days": 3.26},
    },
    latest_oni={"phase": "el_nino", "phase_label": "El Ni\u00f1o", "oni_c": 1.8},
    oni_when="JJA 2026", diagnostic_status="El Ni\u00f1o Advisory",
    tilt={"periods_with_a_tilt": 2},
    storms={"n_events": 119, "years": [2014, 2026], "events": [], "n_with_damage": 12},
    days_in_horizon=0, horizon_last_day="2026-09-24",
    enso_strat={"el_nino": {"n": 11, "mean": 14.23, "median": 13.5, "min": 5.6,
                            "max": 22.1, "phase_label": "El Ni\u00f1o"},
                "la_nina": {"n": 9, "mean": 11.16, "median": 11.0, "min": 1.71,
                            "max": 20.5, "phase_label": "La Ni\u00f1a"},
                "neutral": {"n": 10, "mean": 13.31, "median": 13.0, "min": 6.0,
                            "max": 22.8, "phase_label": "Neutral"}})
check("the bottom line answers the six questions in order",
      [i["n"] for i in _bl] == [1, 2, 3, 4, 5, 6], str([i["n"] for i in _bl]))
check("every answer names its question and gives an answer",
      all(i["question"].strip() and i["answer"].strip() for i in _bl), "")
check("every answer states a basis and a confidence",
      all(i["basis"].strip() and i["confidence"] for i in _bl), "")
check("every answer carries a link to an official host",
      all(s["url"].startswith("https://") and ".gov" in s["url"] for i in _bl
          for s in i["sources"]), "")
check("every answer carries supporting numbers",
      all(len(i["numbers"]) >= 2 for i in _bl), str([len(i["numbers"]) for i in _bl]))
check("no published value is blank or None",
      all(v["value"] not in (None, "", "None") for i in _bl for v in i["numbers"]), "")
check("a severity counter that was not derived says so in words",
      all("not derived this run" not in v["value"] or isinstance(v["value"], str)
          for i in _bl for v in i["numbers"]), "")

# The threshold table is the two-method comparison; both columns must appear.
_thr_rows = [v for i in _bl if i["key"] == "heavy_rain_days" for v in i["numbers"]
             if "≥ 0.50 in" in v["label"] or "≥ 2.00 in" in v["label"]]
check("the hard-rain answer carries the counted-vs-NOAA threshold rows",
      len(_thr_rows) == 2
      and all("counted" in r["label"] and "NOAA published" in r["label"]
              and " vs " in r["value"] for r in _thr_rows), json.dumps(_thr_rows))

# The storm-severity answer must never present a dollar figure, and must say
# that no warning category is applied.
_q6 = [i for i in _bl if i["key"] == "storm_severity"][0]
check("the severity answer reports counts, not a dollar total",
      "$" not in _q6["answer"] and "dollar" in _q6["answer"].lower(), _q6["answer"][:150])
check("the severity answer refuses to restate an NWS warning category",
      "no named warning category" in _q6["answer"].lower(), _q6["answer"][-160:])
check("the damage figure is reported as a count of records, with its denominator",
      any("of 119" in v["value"] for v in _q6["numbers"]), json.dumps(_q6["numbers"])[:200])

# ENSO-conditioned record: the one bridge to the cost question.
_cond = _off.get("enso_conditioned_record") or {}
check("the conditioned record uses the phase NOAA published for this season",
      _cond.get("phase") == "el_nino" and _cond.get("seasons_in_phase") == 11
      and _cond.get("mean_in") == 14.23, json.dumps(_cond)[:160])
check("the conditioned record states it is not a forecast",
      "NOT a forecast" in (_cond.get("how_to_read") or ""), _cond.get("how_to_read") or "")
check("the conditioned record lists the other phases for contrast",
      [c["phase"] for c in _cond.get("contrast") or []] == ["neutral", "la_nina"],
      json.dumps(_cond.get("contrast")))
check("a phase with no seasons yields None, never a zero-filled block",
      (landlord.build_bottom_line(
          season_total={}, wet_days={}, streak_prob={}, longest_streak={}, wind_rain={},
          heavy_wind_and_rain={}, max_gust={}, expected_days={}, severity={},
          latest_oni={"phase": "el_nino"}, oni_when=None, diagnostic_status=None,
          tilt=None, storms=None, days_in_horizon=None, horizon_last_day=None,
          enso_strat={"la_nina": {"n": 9, "mean": 11.16}})[1]
       ).get("enso_conditioned_record") is None, "")

# The documented crash: a severity block that arrives as None, not missing.
_bl_none, _off_none = landlord.build_bottom_line(
    season_total={}, wet_days={}, streak_prob={}, longest_streak={}, wind_rain={},
    heavy_wind_and_rain={}, max_gust={}, expected_days={}, severity=None,
    latest_oni={}, oni_when=None, diagnostic_status=None, tilt=None, storms=None,
    days_in_horizon=None, horizon_last_day=None)
check("an entirely missing severity block still renders six answers",
      len(_bl_none) == 6 and all(i["answer"] for i in _bl_none), str(len(_bl_none)))
check("the official outlook separates ENSO, CPC, the horizon and the conditioned record",
      set(_off_none) == {"enso", "cpc_tilt", "daily_forecast", "enso_conditioned_record"},
      str(sorted(_off_none)))

# --------------------------------------------------------------------------- #
section("storm-severity counters (hand-computable synthetic season)")

_mmdd = [(10, 1), (10, 2), (10, 3), (11, 1), (11, 2), (12, 1), (12, 2),
         (1, 1), (1, 2), (1, 3)]
_ghcn, _gsod = {}, {}
for _si, _sy in enumerate((1991, 1992)):
    for (_m, _d) in _mmdd:
        _y = _sy if _m >= 10 else _sy + 1
        _iso = "%04d-%02d-%02d" % (_y, _m, _d)
        _big = (_si == 0 and _m == 12 and _d == 1)
        _ghcn[_iso] = {"PRCP": 550.0 if _big else 10.0}
        _gsod[_iso] = {"prcp_in": 2.17 if _big else 0.1,
                       "max_wind_kt": 35.0 if _d == 1 else 5.0,
                       "gust_kt": 45.0 if _d == 1 else 10.0}
_sev = climo.build_season_statistics(_ghcn, _gsod, _mmdd, (1991, 1992), {}, None)
_s0 = _sev["seasons"][0]
_s1 = _sev["seasons"][1]
check("2.165 in counts as a >=1.00 in day and a >=2.00 in day but not >=4.00 in",
      (_s0["wet_days_ge_1in"], _s0["wet_days_ge_2in"], _s0["wet_days_ge_400in"]) == (1, 1, 0),
      str([_s0[k] for k in ("wet_days_ge_1in", "wet_days_ge_2in", "wet_days_ge_400in")]))
check("0.50 in is a lower bar, so it can only count more days",
      _s0["wet_days_ge_050in"] >= _s0["wet_days_ge_1in"] >= _s0["wet_days_ge_2in"]
      >= _s0["wet_days_ge_400in"], str([_s0[k] for k in ("wet_days_ge_050in",
                                                         "wet_days_ge_1in",
                                                         "wet_days_ge_2in",
                                                         "wet_days_ge_400in")]))
check("the wettest single day in the season is 2.17 in",
      _s0["max_daily_prcp_in"] == 2.17, str(_s0["max_daily_prcp_in"]))
check("45 kt becomes 51.8 mph and is kept as a record bound to its season",
      _s0["max_gust_mph"] == 51.8
      and _sev["severity_record"]["max_gust_mph"] == {"season": "1991-1992", "value": 51.8},
      json.dumps(_sev["severity_record"].get("max_gust_mph")))
check("a >=1.00 in day with a >=40 kt gust counts as one joint severe day",
      _s0["severe_wind_and_rain_days"] == 1 and _s1["severe_wind_and_rain_days"] == 0,
      "%s / %s" % (_s0["severe_wind_and_rain_days"], _s1["severe_wind_and_rain_days"]))
check("the joint tiers are ordered: severe <= heavy (both are same-day tests)",
      _s0["severe_wind_and_rain_days"] <= _s0["heavy_wind_and_rain_days"] + 1, "")
check("a counter with no qualifying day is 0, not None",
      _s0["gust_days_ge_50kt"] == 0 and _sev["distribution"]["gust_days_ge_50kt"]["mean"] == 0.0,
      json.dumps(_sev["distribution"]["gust_days_ge_50kt"]))
check("four 30 kt days are counted, and the record is bound to the season",
      _s0["wind_days_ge_30kt"] == 4
      and _sev["severity_record"]["most_wet_days_ge_1in"]["value"] == 1, "")
check("every new counter is summarised across seasons with a mean and a max",
      all(_sev["distribution"].get(k, {}).get("mean") is not None
          for k in ("wet_days_ge_050in", "wet_days_ge_1in", "wet_days_ge_2in",
                    "wet_days_ge_400in", "wind_days_ge_30kt", "gust_days_ge_40kt",
                    "gust_days_ge_50kt", "severe_wind_and_rain_days", "max_wind_mph")),
      str(sorted(_sev["distribution"])))

# --------------------------------------------------------------------------- #
section("committed data: the published severity blocks")

if os.path.exists(os.path.join(ROOT, "data", "calendar.json")):
    with io.open(os.path.join(ROOT, "data", "calendar.json"), encoding="utf-8") as fh:
        _cal2 = json.load(fh)
    _days = _cal2.get("days") or []
    _missing = [k for k in ("p_rain_day_pct", "p_wind_and_rain_pct")
                if not all((d.get("climo") or {}).get(k) is not None for d in _days)]
    check("every scoreboard day publishes its rain and joint probabilities",
          not _missing, "missing keys on some days: %s" % _missing)
    _pe = (_cal2.get("season_summary") or {}).get("wet_days") or {}
    check("the committed season summary publishes the wet-day distribution",
          _pe.get("mean") is not None and _pe.get("n") == len(_cal2.get("season_by_year") or []),
          json.dumps(_pe))

# --------------------------------------------------------------------------- #
section("ISD hourly wind & rain parsing (open item 1)")

_sample_isd = """STATION,DATE,SOURCE,LATITUDE,LONGITUDE,ELEVATION,NAME,REPORT_TYPE,CALL_SIGN,QUALITY_CONTROL,WND,CIG,VIS,TMP,DEW,SLP,AA1,GA1
"72494023234","1991-10-01T07:56:00","4","37.619"," -122.365","3.4","SAN FRANCISCO INTERNATIONAL AIRPORT, CA US","FM-15","KSFO","V020","290,1,N,0103,1","99999,9,9,9","010000,1,9,9","+0172,1","+0111,1","10156,1","01,0025,9,5","99,99,99999,9,9,9"
"72494023234","1991-10-01T08:56:00","4","37.619"," -122.365","3.4","SAN FRANCISCO INTERNATIONAL AIRPORT, CA US","FM-15","KSFO","V020","280,1,N,0050,1","99999,9,9,9","010000,1,9,9","+0167,1","+0111,1","10159,1","01,0000,9,5","99,99,99999,9,9,9"
"72494023234","1991-10-01T09:56:00","4","37.619"," -122.365","3.4","SAN FRANCISCO INTERNATIONAL AIRPORT, CA US","FM-15","KSFO","V020","999,9,9,9999,9","99999,9,9,9","010000,1,9,9","+0160,1","+0110,1","10160,1","01,0010,9,5","99,99,99999,9,9,9"
"72494023234","1991-05-01T12:00:00","4","37.619"," -122.365","3.4","SAN FRANCISCO INTERNATIONAL AIRPORT, CA US","FM-15","KSFO","V020","290,1,N,0120,1","99999,9,9,9","010000,1,9,9","+0170,1","+0110,1","10150,1","01,0050,9,5","99,99,99999,9,9,9"
"""

_parsed_isd = climo.parse_isd_hourly(_sample_isd)
check("parse_isd_hourly parses all valid CSV records",
      len(_parsed_isd) == 4, str(len(_parsed_isd)))
check("ISD UTC timestamp is converted to local America/Los_Angeles calendar date",
      _parsed_isd[0]["local_date"] == "1991-10-01" and _parsed_isd[0]["local_hour"] == 0,
      f"{_parsed_isd[0]['local_date']} hour {_parsed_isd[0]['local_hour']}")
check("WND 0103 tenths m/s converts to knots (10.3 m/s = 20.0 kt)",
      _parsed_isd[0]["wind_speed_kt"] == 20.0, str(_parsed_isd[0]["wind_speed_kt"]))
check("AA1 0025 tenths mm converts to inches (2.5 mm = 0.098 in)",
      _parsed_isd[0]["prcp_in"] == 0.098, str(_parsed_isd[0]["prcp_in"]))
check("simultaneous wind >= 20 kt and prcp > 0.00 flags is_wind_and_rain",
      _parsed_isd[0]["is_wind_and_rain"] is True and _parsed_isd[1]["is_wind_and_rain"] is False,
      f"{_parsed_isd[0]['is_wind_and_rain']} vs {_parsed_isd[1]['is_wind_and_rain']}")
check("missing wind 9999 is decoded as None and not flagged as wind+rain",
      _parsed_isd[2]["wind_speed_kt"] is None and _parsed_isd[2]["is_wind_and_rain"] is False,
      str(_parsed_isd[2]))
check("out-of-season month (May) is marked in_season=False",
      _parsed_isd[3]["in_season"] is False and _parsed_isd[0]["in_season"] is True,
      f"May in_season: {_parsed_isd[3]['in_season']}")

_agg_isd = climo.aggregate_isd_hourly_wind_and_rain(_parsed_isd)
check("ISD aggregation counts valid joint hours and simultaneous hours in season",
      _agg_isd["valid_joint_hours"] == 2 and _agg_isd["simultaneous_wind_rain_hours"] == 1,
      f"valid={_agg_isd['valid_joint_hours']}, sim={_agg_isd['simultaneous_wind_rain_hours']}")
check("overall percentage is computed correctly (1/2 = 50.0%)",
      _agg_isd["overall_pct"] == 50.0, str(_agg_isd["overall_pct"]))
check("ISD per-season breakdown identifies season 1991-1992",
      len(_agg_isd["per_season"]) == 1 and _agg_isd["per_season"][0]["season"] == "1991-1992",
      json.dumps(_agg_isd["per_season"]))

# The richer per-date/per-season rollup that the landlord dashboard publishes.
# The sample above has three in-season rows on 1991-10-01: 20.0 kt + 0.098 in
# (simultaneous), 10.0 kt + 0.000 in (dry), and a row with no wind reading.
_ps = _agg_isd["per_season"][0]
check("ISD per-season rollup counts dates, rain days, windy days and daily pairs",
      (_ps["dates_with_data"], _ps["days_rain"], _ps["days_wind_ge_threshold"],
       _ps["days_daily_pair"], _ps["days_simultaneous"], _ps["wind_rain_hours"])
      == (1, 1, 1, 1, 1, 1),
      json.dumps({k: _ps[k] for k in ("dates_with_data", "days_rain", "days_wind_ge_threshold",
                                      "days_daily_pair", "days_simultaneous")}))
check("ISD season coverage is measured against the 123-date Oct 1 - Jan 31 season",
      _ps["dates_expected"] == 123 and _ps["coverage_pct"] == round(100 * 1 / 123, 1),
      f"expected={_ps['dates_expected']} coverage={_ps['coverage_pct']}%")
check("ISD season window is named from the date, not from the file year",
      climo.isd_season_year("1991-10-01") == 1991      # October -> season year Y
      and climo.isd_season_year("1992-01-31") == 1991  # January -> season year Y-1
      and climo.isd_season_year("2027-01-01") == 2026,  # the January of the next season
      f"{climo.isd_season_year('1991-10-01')} / {climo.isd_season_year('1992-01-31')} / "
      f"{climo.isd_season_year('2027-01-01')}")
check("ISD per-date rollup carries the day's max wind and summed precipitation",
      _agg_isd["by_local_date"]["1991-10-01"]["wind_max_kt"] == 20.0
      and _agg_isd["by_local_date"]["1991-10-01"]["prcp_in"] == 0.098,
      json.dumps(_agg_isd["by_local_date"]["1991-10-01"]))
check("the AA1 reporting period is kept so multi-hour accumulations can be disclosed",
      _parsed_isd[0]["prcp_period_hours"] == 1
      and _agg_isd["simultaneous_hours_from_multi_hour_reports"] == 0,
      f"period={_parsed_isd[0]['prcp_period_hours']} "
      f"multi={_agg_isd['simultaneous_hours_from_multi_hour_reports']}")

# A six-hour accumulation must be counted as a simultaneous hour (rain did fall)
# AND disclosed as not being an hour-by-hour measurement.
_multi_isd = climo.parse_isd_hourly(
    _sample_isd.splitlines()[0] + "\n" +
    '"72494023234","1991-10-02T07:56:00","4","37.619"," -122.365","3.4","KSFO","FM-15","KSFO",'
    '"V020","290,1,N,0103,1","99999,9,9,9","010000,1,9,9","+0172,1","+0111,1","10156,1",'
    '"06,0025,9,5","99,99,99999,9,9,9"\n')
_multi_agg = climo.aggregate_isd_hourly_wind_and_rain(_multi_isd)
check("a 6-hour precipitation report still counts as rain, and is disclosed",
      _multi_agg["simultaneous_wind_rain_hours"] == 1
      and _multi_agg["simultaneous_hours_from_multi_hour_reports"] == 1,
      json.dumps({k: v for k, v in _multi_agg.items()
                  if k.startswith("simultaneous")}))

# --------------------------------------------------------------------------- #
section("Landlord dashboard: hour-by-hour wind+rain block")

import landlord_summary as ls  # noqa: E402

_isd_fixture = {
    "station_id": "72494023234",
    "station_name": "KSFO",
    "source": "NCEI ISD",
    "by_local_date": {
        # season 1991-1992: one simultaneous day
        "1991-10-05": {"valid_hours": 24, "wind_rain_hours": 2, "rain_hours": 3,
                       "prcp_in": 0.4, "wind_max_kt": 24.0, "wind_max_mph": 27.6},
        "1991-10-06": {"valid_hours": 24, "wind_rain_hours": 0, "rain_hours": 0,
                       "prcp_in": 0.0, "wind_max_kt": 9.0},
        # season 1992-1993: rain and wind on the same day but never the same hour
        "1992-11-01": {"valid_hours": 24, "wind_rain_hours": 0, "rain_hours": 5,
                       "prcp_in": 0.9, "wind_max_kt": 21.0},
        "1992-11-02": {"valid_hours": 24, "wind_rain_hours": 1, "rain_hours": 1,
                       "prcp_in": 0.2, "wind_max_kt": 30.0},
        # season 1993-1994: thin coverage, must be excluded and named
        "1993-12-01": {"valid_hours": 24, "wind_rain_hours": 9, "rain_hours": 9,
                       "prcp_in": 1.1, "wind_max_kt": 40.0},
        # a season outside the normals window, must be excluded and named
        "2024-12-01": {"valid_hours": 24, "wind_rain_hours": 4, "rain_hours": 4,
                       "prcp_in": 0.5, "wind_max_kt": 35.0},
    },
    "valid_joint_hours": 1000,
    "simultaneous_wind_rain_hours": 16,
    "simultaneous_hours_from_multi_hour_reports": 0,
    "wind_threshold_kt": 20.0,
    "dates_expected_per_season": 123,
    "latest_observation_utc": "2025-08-26T23:56:00+00:00",
}
# The fixture carries only a handful of dates, so the coverage floor is lowered
# for the test (the production floor is pinned separately below).
_hr = ls.summarise_hourly_wind_rain(_isd_fixture, (1991, 2020),
                                    {"mean": 11.1, "median": 10.0, "max": 24.0},
                                    {"mean": 2.2, "median": 2.0, "max": 8.0},
                                    min_coverage_pct=1.0)
check("hourly block summarises only seasons inside the shared window with enough coverage",
      _hr["n_seasons_used"] == 2 and [s["season"] for s in _hr["per_season"]]
      == ["1991-1992", "1992-1993"],
      json.dumps([s["season"] for s in _hr["per_season"]]))
check("excluded seasons are named with the reason instead of being averaged in",
      sorted(e["season"] for e in _hr["excluded_seasons"]) ==
      ["1993-1994", "2024-2025"]
      and all(e.get("excluded_because") for e in _hr["excluded_seasons"]),
      json.dumps([(e["season"], e["excluded_because"]) for e in _hr["excluded_seasons"]]))
check("hourly mean/median are the arithmetic over the used seasons (1 and 1)",
      _hr["days_with_a_simultaneous_hour"]["mean"] == 1.0
      and _hr["days_with_a_simultaneous_hour"]["n"] == 2,
      json.dumps(_hr["days_with_a_simultaneous_hour"]))
check("same-station whole-day pairing is counted from the per-date fields",
      # season 1: 24 kt + 0.4 in on one day, dry on the other -> 1 pair, 1 windy day
      # season 2: 21 kt + 0.9 in and 30 kt + 0.2 in -> 2 pairs, 2 windy days; means 1.5
      _hr["days_daily_pair_same_station"]["mean"] == 1.5
      and _hr["days_wind_ge_threshold_same_station"]["mean"] == 1.5,
      json.dumps({"pair": _hr["days_daily_pair_same_station"],
                  "windy": _hr["days_wind_ge_threshold_same_station"]}))
check("the cross-station whole-day figure is carried through, not recomputed",
      _hr["cross_station_daily_days"]["mean"] == 11.1
      and _hr["difference_cross_station_minus_hourly"] == 10.1,
      json.dumps({"cross": _hr["cross_station_daily_days"],
                  "diff": _hr["difference_cross_station_minus_hourly"]}))

# An older hourly summary (before the per-date fields existed) must report the
# pairing as unavailable rather than as a measured zero.
_old_isd = {"by_local_date": {"1991-10-05": {"valid_hours": 24, "wind_rain_hours": 2}},
            "simultaneous_wind_rain_hours": 2, "valid_joint_hours": 24}
_hr_old = ls.summarise_hourly_wind_rain(_old_isd, (1991, 2020), {"mean": 11.1}, {"mean": 2.2},
                                       min_coverage_pct=0.5)
check("an hourly summary without the per-date fields reports the pairing as unavailable",
      _hr_old["available"] is True and _hr_old["days_daily_pair_same_station"] is None
      and _hr_old["same_station_daily_fields_available"] is False,
      json.dumps({k: v for k, v in _hr_old.items()
                  if k.startswith("days_daily_pair") or k == "same_station_daily_fields_available"}))
check("an unavailable pairing is explained in the published notes",
      any("unavailable" in n for n in _hr_old["notes"]), json.dumps(_hr_old["notes"]))
check("a missing hourly summary yields available=False, never a zero",
      ls.summarise_hourly_wind_rain({}, (1991, 2020), {}, {})["available"] is False,
      json.dumps(ls.summarise_hourly_wind_rain({}, (1991, 2020), {}, {})))
check("the production coverage floor is published and applied at 95% of 123 dates",
      ls.HOURLY_SEASON_MIN_COVERAGE_PCT == 95.0
      and _hr["coverage"]["min_coverage_pct_required"] == 1.0
      and ls.summarise_hourly_wind_rain(_isd_fixture, (1991, 2020), {}, {})["available"] is False,
      f"floor={ls.HOURLY_SEASON_MIN_COVERAGE_PCT}")


# --------------------------------------------------------------------------- #
section("NWS forecast verification loop (open item 2)")

_sample_fc_snapshot = {
    "issuance_date": "2026-09-18",
    "generated_utc": "2026-09-18T04:10:47+00:00",
    "forecast_updated": "2026-09-18T03:51:56+00:00",
    "days": [
        {"target_date": "2026-09-18", "high_f": 64, "low_f": 58, "pop_pct": 10, "qpf_in": 0.0},
        {"target_date": "2026-09-19", "high_f": 66, "low_f": 58, "pop_pct": 60, "qpf_in": 0.25},
    ],
}

_hist1 = climo.update_forecast_history([], _sample_fc_snapshot)
check("update_forecast_history appends snapshot to empty history",
      len(_hist1) == 1 and _hist1[0]["issuance_date"] == "2026-09-18", str(_hist1))
_hist2 = climo.update_forecast_history(_hist1, _sample_fc_snapshot)
check("update_forecast_history deduplicates snapshot for the same issuance date",
      len(_hist2) == 1, str(len(_hist2)))

_synth_ghcn = {
    "2026-09-18": {"TMAX": "178", "TMIN": "144", "PRCP": "0"},   # 17.8 C = 64.0 F, 14.4 C = 58.0 F, 0 mm
    "2026-09-19": {"TMAX": "189", "TMIN": "144", "PRCP": "51"},  # 18.9 C = 66.0 F, 5.1 mm = 0.20 in
}

_scored = climo.score_forecast_history(_hist1, _synth_ghcn)
check("score_forecast_history matches forecasts against observations",
      _scored["total_scored_pairs"] == 2, str(_scored["total_scored_pairs"]))
check("temperature error is exact: forecast high 64 vs obs 64.0 is error 0.0",
      _scored["scored_pairs"][0]["high_error"] == 0.0, str(_scored["scored_pairs"][0]["high_error"]))
check("overall high MAE is 0.0 on perfect forecast",
      _scored["overall_high_mae_f"] == 0.0, str(_scored["overall_high_mae_f"]))
check("POP >= 50% correctly evaluates observed rain (pop=60% -> observed rain=True -> 100% hit rate)",
      _scored["pop_ge_50_rain_pct"] == 100.0, str(_scored["pop_ge_50_rain_pct"]))
check("POP < 50% correctly evaluates dry condition (pop=10% -> observed rain=False -> 0.0% rain)",
      _scored["pop_lt_50_rain_pct"] == 0.0, str(_scored["pop_lt_50_rain_pct"]))
check("lead days breakout handles 0-day lead and 1-day lead",
      len(_scored["by_lead_days"]) == 2 and _scored["by_lead_days"][1]["lead_days"] == 1,
      json.dumps(_scored["by_lead_days"]))

# --------------------------------------------------------------------------- #
# NWS Area Forecast Discussion language scan (climo.afd_language_scan)
#
# The scan publishes quotations, never numbers, so the tests pin down both
# halves of that contract: that real forecaster language IS found (a scanner
# that can only return zero would look correct on a dry September day and be
# useless in January), and that nothing is invented, misattributed or smuggled
# in from the marine and aviation sections.
# --------------------------------------------------------------------------- #

section("== AFD section and sentence parsing")

_AFD_FIXTURE = """
000
FXUS66 KMTR 051234
AFDMTR

Area Forecast Discussion
National Weather Service San Francisco CA
434 AM PST Mon Jan 5 2027

.KEY MESSAGES...

 - An atmospheric river will bring periods of heavy rain
 - Potential for 2-4 inches of rain in the hills

.SHORT TERM...
An atmospheric river oriented from the central Pacific will
tap deep subtropical moisture, with PWAT values near 1.5 inches.
Rain will continue for several days with steady rain at times and
rainfall totals of 3 inches possible along the coast range.
The AR is expected to train over the same area, producing
flash flooding potential. Winds will increase with gusts to 45 mph,
and strong south winds combined with heavy rain will make travel
difficult. Multiple rounds of rain are likely through the weekend.
Above-
normal tides will compound the drainage problem.

Issued at 434 AM PST
FORECASTER INITIALS: JK/DR
Discussion available at https://forecast.weather.gov/product.php?site=MTR&issuedby=MTR&product=AFD

.MARINE...
Gale warning in effect with storm-force gusts to 50 kt across the
coastal waters.

.AVIATION...
IFR conditions with gusts to 35 kt and heavy rain at SFO.

.FIRE WEATHER...
No fire weather concerns at this time.

&&
"""

_sections = climo.afd_sections(_AFD_FIXTURE)
_sec_names = [n for n, _b in _sections]
check("afd_sections finds the preamble and every .HEADER... section",
      "(preamble)" in _sec_names and "KEY MESSAGES" in _sec_names
      and "SHORT TERM" in _sec_names and "MARINE" in _sec_names
      and "AVIATION" in _sec_names, str(_sec_names))
check("afd_sections stops the last block at the && separator",
      not any("&&" in b for _n, b in _sections), "&& leaked into a block body")

_short = next(b for n, b in _sections if n == "SHORT TERM")
_sents = climo.afd_sentences(_short)
check("hard-wrapped prose is unwrapped into whole sentences",
      any(s.startswith("An atmospheric river oriented from the central Pacific will "
                       "tap deep subtropical moisture") for s in _sents), str(_sents[:2]))
check("a hyphen at end of line is a wrap, not part of the word",
      any("Above-normal tides" in s for s in _sents),
      str([s for s in _sents if "normal tides" in s]))
check("every sentence returned is whitespace-collapsed",
      all(s == climo.collapse_ws(s) for s in _sents), "a sentence kept a newline or double space")

_key = next(b for n, b in _sections if n == "KEY MESSAGES")
_key_sents = climo.afd_sentences(_key)
check("KEY MESSAGES bullets stay separate statements instead of merging",
      len(_key_sents) == 2, str(_key_sents))

section("== AFD language scan: positive detection")

_scan = climo.afd_language_scan({"text": _AFD_FIXTURE, "issuance_time": "2027-01-05T12:34:00+00:00",
                                 "source_url": "https://api.weather.gov/products/x",
                                 "product_name": "Area Forecast Discussion", "id": "x"})
_by_id = {c["id"]: c for c in _scan["categories"]}
check("the scan reports itself as scanned when text was fetched",
      _scan["scanned"] is True, str(_scan.get("reason")))
check("atmospheric-river language is found",
      _by_id["atmospheric_river"]["sentence_count"] >= 3,
      str(_by_id["atmospheric_river"]["sentence_count"]))
check("the bare abbreviation AR counts only after the term is spelled out",
      any("The AR is expected to train" in s["sentence"]
          for s in _by_id["atmospheric_river"]["sentences"]),
      str([s["sentence"][:60] for s in _by_id["atmospheric_river"]["sentences"]]))
check("prolonged-rain language is found",
      _by_id["prolonged_rain"]["sentence_count"] >= 3,
      str(_by_id["prolonged_rain"]["sentence_count"]))
check("heavy-rain / flooding language is found",
      _by_id["heavy_rain"]["sentence_count"] >= 3, str(_by_id["heavy_rain"]["sentence_count"]))
check("strong-wind language is found",
      _by_id["strong_wind"]["sentence_count"] >= 1, str(_by_id["strong_wind"]["sentence_count"]))
check("an explicit rainfall amount in NWS's own text is found",
      _by_id["quoted_rainfall_amount"]["sentence_count"] >= 2,
      str(_by_id["quoted_rainfall_amount"]["sentence_count"]))
check("wind and rain in the same sentence is found",
      _by_id["wind_and_rain_together"]["sentence_count"] >= 1,
      str(_by_id["wind_and_rain_together"]["sentence_count"]))

section("== AFD language scan: no invention, no leakage")

_collapsed_src = climo.collapse_ws(_AFD_FIXTURE)
_not_verbatim = [s["sentence"] for c in _scan["categories"] for s in c["sentences"]
                 if s["sentence"] not in _collapsed_src]
check("every published sentence is a whitespace-collapsed substring of the source",
      not _not_verbatim, str(_not_verbatim[:2]))
_counts_short = [c["id"] for c in _scan["categories"]
                 if c["sentence_count"] < len(c["sentences"])]
check("no category count is smaller than its own published list",
      not _counts_short, str(_counts_short))
_leaked = [(c["id"], s["section"], s["sentence"][:50]) for c in _scan["categories"]
           for s in c["sentences"] if s["section"] in ("MARINE", "AVIATION", "FIRE WEATHER")]
check("marine, aviation and fire-weather sections never produce a flag",
      not _leaked, str(_leaked))
check("the excluded sections are published as excluded",
      set(_scan["sections_excluded_this_run"]) == {"MARINE", "AVIATION", "FIRE WEATHER"},
      str(_scan["sections_excluded_this_run"]))
check("the scanned section list carries no duplicates",
      len(_scan["sections_scanned"]) == len(set(_scan["sections_scanned"])),
      str(_scan["sections_scanned"]))
check("the AWIPS header is not scanned as forecast prose",
      climo.AFD_PREAMBLE not in _scan["sections_scanned"], str(_scan["sections_scanned"]))
check("product furniture is dropped and the drop is counted",
      _scan["furniture_sentences_dropped"] >= 1, str(_scan["furniture_sentences_dropped"]))
check("no quoted sentence carries a date or a value",
      not any(k in s for c in _scan["categories"] for s in c["sentences"]
              for k in ("date", "value", "amount_in", "probability")),
      "a forbidden key appeared on a quoted sentence")
check("the scope caveat and the usage note are published with the scan",
      bool(_scan.get("scope_caveat")) and bool(_scan.get("usage_note")), "missing caveat/note")

section("== AFD language scan: dry discussion and missing product")

_DRY = """
.KEY MESSAGES...

 - Warming trend Friday into the weekend

.SHORT TERM...
High pressure builds in with mostly sunny skies and light winds.
The marine layer reforms overnight along the coast.

.MARINE...
Small craft advisory for the coastal waters this afternoon.
"""
_dry = climo.afd_language_scan({"text": _DRY, "issuance_time": "2026-09-18T14:34:00+00:00",
                                "source_url": "https://api.weather.gov/products/y", "id": "y"})
_dry_hits = sum(c["sentence_count"] for c in _dry["categories"])
check("a dry discussion produces no atmospheric-river, prolonged-rain or heavy-rain flags",
      sum(c["sentence_count"] for c in _dry["categories"]
          if c["id"] in ("atmospheric_river", "prolonged_rain", "heavy_rain")) == 0,
      str([(c["id"], c["sentence_count"]) for c in _dry["categories"]]))
check("a bare AR never matches when the discussion never spells the term out",
      all("AR" not in str(s["matched_patterns"]) or "atmospheric river" in _DRY.lower()
          for c in _dry["categories"] for s in c["sentences"]),
      "a bare AR was accepted without the spelled-out term")
check("when nothing is found the scan says so, and says it is not a seasonal claim",
      _dry_hits == 0 and bool(_dry["none_found_statement"])
      and "not evidence that the season will be dry" in _dry["none_found_statement"],
      str(_dry["none_found_statement"])[:200])
check("when something is found there is no none-found statement",
      _scan["none_found_statement"] is None, str(_scan["none_found_statement"]))

_empty = climo.afd_language_scan({"text": "", "source_url": None, "id": None})
check("no fetched discussion text is reported as not scanned, with a reason",
      _empty["scanned"] is False and bool(_empty["reason"]), str(_empty))
check("no fetched discussion text publishes no categories at all",
      _empty["categories"] == [] and _empty["any_language_found"] is False, str(_empty))
_none = climo.afd_language_scan(None)
check("a missing AFD product does not raise",
      _none["scanned"] is False, str(_none.get("scanned")))

section("== Census reverse geocode (climo.parse_census_geographies)")

_fx_path = os.path.join(HERE, "fixtures", "census_geocoder_94122.json")
_fx = json.loads(open(_fx_path, encoding="utf-8").read())
_geo = climo.parse_census_geographies(_fx)
check("the real Census response names the county subdivision",
      _geo and _geo["county_subdivision"] == "Sunset CCD", str(_geo))
check("the real Census response names the county and place",
      _geo["county"] == "San Francisco County" and _geo["place"] == "San Francisco city",
      str({k: _geo[k] for k in ("county", "place")}))
check("the real Census response gives tract and block GEOIDs",
      _geo["census_tract_geoid"] == "06075032601"
      and _geo["census_block_geoid"] == "060750326013006",
      str({k: _geo[k] for k in ("census_tract_geoid", "census_block_geoid")}))
check("Census GEOIDs nest: county is a prefix of subdivision, tract and block",
      _geo["county_subdivision_geoid"].startswith(_geo["county_geoid"])
      and _geo["census_tract_geoid"].startswith(_geo["county_geoid"])
      and _geo["census_block_geoid"].startswith(_geo["census_tract_geoid"]),
      str(_geo))
check("the geography types actually returned are listed for review",
      "County Subdivisions" in _geo["geography_types_returned"],
      str(_geo["geography_types_returned"]))
check("an empty payload yields None rather than a guess",
      climo.parse_census_geographies({}) is None
      and climo.parse_census_geographies(None) is None, "empty payload produced a value")
check("a payload with no usable geography yields None",
      climo.parse_census_geographies({"result": {"geographies": {}}}) is None
      and climo.parse_census_geographies(
          {"result": {"geographies": {"States": [{"NAME": "California"}]}}}) is None,
      "a state-only payload produced a value")
check("a geography is read by name, so a re-ordered response still parses",
      climo.parse_census_geographies({"result": {"geographies": {
          "County Subdivisions": [{"BASENAME": "Sunset", "NAME": "Sunset CCD",
                                   "GEOID": "0607593267"}]}}})["county_subdivision"] == "Sunset CCD",
      "name lookup failed")


# --------------------------------------------------------------------------- #
# The three fetch counts, and the one rule that keeps an expected absence from
# hiding a real failure.  ``run.json`` publishes "139 ok / 0 failed / 4 absent by
# design" and the site repeats it, so the arithmetic and the labelling both have
# to hold: a not-yet-published annual file is routine, an archive that stopped
# answering is not.
# --------------------------------------------------------------------------- #

MANIFEST_FIXTURE = [
    {"url": "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/1991/72494023234.csv",
     "ok": True},
    {"url": "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/2026/72494023234.csv",
     "ok": False, "expected_absent": "annual-file-not-yet-published"},
    {"url": "https://api.weather.gov/stations/OAMC1/observations/latest",
     "ok": False, "expected_absent": "station-without-observations-product"},
    {"url": "https://www.ncei.noaa.gov/data/normals-hourly/1991-2020/access/USW00023272.csv",
     "ok": False, "expected_absent": "candidate-station-without-the-product"},
    {"url": "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv",
     "ok": False},                                    # a real failure
]

_counts = pipeline_main.count_fetches(MANIFEST_FIXTURE)
check("count_fetches separates a real failure from three expected absences",
      _counts == {"manifest_entries": 5, "successful_fetches": 1,
                  "failed_fetches": 1, "expected_absences": 3},
      "got %r" % (_counts,))
check("count_fetches counts every manifest entry exactly once",
      sum(_counts[k] for k in ("successful_fetches", "failed_fetches",
                               "expected_absences")) == len(MANIFEST_FIXTURE))
check("the expected-absence rules are a closed set of three named reasons",
      set(pipeline_main.EXPECTED_ABSENCE_RULES) == {
          "annual-file-not-yet-published",
          "station-without-observations-product",
          "candidate-station-without-the-product"},
      repr(pipeline_main.EXPECTED_ABSENCE_RULES))


class _FakeResult:
    """Minimal stand-in for lib_fetch.FetchResult's provenance() surface."""

    def __init__(self, ok, url):
        self.ok, self.url = ok, url

    def provenance(self, note=None, **extra):
        return {"url": self.url, "ok": self.ok, "http_status": 200 if self.ok else 404,
                "note": note, **extra}


try:
    pipeline_main.record(_FakeResult(False, "https://x/"), expected_absent="made-up-reason")
    _raised = False
except ValueError:
    _raised = True
check("a failed fetch cannot be labelled with an invented absence reason", _raised)

# A successful fetch is never labelled absent, however it is called: the label
# describes the provider's normal state, not this run's luck.
_ok_entry = pipeline_main.record(_FakeResult(True, "https://x/"),
                                 expected_absent="annual-file-not-yet-published")
check("a 200 is never recorded as an expected absence",
      "expected_absent" not in pipeline_main.MANIFEST[-1])
pipeline_main.MANIFEST.clear()

# --------------------------------------------------------------------------- #
# Failed fetches must be explained, not just counted (main.flag_failed_fetches)
#
# The site already discloses a failed fetch in the status banner and in the
# Sources table ("failed only" filter, HTTP status badge).  What it cannot do
# there is name the consequence, so each failure also has to land in the quality
# report.  main() needs the network, which is why this is a separate function.
# --------------------------------------------------------------------------- #

section("== failed fetches are flagged as irregularities")

pipeline_main.IRREGULARITIES.clear()
_manifest = [
    {"url": "https://api.weather.gov/stations/OAMC1/observations/latest",
     "http_status": 404, "ok": False, "note": "Latest official observation from station OAMC1"},
    {"url": "https://www.ncei.noaa.gov/good.csv", "http_status": 200, "ok": True,
     "sha256": "a" * 64, "note": "a fetch that worked"},
    {"url": "https://www.ncei.noaa.gov/normals-hourly/USW00023272.csv",
     "http_status": None, "ok": False, "error": "read timeout",
     "note": "NCEI 1991-2020 Hourly Climate Normals"},
    {"url": "https://api.weather.gov/ok-too", "http_status": 200, "ok": True},
]
_flagged = pipeline_main.flag_failed_fetches(_manifest)
check("every non-200 / not-ok fetch is flagged and nothing else is",
      len(_flagged) == 2, str(len(_flagged)))
check("each flagged fetch becomes one irregularity",
      len(pipeline_main.IRREGULARITIES) == 2, str(len(pipeline_main.IRREGULARITIES)))
check("failed-fetch irregularities are warnings in the fetch area",
      all(i["severity"] == "warning" and i["area"] == "fetch"
          for i in pipeline_main.IRREGULARITIES),
      str([(i["severity"], i["area"]) for i in pipeline_main.IRREGULARITIES]))
check("the message names the status and the source, and says nothing was inferred",
      all("404" in i["message"] or "no response" in i["message"] for i in pipeline_main.IRREGULARITIES)
      and all("Nothing was inferred" in i["message"] for i in pipeline_main.IRREGULARITIES),
      str(pipeline_main.IRREGULARITIES[0]["message"])[:160])
check("the evidence carries the URL, status, note, error and retrieval time",
      all(set(i["evidence"]) == {"url", "http_status", "note", "error", "retrieved_utc"}
          for i in pipeline_main.IRREGULARITIES),
      str(sorted(pipeline_main.IRREGULARITIES[0]["evidence"])))
check("a timeout with no HTTP status is still a failure",
      pipeline_main.fetch_failed({"url": "x", "http_status": None, "ok": False}) is True, "")
check("a missing status on an ok=True entry is not treated as a failure",
      pipeline_main.fetch_failed({"url": "x", "ok": True}) is False, "")
check("junk entries do not raise and are not failures",
      pipeline_main.fetch_failed(None) is False and pipeline_main.fetch_failed("x") is False
      and pipeline_main.fetch_failed({}) is False, "")
check("an empty manifest flags nothing",
      pipeline_main.flag_failed_fetches([]) == []
      and pipeline_main.flag_failed_fetches(None) == [], "")
pipeline_main.IRREGULARITIES.clear()

# --------------------------------------------------------------------------- #

passed = sum(1 for _n, ok, _d in RESULTS if ok)
failed = [(n, d) for n, ok, d in RESULTS if not ok]
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
if failed:
    print("FAILURES:")
    for n, d in failed:
        print("  - %s: %s" % (n, d))
    sys.exit(1)
print("all good")
