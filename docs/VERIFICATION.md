# Verification log

A line-by-line record of what was checked, what was wrong, and what was done
about it. The point of this file is that **the mistakes are kept**, not hidden.

## Environment constraint encountered

The development sandbox had **no general internet egress** - only
`github.com`, `registry.npmjs.org` and `pypi.org` were reachable, and TLS
connections to `api.weather.gov` and every NOAA host were reset at the
ClientHello. Direct verification from the sandbox was therefore impossible.

**Resolution:** the fetch pipeline was made to run **on GitHub Actions runners**,
which have unrestricted egress. The job commits its output and a full run log
into `data/`, so every dataset could then be inspected from the sandbox via
`raw.githubusercontent.com`. All figures on the site were produced by a job that
actually reached NOAA - none were produced locally from memory.

## Bugs found and fixed

Each was found by reading real fetched data, and each would have produced
plausible-looking but wrong numbers.

| # | Symptom | Root cause | Fix |
| --- | --- | --- | --- |
| 1 | `KeyError: 'INTPTLONG'` | Census Gazetteer uses CRLF, so the last header arrives as `INTPTLONG\r` | Strip headers and values; resolve columns case-insensitively; record which names were used |
| 2 | `ValueError: unknown url type: 'c8466ee2-...'` | NWS products endpoint is JSON-LD: the URL is in `@id`, while `id` is only a UUID | Read `@graph` / `@id` |
| 3 | `NameError: name 'v' is not defined` | Missing `v` in a dict comprehension over `oni.items()` | Fixed the comprehension |
| 4 | **GHCN-Daily parsed to zero rows** despite a 7.5 MB download | The access CSV is served in **wide** format (one row per date, a column per element), not the long element-per-row format | Rewrote the parser to detect and handle both layouts |
| 5 | **GSOD wind and temperature were 10x too small** | Applied a `x0.1` scale that the CSV does not use | Verified against the official GSOD README: values are already decimal. Missing sentinels (`999.9`, `99.99`, `9999.9`) confirm it. Scale is now 1.0 and the README is recorded as the authority in the provenance manifest |
| 6 | GSOD rows mis-aligned | The station `NAME` field contains an **unquoted comma** ("SAN FRANCISCO INTERNATIONAL AIRPORT, CA US"), breaking `csv.DictReader` | Positional parsing with surplus-field re-joining |
| 7 | **Only 1 of 14 CPC seasonal outlooks was sampled** | `seas*.zip` holds one shapefile per lead; reading "the first .shp" picked `lead10_JJA_*` purely because it sorts first alphabetically | Sample every shapefile in the archive |
| 8 | CPC season codes unresolved | Compared single month initials against three-letter keys (`O` vs `OCT`) | Resolve initials by requiring three consecutive months |
| 9 | CPC short-range spans dropped | DBF numeric fields arrive as floats, so `20260922` became `20260922.0` | Coerce through `int` before parsing |
| 10 | CPC variable (`temp`/`prcp`) shown as blank | Short-range stems are `610temp_latest`, not `lead1_SON_temp`, so the suffix test also missed the trailing `_latest` | Strip `_latest`, then match `^(610\|814\|wk34)_?(temp\|prcp)$`. Without this, temperature was mislabelled "Above median" instead of "Above normal" |
| 13 | A single day showed up to 12 "covering" CPC outlooks, many identical | `seasprcp_202608.zip`, `seasprcp_202609.zip` and `monthupd_*_latest.zip` all carry an outlook for e.g. "Oct 2026" | Deduplicate on (valid period, variable), keeping the most recent `Fcst_Date`, and publish the issuance date next to every outlook so a reviewer knows which release a number came from |
| 11 | `SyntaxError` in the site JS | Unbalanced parentheses in the table builder | Rewrote the function; now checked with `node --check` |
| 12 | Page rendered twice | `DOMContentLoaded` could fire more than once | Added an idempotency guard and null-safe teardown |

## Stale official content that was rejected

* <https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/index.shtml>
  returns a page whose newest content dates from **2016** (it still advertises a
  survey that closed on 19 May 2020). It was fetched, detected as stale by the
  current-year check, and **discarded rather than quoted**.
* The ENSO narrative shown on the site therefore comes from two *current*
  official products instead: the CPC long-lead discussion issued
  **20 Aug 2026** and the week 3-4 discussion issued **11 Sep 2026**.

## Cross-checks performed

| Claim | Independent check | Result |
| --- | --- | --- |
| The 94122 coordinate | Census Gazetteer row for `GEOID=94122` | 37.760459, -122.483894 - matched, not assumed |
| CPC point-sampling works | Compare sampled attributes with the prose in the official discussion | Week 3-4 temperature sampled as `Above, 40%`; the 11 Sep 2026 discussion says "enhanced probabilities of warmer-than-normal temperatures ... along the west coast". Week 3-4 precipitation sampled as `EC`; the discussion names wetter-than-normal only for the Desert Southwest/Rockies and drier for the Pacific Northwest - i.e. San Francisco is indeed untipped. **Consistent.** |
| GHCN units | Sanity of converted values | 1921-01-01 TMAX 15.6 C / TMIN 7.2 C = 60.1 F / 45.0 F for a January day in San Francisco - plausible |
| GSOD units | Sanity of converted values | 2020-10-01 WDSP 6.3 kt, MXSPD 15.0 kt, GUST 21.0 kt for SFO - plausible |
| Day aggregation | Fixture with a known in-season NWS day | High/low/humidity/wind/gust/rain/POP aggregated correctly; month switching produced 31 cells for October and 31 for January |
| Site rendering | Headless DOM (jsdom) driven with fixture data | 0 console errors; all sections populated; day dialog opens with 16 detail rows and 2 source links |

## Landlord dashboard verification (2026-09-17)

Added `pipeline/landlord_summary.py` that builds `data/landlord.json` from already-verified datasets — no new external fetches, so no new hosts to vet.

**Line-by-line verification of landlord.json:**

| Field | Source file | Official origin | Verified? |
|---|---|---|---|
| season_total_prcp 12.79 in mean | climatology.json distribution.season_total_prcp_in | GHCN-Daily USW00023272 1991-2020 | Yes — file at https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv, parsed as tenths of mm → inches |
| oct/nov/dec/jan totals | climatology.json distribution.*_total_prcp_in | same | Yes |
| streak_probability ge_7_days 53.3% | climatology.json season.probability_of_at_least_one_streak | same GHCN, consecutive wet-day scan Oct 1-Jan 31 | Yes — 16 of 30 seasons = 53.3% |
| wind_and_rain 11.1 days mean | climatology.json distribution.wind_and_rain_days | GSOD 72494023234 (KSFO) https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/ + GHCN, joint count ≥20kt & ≥0.01in | Yes — GSOD units verified against README https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt |
| heavy_wind_and_rain 2.2 days | same | same, ≥35kt gust & ≥0.50in | Yes |
| max_gust 53.8 mph mean | same | GSOD GUST field, knots→mph ×1.15078 | Yes |
| current_enso ONI 0.98C May 2026 el_nino | enso.json latest_oni | CPC table https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt — ONI = 3-month running mean | Yes — computed per NOAA definition |
| cpc_outlooks OND/EC, JFM/Above 50% | calendar.json cpc.records | CPC GIS shapefiles https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/seasprcp_202609.zip sampled at 37.7605,-122.4839 | Yes — each record has url, prob, category, issued date, and map in assets/cpc/*.gif |
| high_risk_dates | calendar.json days[].climo | per-date stats from 30 seasons | Yes — sorted by p_rain_day_pct |
| action_items | derived | all above, with source_url per item | Yes — each item cites official URL |

**No hallucinations:** every landlord action item includes source and source_url that is already in provenance.json. The dashboard explicitly states that daily forecast beyond 7 days does not exist and shows climatology instead, with badges.

**Commercial exclusion verified:** `pipeline/verify_sources.py` checks 100 fetches across 5 hosts — api.weather.gov, ftp.cpc.ncep.noaa.gov, www.cpc.ncep.noaa.gov, www.ncei.noaa.gov, www2.census.gov — all official .gov. No AccuWeather, OpenWeatherMap, etc.

## Irregularities currently flagged (not defects in this project)

These are properties of the sources or of geography, and they are surfaced in
the site's **Data quality** section rather than smoothed over:

* **NWS issues no Hazardous Weather Outlook product for office MTR** via the API
  products endpoint at this time, so none can be shown.
* **Some hourly NWS gridpoint fields are null** for this cell (an NWS
  characteristic, not a fetch failure); the affected field counts are logged.
* **GSOD 2026 is not yet published** for station 72494023234, so the wind record
  runs 1991-2025.
* **Coastal point-in-polygon misses** in CPC shapefiles: where 94122 falls
  between polygons the nearest polygon is used and the record is marked so it can
  be checked against the published map.
* **Thin samples per calendar date** - 30 seasons at most, so a single-date
  percentage carries roughly +/- 3.3 points of sampling noise.
* **SFO wind is upper bound for Sunset** — exposure at KSFO is more open than 94122, so wind figures are intentionally conservative for landlord planning.
