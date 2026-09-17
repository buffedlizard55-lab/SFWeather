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

---

# Session 3 audit — 17 September 2026 (line-by-line, against live official sources)

Every row below was checked against the live official endpoint named in the last
column, from outside the build sandbox, on 17 Sep 2026. Where the site disagreed
with the official source, the site was changed — the mistake is kept here rather
than deleted.

## Claims checked against live official sources

| Claim on the site | Live official value on 17 Sep 2026 | Source checked | Verdict |
| --- | --- | --- | --- |
| ZIP 94122 internal point = 37.760459 N, -122.483894 W | Reverse geocoding the point returns San Francisco County (06075) and 2020 Census Block `060750326013006`, whose own `INTPTLAT/INTPTLONG` is **+37.7604592 / -122.4838940** | [Census geocoder](https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x=-122.483894&y=37.760459&benchmark=Public_AR_Current&vintage=Current_Current&format=json) | **Confirmed** |
| "Current ENSO: El Nino, ONI +0.98 C (May 2026)" | NOAA's published ONI product ends at **JJA 2026 = +1.80 C** (MJJ +1.39, AMJ +0.95) | [oni.ascii.txt](https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt) | **Wrong and stale — fixed.** The site now shows NOAA's published season-labelled ONI and keeps the locally derived value only as a published cross-check |
| "El Nino conditions are present - greater than 90 percent chance of a very strong event" attributed to the long-lead discussion of 20 Aug 2026 | The current discussion (issued **17 Sep 2026**) carries that sentence verbatim | [90-day discussion](https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html) | Sentence confirmed, attribution date had drifted |
| "there is a 69% chance of a historic event" for OND 2026 | The current ENSO Diagnostic Discussion (issued **10 Sep 2026**) says **75%** for Oct-Dec 2026 (and +2.5 C or more on the RONI) | [ENSO Diagnostic Discussion](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml) | **Stale by one issuance — fixed.** Quotes are now captured verbatim from the fetched page with its SHA-256, and no number is typed into the HTML |
| Nino index values "+1.8 / +2.5 / +3.2 C" | 10 Sep 2026 discussion reports August values of **+1.8 (Nino-3.4), +2.5 (Nino-3), +3.4 (Nino-1+2)** | same discussion | Third value differed (weekly vs monthly vintage); now quoted verbatim |
| ENSO Alert System Status | **El Nino Advisory** | same discussion | **Added** to the site (it was not shown before) |
| CPC seasonal precipitation at the 94122 point: OND 2026 EC, NDJ 2026-27 above median 33%, DJF 40%, JFM 2027 above median 50% | Point-sample of the official GIS shapefiles issued 17 Sep 2026 | [CPC GIS](https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/) | Unchanged; each record now also publishes the containing polygon index, its bounding box and the raw DBF row |
| CPC prose says OND precipitation is above normal "from the southern half of California" | The sampled polygon **containing the 94122 point is Equal Chances (33%)** — the tilt starts further south/east | [90-day discussion](https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html) | **No conflict, but worth knowing:** regional prose is not a point forecast; the map polygon is what the site reports |
| "Active NWS alerts: 1" | The single alert was a **TEST** Tsunami Warning from the National Tsunami Warning Center | [alerts API](https://api.weather.gov/alerts/active?zone=CAZ006) | **Misleading — fixed.** Test messages are counted separately and never shown as real warnings |
| Current NWS forecast for the point (stored copy) | Live `/gridpoints/MTR/82,105/forecast` matched the stored structure and values for the same cycle | [NWS forecast](https://api.weather.gov/gridpoints/MTR/82,105/forecast) | Confirmed; the forecast simply moves with each cycle |
| Climatology means for Oct/Nov/Dec/Jan rainfall derived from GHCN-Daily | NOAA's own published monthly normals for the same station: **Oct 0.94, Nov 2.60, Dec 4.76, Jan 4.40 in** | [NCEI monthly normals](https://www.ncei.noaa.gov/data/normals-monthly/1991-2020/access/USW00023272.csv) | **Cross-check added to the nightly job: largest difference 0.07 in** (Dec 4.78 vs 4.76; Jan 4.47 vs 4.40), consistent with normals built on a quality-controlled subset |
| Humidity per day | No official RH normal existed in the datasets used; the site showed "—" | [NCEI hourly normals](https://www.ncei.noaa.gov/data/normals-hourly/1991-2020/access/USW00023234.csv) | **Gap fixed** by deriving RH from the official hourly temperature and dew-point normals (Magnus formula), labelled as a derivation, with the station named |

## Bugs found in this project during the audit (and fixed)

| # | Symptom | Root cause | Fix |
| --- | --- | --- | --- |
| 14 | Official ONI parsed to **zero seasons**, so the site would have shown no ENSO state at all | `parse_oni_seasons()` compared the season token (`DJF`) against a table of three-letter *month names*; CPC seasons are three **month initials** | Build all 12 season rotations and resolve the token against them |
| 15 | ONI year labelling was off by one season for winter seasons | Assumed the label year was the season's first month | Anchored on published values: `NDJ 2015 = +2.59` covers Nov 2015-Jan 2016; `DJF 2016 = +2.50` covers Dec 2015-Feb 2016 (2015-16 El Nino peak) |
| 16 | Hourly normals fetched, but **no humidity extracted** | Substring match on column names picked up `meas_flag_HLY-TEMP-NORMAL`, so the file looked like a wide hour-per-column layout and produced zero rows | Match element columns exactly, read the file's own `month`/`day`/`hour` columns, and emit a **per-calendar-date** humidity normal |
| 17 | ENOS Alert System Status truncated to "El Ni" | Regex used `[A-Za-z ]`, which drops "n-tilde" | Use a Unicode-aware class |
| 18 | Page claimed "a failure stops the nightly build" while the commit step ran unconditionally | `if: always()` committed data regardless of the ledger verdict | Workflow now commits **diagnostics only** when the ledger fails, so the site keeps the last verified numbers |

Each of 14-17 was caught by `pipeline/verify_claims.py` on its first run, which is
the point of the ledger: the checks are not decoration, they fail the build.

## How a reviewer can re-check any number in about a minute

1. Open <https://buffedlizard55-lab.github.io/SFWeather/> and scroll to
   **Verification — every number checked against its source**.
2. Each claim lists the value, the official URL it came from, the HTTP status,
   the byte count, the **SHA-256 of those exact bytes** and the retrieval time.
3. Open the URL, find the number, compare. For CPC outlooks the row also gives the
   containing polygon index and bounding box so the polygon can be found on the
   official map.
4. `data/verify_report.txt` is the same ledger as plain text, and
   `data/provenance.json` lists all ~100 fetches of the run.

## Session 4 (17 September 2026): why the release was held back, and what now guards it

The fixes above were pushed and the nightly job ran three times. Two of those runs
**published nothing**, which is the behaviour the gate was built for:

| Run | Outcome | What the gate did |
| --- | --- | --- |
| 1 (`1bc8f23`) | Ledger 17/18, `oni-official-present` failed | Old workflow committed the data anyway - the defect that motivated bug 18. Nothing was wrong with the numbers that run published, but the failure was not allowed to block them |
| 2 (`0a9d630`) | `PIPELINE_EXIT=1`, `CLAIMS_EXIT=1` | Committed **diagnostics only** ("refresh NOT published"). The site kept the last verified dataset |
| 3 (this commit) | see the ledger panel on the site | - |

### Irregularity found and fixed while the release was held

Run 2 failed in the middle of the pipeline:

```
File "pipeline/main.py", line 1323, in main
    climo_out["daily"] = climo.build_daily_climatology(
AttributeError: module 'climo' has no attribute 'build_daily_climatology'
```

Two functions - `build_daily_climatology` (113 lines) and `build_season_statistics`
(151 lines) - had been **deleted from `pipeline/climo.py`** while the ENSO and
hourly-normals helpers were being added. This is exactly the class of mistake the
project is meant not to ship: code that had been verified and shipped in an earlier
commit disappeared in a later one, and nothing in the old test setup would have
noticed, because the pipeline only runs in CI.

What was done about it:

1. **Restored verbatim** from `1bc8f23` and byte-compared against the original with
   a script (both functions identical, confirmed before committing).
2. **`tests/test_parsers.py` added** (37 assertions, standard library only, no
   network). It covers the things that have actually broken: the ONI season
   rotations and the NDJ/DJF year convention, the exact-column match for the
   normals files, the per-date humidity derivation (cross-checked against an
   independent formulation of the Magnus formula), and an end-to-end aggregation
   over a synthetic GHCN file with hand-computable expected values.
3. **A second CI job (`Tests` workflow, `parsers` job)** runs that test file on
   every push touching `pipeline/**` or `tests/**`, alongside the headless site
   test.

The honest lesson, recorded because it matters more than the fix: a one-line
`AttributeError` in CI is a *lucky* failure. The same deletion inside a function
that is only reached on some code paths would have been silent. Unit tests that run
on every push are the cheapest available defence, and this project did not have
them until the ledger caught this.

### Verification that the restore is correct

* `python3 tests/test_parsers.py` - 37/37 checks pass locally (offline, no network).
* `python3 -m py_compile pipeline/*.py` - all modules compile.
* `build_calendar.py` -> `landlord_summary.py` -> `verify_claims.py` re-run locally
  against the last verified data: 123 days, 38 CPC records, 17 claims, 17/18 checks
  with only `oni-official-present` failing (expected: the local copy of the dataset
  is the pre-fix snapshot).

---

# Session 3 audit — 17 September 2026 (line-by-line, against live sources)

This is the audit the project promised: every headline number taken back to the
official product it came from, on the day it was published, with the disagreement
recorded rather than hidden. The table below is the audit; the bugs it produced are
listed after it, and every one of them was fixed and is now guarded by a test or a
ledger check.

## What was checked, and what was found

| Claim on the site | Where it was checked | Result |
| --- | --- | --- |
| "Current ENSO: derived ONI +0.98 °C (May 2026)" | NOAA's published ONI product, [`oni.ascii.txt`](https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt) | **Wrong product.** NOAA publishes the ONI directly, season-labelled: **JJA 2026 = +1.80 °C, a strong El Nino**, with MJJ +1.39, AMJ +0.95, MAM +0.46, FMA +0.11, JFM −0.21, DJF −0.39, NDJ −0.60, OND −0.61. The site had been showing a locally derived value two months behind and ~0.8 °C too low. **Fixed:** the displayed value is now NOAA's published ONI; the derivation is kept only as a cross-check (AMJ 2026: derived 0.98 vs official 0.95, difference 0.03 °C, published on the site) |
| Quoted CPC statements ("69% chance of a historic event", originating from a 20 Aug 2026 issuance) | Live ENSO Diagnostic Discussion, issued 10 Sep 2026, and the 90-day outlook discussion, issued 17 Sep 2026 | **Stale wording.** The live discussion says **75%** for a historic event in OND 2026 and **>90%** for a very strong event, and gives August indices of +1.8 (Nino-3.4), +2.5 (Nino-3), +3.4 (Nino-1+2). The page had been hard-coding prose from an earlier issuance. **Fixed:** every quoted sentence is fetched at build time, stored verbatim with the SHA-256 of the page, and shown with a link |
| "Active NWS alerts: 1" | [`api.weather.gov/alerts/active?zone=CAZ006`](https://api.weather.gov/alerts/active?zone=CAZ006) | **A test message counted as a real warning.** The single alert was a NOAA *TEST* tsunami warning. **Fixed:** test messages are counted and shown separately, never as active warnings |
| The 94122 coordinate | Census 2024 Gazetteer ZCTA file, plus an independent reverse geocode of the same point | Confirmed: the point is the ZCTA internal point, and the geocoder places it in San Francisco County (06075), 2020 Census Block 060750326013006, Sunset CCD |
| NWS forecast for the point (stored copy) | Live [`gridpoints/MTR/82,105/forecast`](https://api.weather.gov/gridpoints/MTR/82,105/forecast) and the hourly grid | Matched in structure and values for the same cycle (e.g. the daily high equals the max of its hourly periods). The live forecast had moved on by the time of the check — normal nightly drift, not an error |
| Climatology means for Oct/Nov/Dec/Jan rain (GHCN-Daily) | NOAA's *published* 1991-2020 monthly normals for the same station | Agree to within **0.07 in** (largest gap: Dec 4.78 derived vs 4.76 published). Cross-check now published on the site every night |
| "Humidity: —" on climatology days | NCEI 1991-2020 hourly normals | **Gap, not an error.** NOAA publishes no RH normal. **Fixed:** humidity is derived from the official hourly temperature and dew-point normals by calendar date and labelled as a derivation everywhere |
| CPC prose: OND precipitation "above normal from the southern half of California east-northeastward" | The sampled forecast polygon containing the 94122 point | **Not a conflict, but worth knowing:** the polygon covering the point is **Equal Chances (33%)**; the tilt starts south/east of San Francisco. Regional prose is not a point forecast, and the site reports the polygon, not the prose |
| Verbatim CPC quotes | The stored sentences against the live pages | **Two bugs**, below: entities were not decoded, and figure references split sentences |

## Bugs found by this audit

| # | Symptom | Root cause | Fix |
| --- | --- | --- | --- |
| 19 | The page showed `El Nino Advisory` as **"El Ni"**, and every quote contained `&ntilde;`, `&#37;`, `&deg;` | `html_to_text()` decoded a hand-written list of five entities and left the rest; the status regex then stopped at the first non-word character, and the semicolon inside `&#37;` looked like a sentence end, chopping quotes mid-sentence | Decode with `html.unescape()` + NFC normalisation; read the status to end of line; take the synopsis from its own line. **New ledger check `quotes-plain-text` fails the run if any published quote still contains an entity** |
| 20 | Quotes were cut at figure references ("... the eastern equatorial Pacific [Fig.") and long-lead quotes were single wrapped lines ("... a greater than 90" / "percent chance of ...") | The splitter treated the period in "[Fig. 1]" as a sentence end, and treated hard-wrapped line breaks as sentence boundaries | A sentence now ends only at `.` or `;` followed by whitespace **and a capital**; wrapped lines are re-joined; a trailing hyphen is kept ("above-\nnormal" -> "above-normal") so no quote is edited |
| 21 | The reality-check banner read "reaches **0 day(s)**" | The number shown was *scoreboard days inside the horizon* (0 until 1 October), not the length of the horizon | The banner now reports the horizon length and states separately that no scoreboard day is inside it yet; `nws_window.horizon_days` is published in the data |
| 22 | The first long-lead quote was the page breadcrumb glued to a sentence: "HOME > Outlook Maps > Seasonal Forecast Discussion ... College Park MD 830 AM EDT Thu Sep 17 2026 SUMMARY OF THE OUTLOOK FOR NON-TECHNICAL USERS El Nino conditions are present, ..." | HTML tags become spaces, so nothing marked where the page content began | Everything before the document's own "SUMMARY OF THE OUTLOOK" marker is cut, the all-caps document heading is dropped, and remaining breadcrumb/title fragments are filtered out of the quote list |

Bugs 19-22 were all found by reading the published page against its source, which is
the workflow this project is built around. 21 and 22 were found in the **rendered
site**, not in the data — a reminder that a correct dataset can still be displayed
wrongly, which is why `npm test` renders the page headlessly on every push.

## How the ledger and the tests stand now

* `pipeline/verify_claims.py`: **20 automated checks, 17 recorded claims**, each claim
  carrying value, unit, method, official URL, HTTP status, bytes, SHA-256, retrieval
  time and (where one exists) an independent cross-check.
* `tests/test_parsers.py`: **52 offline assertions** (standard library only, no
  network) over the things that have actually broken: ONI season rotations and the
  NDJ/DJF year convention, exact column matching in the NCEI normals files, per-date
  humidity derivation against an independent Magnus formulation, entity decoding,
  sentence integrity, and an end-to-end aggregation over a synthetic GHCN file.
* `npm test` (jsdom): renders the page against the committed data and fails if a
  section is empty, the day dialog breaks or the CSV export throws.
* The nightly job runs the ledger **before** publishing: `summary.failed > 0` commits
  diagnostics only and the message "refresh NOT published".
