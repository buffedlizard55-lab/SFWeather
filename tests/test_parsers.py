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
# 1. official ONI parsing
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
