# Next session — handoff, open work and limitations

Read this first. It says what is done, what is verified, what is still open, and
which official endpoint each open item depends on. Everything below refers to
official, free, no-key sources; nothing here depends on commercial data.

---

## State at the end of this session (17 Sep 2026)

**Working:** the nightly pipeline, the Oct 2026 – Jan 2027 scoreboard, the landlord
dashboard, the current-forecast panel, the verification ledger, the headless site
test, and the GitHub Pages site.

**Verified end to end:** every headline number is re-derived from its dataset by
`pipeline/verify_claims.py`, and the nightly job publishes data only when every
check passes. The ledger, the claim list and the checks are rendered on the site
under **Verification**.

**What this session changed**

1. **ENSO is now NOAA's published ONI product**, not a value derived here. This
   fixed a real defect: the site had been showing a derived value labelled
   "May 2026, +0.98 °C" while NOAA's published product already listed JJA 2026 at
   **+1.80 °C** (a strong El Niño). The derivation is kept only as a published
   cross-check against the official season, and any disagreement > 0.15 °C is
   raised as an irregularity.
2. **ENSO statements are captured verbatim.** The ENSO Diagnostic Discussion
   (`ensodisc.shtml`) — which carries the Alert System Status — is now fetched
   alongside the long-lead discussion, and the exact sentences containing numbers
   are stored with the SHA-256 of the page. No sentence on the site is typed by
   hand any more. (Previously the page hard-coded quotes from a superseded
   issuance: "69% chance of a historic event" when the live discussion says 75%.)
3. **Test alerts are separated from real alerts.** A NOAA TEST tsunami warning had
   been counted as an active warning.
4. **Humidity exists for climatology days.** NCEI's 1991-2020 hourly normals of
   temperature and dew point are fetched; RH is derived per calendar date with the
   Magnus formula and labelled as a derivation, naming the station.
5. **Independent cross-check on the climatology.** NOAA's published monthly normals
   are fetched and compared with the project's GHCN-derived monthly means (largest
   difference 0.07 in on the first run).
6. **CPC outlook records are auditable.** Each sampled outlook now carries the
   containing polygon index, its bounding box and the raw DBF attribute row.
7. **Verification ledger + site test**, both wired into CI. The ledger caught four
   bugs in code written the same session before they could reach the site.

---

## Open work, in priority order

### 1. Hourly ISD wind → hour-by-hour simultaneous wind and rain
**Why:** the joint wind+rain statistic currently pairs a local-day rain total with
a UTC-day wind figure (GSOD is 00-24Z ≈ 16:00-16:00 Pacific). This is the single
biggest accuracy gap for the landlord's "wind and rain at the same time" question.
**Source:** `https://www.ncei.noaa.gov/data/global-hourly/access/{year}/{station}.csv`
(free, public, no key, same station `72494023234`).
**Work:** fetch the Oct-Jan hours of 1991-2025, convert to `America/Los_Angeles`,
count hours where precipitation > 0 and wind ≥ 20 kt simultaneously, and compare
with the current daily-max method. Publish only aggregates; never commit the raw
hourly files.
**Caveat to publish:** the result must be presented *next to* the existing daily
approximation, not instead of it, until the two are shown to agree.
**Effort:** ~1 day plus runtime; put it in its own job with its own timeout.

### 2. NWS forecast verification loop
**Why:** accountability. The forecast is already fetched nightly; scoring it costs
almost nothing and proves the pipeline's value over time.
**Work:** append each run's 7-day forecast to a compact history file, then score
against the next day's GHCN/GSOD observations. Publish: POP calibration (did it
rain when POP ≥ 50%?), mean absolute error of the forecast high, and the same by
month. Everything stays inside already-verified hosts.
**Effort:** ~1 day.

### 3. CPC back-testing for this location
**Why:** the site reports CPC tips but never scores them.
**Work:** accumulate every issuance into a history file (the shapefiles are already
downloaded nightly), then once each valid period completes, compare the sampled
probability category with the observed GHCN total at 94122 and publish hit rates.
**Effort:** ~1-2 days, mostly waiting for seasons to complete. A short back-test
over the last 5-10 years of archived issuances (`seasprcp_YYYYMM.zip`) is possible
immediately if the storage/time budget allows.

### 4. Atmospheric-river flag from the NWS Area Forecast Discussion
**Why:** ARs drive nearly all high-impact California rain and are the best available
signal for "days of straight rain". The AFD text is already fetched verbatim.
**Work:** regex for atmospheric-river language, attach the *date-coded* mentions to
the days they refer to, and show the quoted sentence with its source. Never convert
a mention into a number or a probability.
**Effort:** ~0.5 day.

### 5. A nearer wind record than SFO
**Why:** SFO is ~10 mi away and more exposed; every wind number is an upper bound.
**Work:** assess `SFOC1` and any other ISD stations in the city; if a usable
overlap exists, publish a documented ratio (labelled an estimate) alongside the raw
SFO numbers, not instead of them.

### 6. Per-field provenance in the day dialog
Each number in the dialog should link to the exact element of the exact file it came
from. Cheap, and it makes the manual line-by-line check faster for a reviewer.

### 7. Multi-ZIP support and a digest
The pipeline is already parameterised by coordinate; multi-ZIP is mostly front-end
work. A digest (RSS or email) for "day enters the 7-day window with POP ≥ X" or "NWS
alert for CAZ006" needs an opt-in and a privacy story before it is built.

### 8. Model guidance (only with heavy caveats)
CFSv2/NMME on NOMADS would give a genuine model view of Oct-Jan, but it needs GRIB2
decoding, large storage, and it is **not an official forecast**. If it is ever
built, it must be a separate tier or page with prominent warnings — never merged
into the scoreboard.

---

## Operational notes

* **Nightly:** `.github/workflows/update-data.yml`, 07:15 UTC, after the NWS 00Z
  cycle and CPC's daily outlook posts. Also runs on every push.
* **Verification gate:** if `verify_claims.py` fails, the workflow commits
  *diagnostics only* (`data/pipeline.log`, `run_diagnostics.txt`,
  `quality_report.json`, `verify.json`, `verify_report.txt`) with the message
  "refresh NOT published", so the site keeps the last verified numbers.
* **Site test:** `.github/workflows/site-test.yml` runs `npm test`
  (`tests/smoke.js`, jsdom) on any change to the page, CSS, JS or tests. It renders
  the page against the committed data and fails on empty sections, a broken day
  dialog or a broken CSV export.
* **Local run:** standard library only —
  `python3 pipeline/main.py --outdir data`, then `build_calendar.py`,
  `landlord_summary.py`, `verify_claims.py`, then `python3 -m http.server 8000`.
* **No-hallucination rule:** never invent a daily value beyond the NWS horizon; always
  badge `NWS FORECAST` vs `CLIMATOLOGY`; CPC outlooks stay probabilities for a
  period; every number on the page must exist in `data/` with a source URL and a
  recorded fetch. If a number cannot be traced, it does not get published — the
  ledger enforces this.

---

## Links for manual review (all official, free, no key)

* Live site — <https://buffedlizard55-lab.github.io/SFWeather/>
* Repo — <https://github.com/buffedlizard55-lab/SFWeather>
* Census Gazetteer (ZCTA 94122) — <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip>
* Census reverse geocoder (check the point) — <https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x=-122.483894&y=37.760459&benchmark=Public_AR_Current&vintage=Current_Current&format=json>
* NWS point → grid — <https://api.weather.gov/points/37.7605,-122.4839>
* NWS hourly grid — <https://api.weather.gov/gridpoints/MTR/82,105/forecast/hourly>
* NWS human forecast — <https://forecast.weather.gov/MapClick.php?lat=37.7605&lon=-122.4839>
* NWS alerts (CAZ006) — <https://api.weather.gov/alerts/active?zone=CAZ006>
* NWS Area Forecast Discussion — <https://api.weather.gov/products/types/AFD/locations/MTR>
* **Official ONI product** — <https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt>
* **ENSO Diagnostic Discussion** — <https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml>
* CPC long-lead discussion — <https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html>
* CPC GIS outlooks — <https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/>
* CPC seasonal index — <https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/seasonal.php>
* CPC 6-10 / 8-14 / weeks 3-4 / 30-day — <https://www.cpc.ncep.noaa.gov/products/predictions/610day/>, <https://www.cpc.ncep.noaa.gov/products/predictions/814day/>, <https://www.cpc.ncep.noaa.gov/products/predictions/WK34/>, <https://www.cpc.ncep.noaa.gov/products/predictions/30day/>
* Niño 3.4 monthly table (cross-check only) — <https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt>
* GHCN-Daily `USW00023272` — <https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv>
* GSOD archive — <https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/>
* GSOD README (units) — <https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt>
* Monthly normals `USW00023272` — <https://www.ncei.noaa.gov/data/normals-monthly/1991-2020/access/USW00023272.csv>
* Hourly normals (humidity source) — <https://www.ncei.noaa.gov/data/normals-hourly/1991-2020/access/USW00023234.csv>
* ISD hourly archive (open item 1) — <https://www.ncei.noaa.gov/data/global-hourly/access/>
* Storm Events — <https://www.ncdc.noaa.gov/stormevents/>
