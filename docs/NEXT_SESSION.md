# Next session — handoff, open work and limitations

Read this first. It says what is done, what is verified, what is still open, and
which official endpoint each open item depends on. Everything below refers to
official, free, no-key sources; nothing here depends on commercial data.

---

## State at the end of this session (17 Sep 2026)

**What is live:** the nightly pipeline, the Oct 2026 – Jan 2027 scoreboard, the
landlord dashboard, the current-forecast panel, the verification ledger and the
headless tests. The site is published on GitHub Pages from `data/` in this repo,
and the datasets are refreshed by the `Update NOAA data` workflow on every push and
every night at 07:15 UTC.

**How to tell whether the last run was good** (do this before anything else):

```bash
gh run list --branch <branch> --limit 3
git fetch origin && git show FETCH_HEAD:data/run_diagnostics.txt   # *_EXIT codes
git show FETCH_HEAD:data/verify_report.txt | head -6               # checks: N passed, M failed
git log --oneline -3                                               # "refresh NOT published" means the gate held
```

A run that fails the ledger commits **diagnostics only** (message: "refresh NOT
published"), so the site keeps the last verified dataset. That is normal and safe.

### What this session changed

1. **ENSO is NOAA's published ONI product**, not a value derived here. The site had
   been showing a derived "+0.98 °C for May 2026" while NOAA's published product
   already listed **JJA 2026 at +1.80 °C**. The derivation survives only as a
   published cross-check (AMJ 2026: 0.98 derived vs 0.95 official).
2. **Every quoted CPC sentence is fetched at build time** and stored verbatim with
   the SHA-256 of the page. Previously the ENSO prose was hard-coded and quoted a
   superseded issuance (69% where the live discussion says 75%).
3. **Humidity exists on climatology days**, derived per calendar date from NCEI's
   1991-2020 hourly normals of temperature and dew point (Magnus formula), labelled
   as a derivation and naming the station. 365 dated values, all 123 days covered.
4. **NOAA test messages** are counted separately and never shown as real warnings.
5. **CPC records are auditable**: every sampled outlook carries the containing
   polygon index, its bounding box, vertex count and the raw DBF attribute row.
6. **Verification ledger** (`pipeline/verify_claims.py`): 20 checks, 17 claims, each
   claim with URL, HTTP status, bytes, SHA-256, retrieval time, method and a
   cross-check. A failure blocks publication.
7. **Offline unit tests** (`tests/test_parsers.py`, 53 assertions, stdlib only) and a
   **headless site test** (`npm test`, jsdom). Both run in the `Tests` workflow.
8. Bugs **14–22** found and fixed this session are listed in
   [`docs/VERIFICATION.md`](VERIFICATION.md) — including a function deletion that
   broke the pipeline, HTML-entity corruption of every quote, and a banner that read
   "reaches 0 day(s)".

---

## Open work, in priority order

### 1. Hourly ISD wind → hour-by-hour simultaneous wind and rain
**Why:** the joint wind+rain statistic pairs a local-day rain total with a UTC-day
wind figure (GSOD is 00–24Z ≈ 16:00–16:00 Pacific). This is the biggest remaining
accuracy gap for "wind and rain at the same time".
**Source:** `https://www.ncei.noaa.gov/data/global-hourly/access/{year}/{station}.csv`
(free, no key, same station `72494023234`).
**Work:** fetch Oct–Jan hours for 1991–2025, convert to `America/Los_Angeles`, count
hours where precipitation > 0 and wind ≥ 20 kt coincide, and publish that **next to**
the current daily approximation until the two are shown to agree. Keep raw hourly
files out of the repository; publish aggregates only. Give it its own job/timeout.
**Effort:** ~1 day plus runtime.

### 2. NWS forecast verification loop
**Why:** accountability, and the data is already fetched every night.
**Work:** append each run's 7-day forecast to a compact history file, then score it
against the next day's GHCN/GSOD observations: POP calibration (did it rain when POP
≥ 50%?), mean absolute error of the forecast high, by month. Publish the score.
**Effort:** ~1 day.

### 3. CPC back-testing for this location
**Work:** keep a small history of each issuance (`seasprcp_YYYYMM.zip` is already
downloaded nightly, so archive a compact extract), then once each valid period has
completed, compare the sampled probability category with the observed GHCN total at
94122 and publish hit rates. A 5–10 year back-test is possible immediately from the
archived issuances if storage/time allows.
**Effort:** ~1–2 days.

### 4. Atmospheric-river flag from the NWS Area Forecast Discussion
**Why:** ARs drive most high-impact California rain and are the best available signal
for "days of straight rain". The AFD is already fetched verbatim.
**Work:** match AR language, attach date-coded mentions to the days they refer to, and
show the quoted sentence with its source. Never turn a mention into a number.
**Effort:** ~0.5 day.

### 5. A nearer wind record than SFO
SFO is ~10 mi away and more exposed; every wind number is an upper bound. Assess
`SFOC1` and other ISD stations in the city; if a usable overlap exists, publish a
documented ratio (labelled an estimate) alongside the raw SFO numbers.

### 6. Per-field provenance in the day dialog
Each number in the dialog should link to the exact element of the exact file it came
from. Cheap, and it speeds up the manual line-by-line check.

### 7. Multi-ZIP support and a digest
The pipeline is already parameterised by coordinate; multi-ZIP is mostly front-end
work. A digest (RSS or email) for "a day enters the 7-day window with POP ≥ X" or "an
NWS alert is issued for CAZ006" needs an opt-in and a privacy story first.

### 8. Model guidance (only with heavy caveats)
CFSv2/NMME on NOMADS would give a genuine model view of Oct–Jan, but it needs GRIB2
decoding, large storage, and it is **not an official forecast**. If built, it must be
a separate tier or page with prominent warnings — never merged into the scoreboard.

---

## Standing rules (do not break these)

* **No invented daily values** beyond the NWS horizon. Days are badged
  `NWS FORECAST` or `CLIMATOLOGY`; CPC outlooks stay probabilities for a period.
* **Every number must be traceable** to a recorded official fetch (URL + status +
  bytes + SHA-256). If it cannot be traced, it does not get published — the ledger
  enforces this and the workflow gate refuses to publish on failure.
* **Never loosen a check to make a run pass.** Loosening hides exactly the class of
  defect the project exists to prevent.
* **Never force-push.** The data workflow appends commits to the same branch, so a
  rejected push means `git pull --rebase origin <branch>` first.
* **`gh` only works from the repository directory.**
* Commercial providers (AccuWeather and similar) stay excluded and that exclusion is
  documented on the site, in the README and in `docs/LIMITATIONS.md`.

---

## Links for manual review (all official, free, no key)

* Live site — <https://buffedlizard55-lab.github.io/SFWeather/>
* Repo — <https://github.com/buffedlizard55-lab/SFWeather>
* **Official ONI product** — <https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt>
* **ENSO Diagnostic Discussion** (Alert System Status) — <https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml>
* CPC long-lead discussion — <https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html>
* CPC GIS outlooks — <https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/>
* Census Gazetteer (ZCTA 94122) — <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip>
* Census reverse geocoder (check the point) — <https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x=-122.483894&y=37.760459&benchmark=Public_AR_Current&vintage=Current_Current&format=json>
* NWS point → grid — <https://api.weather.gov/points/37.7605,-122.4839>
* NWS hourly grid — <https://api.weather.gov/gridpoints/MTR/82,105/forecast/hourly>
* NWS alerts (CAZ006) — <https://api.weather.gov/alerts/active?zone=CAZ006>
* NWS Area Forecast Discussion — <https://api.weather.gov/products/types/AFD/locations/MTR>
* GHCN-Daily `USW00023272` — <https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv>
* GSOD archive — <https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/>
* GSOD README (units) — <https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt>
* Monthly normals `USW00023272` — <https://www.ncei.noaa.gov/data/normals-monthly/1991-2020/access/USW00023272.csv>
* Hourly normals (humidity source) — <https://www.ncei.noaa.gov/data/normals-hourly/1991-2020/access/USW00023234.csv>
* ISD hourly archive (open item 1) — <https://www.ncei.noaa.gov/data/global-hourly/access/>
* Storm Events — <https://www.ncdc.noaa.gov/stormevents/>
