# Next session — handoff

## 1. State at the end of this session (18 Sep 2026 — UI surface for NWS verification loop and CPC back-test)

**Ledger:** 53 checks, 19 claims — all pass.

**Tests:** `tests/test_parsers.py` 336/336 · `tests/falsify_guards.py` 23 cases ·
`tests/falsify_smoke.py` 13 cases · `npm test` (jsdom smoke) passes ·
`pipeline/verify_sources.py` passes · `pipeline/verify_claims.py` passes.

### What changed in this session

1. **Two new site sections**, surfaced visibly rather than sitting as silent data files:
   - **NWS forecast verification** (`#nws-verification`) — reads
     `data/forecast_verification.json`, reports the running scored-pair count, and
     explains why it currently reads 0 (the first pairs populate once GHCN-Daily
     observations catch up to the archived forecasts). Once pairs exist it shows
     high-temp MAE, POP calibration (rain frequency when POP ≥ 50 % vs < 50 %),
     and a lead-day breakdown. Nav link added.
   - **CPC back-test** (`#cpc-backtest`) — reads `data/cpc_backtest.json`; when
     that file is absent (the current state) it honestly reports the
     **data-source limitation**: CPC's live GIS server only exposes the current
     month's issuance, so historical `seasprcp_YYYYMM.zip` files must be
     bulk-fetched from a static archive before a hit-rate can be computed. It
     describes the exact work needed (vetted host, bulk fetch, existing sampling
     code path). Nav link added.
2. Both sections render cleanly in jsdom (smoke test passes); both handle the
   "no data yet" case with an explanatory callout rather than an empty panel.
3. Everything previously live is unchanged: nightly pipeline, scoreboard,
   landlord dashboard, bottom line, cost drivers, hour-by-hour wind+rain, AFD
   scanner, verification ledger, source provenance, Storm Events, published-vs-
   derived normals cross-check.

### What already existed and needed surfacing (not new code, just visibility)

- **NWS verification loop**: `pipeline/build_calendar.py` already appends the
  nightly forecast to `data/forecast_history.json` and calls
  `climo.score_forecast_history()`, which already computes MAE and POP
  calibration by lead day. The pipeline was already writing
  `data/forecast_verification.json`. It just wasn't being rendered on the page
  and the reader had no way to know why the count was 0. Both are now explicit.
- **A nearer wind record than SFO**: already assessed — the honest answer is
  "there isn't one with both wind and precipitation from an official long
  archive." `SFOC1` downtown (3.67 mi) carries no wind or precipitation in its
  feed; the next-nearest official co-loaded station is KSFO at 11.9 mi. That
  answer is published in `docs/LIMITATIONS.md` §2 and restated on the Wind card.

---

## 2. Open work — next session priority order

### 1. Back-fill the CPC archive to run the back-test for real

**Blocker:** `ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/` only hosts
`seasprcp_YYYYMM.zip` / `seastemp_YYYYMM.zip` for the current and previous month.
Historical issuances live at:
- CPC static archive — many are preserved at
  `https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/YYYY/`
  when it has been retained; and at
- **IRI Data Library** `http://iridl.ldeo.columbia.edu/SOURCES/.NOAA/.NCEP/.CPC/.seasonal/`
  which holds a shapefile archive back to 1995 — but this host is NOT on the
  vetted-host allow-list.

**Work:**
1. Pull the list of issuance months needed: every mid-month release from
   1995-08 through 2020-08 (25+ seasons, so OND, NDJ, DJF, JFM can all be scored
   against observed terciles).
2. If `iridl.ldeo.columbia.edu` is required, vet it, add it to
   `pipeline/verify_sources.py` `ALLOWED_HOSTS`, and document the decision in
   `docs/DATA_SOURCES.md`.
3. Write a `pipeline/cpc_backtest.py` (or extend `main.py`) that:
   - fetches each historical `seasprcp_YYYYMM.zip`,
   - samples it at the 94122 point using the existing `lib_shape.py`
     point-in-polygon (same code path used for live CPC outlooks),
   - reads the target season (e.g. `OND 2015` for the Aug 2015 issuance) from the
     DBF row,
   - computes the observed Oct/Nov/Dec/Jan precipitation total from GHCN-Daily
     USW00023272, assigns a tercile against the 1991–2020 distribution,
   - writes `data/cpc_backtest.json` with one row per issuance (season, CPC
     category, probability, observed tercile, hit/miss) plus an overall hit-rate
     summary broken out by category and lead.
4. Add a falsifiable ledger check (`cpc-backtest-sampling-method`) and at least
   one render guard (hit/miss pill must render when data is present).
5. Add a test with one synthetic season so the arithmetic is verified offline.

**Effort:** ~1–2 days. The sampling and scoring primitives already exist; the
new work is the bulk fetch and the host-vetting decision.

### 2. Chase why GSOD/ISD for KSFO stop at 2025-08-27

NCEI's annual files for station 72494023234 have not rolled forward. Either
the station identifier changed or NCEI has a lag in producing the GSOD annual
files. Check `isd-history.csv` for the station and look for a successor
`USAF-WBAN` id. If one exists, stitch the archives; if not, document that the
file ends where it ends and keep the stale-archive flag honest.

### 3. Deep links in the day dialog

Every field already names its basis, but a reader trying to manually verify
temperature on 14 December still has to download the whole GHCN CSV and search.
Per-field deep links (GHCN CSV row anchor, NWS hourly `startTime`) would make
manual verification a one-click step. **Effort:** a couple of hours.

### 4. AFD history archive

Store each scanned Area Forecast Discussion in `data/afd_history.json` so the
AFD card can say "the last discussion to mention an atmospheric river was
issued on …". That is a history of what NWS wrote, not a forecast, and would
make the card useful in January rather than only today. **Effort:** ~2 hours.

### 5. Multi-ZIP support and a digest

The pipeline is already parameterised by coordinate; multi-ZIP is mostly
front-end work. A digest (RSS or email) for "a day enters the 7-day window
with POP ≥ X" or "an NWS alert is issued for CAZ006" needs an opt-in and a
privacy story first.

### 6. Model guidance (only with heavy caveats)

CFSv2/NMME on NOMADS would give a genuine model view of Oct–Jan, but it needs
GRIB2 decoding, large storage, and is **not an official forecast**. If built
it must be a separate tier or page with prominent warnings — never merged into
the scoreboard.

---

## 3. How to tell whether the last nightly run was good

```bash
gh run list --branch main --limit 3
gh run watch <run-id> --exit-status
# After it finishes:
cat data/run_diagnostics.txt           # *_EXIT codes, all 0 = good
cat data/verify_report.txt | head -6   # "checks: N passed, M failed"
python3 -c "import json;print(json.load(open('data/verify.json'))['summary'])"
```

A failing ledger run commits **diagnostics only** and publishes nothing; the
site keeps the last verified dataset. That is designed behaviour, not an
outage.

---

## 4. Standing rules (do not break these)

* **No invented daily values** beyond the NWS horizon. Days are badged
  `NWS FORECAST` or `CLIMATOLOGY`; CPC outlooks stay probabilities for a period.
* **Every number must be traceable** to a recorded official fetch (URL + status +
  bytes + SHA-256). If it cannot be traced it does not get published — the ledger
  enforces this and the workflow gate refuses to publish on failure.
* **Never loosen a check to make a run pass.** If a check is wrong, fix the check
  and say so in `docs/VERIFICATION.md`.
* **Never force-push.** The data workflow appends commits to the same branch; a
  rejected push means `git pull --rebase origin <branch>` first.
* **Quotes are copied, never paraphrased**, decoded to plain text first.
* Commercial providers (AccuWeather and similar) stay excluded; the exclusion is
  documented. Any new host must be vetted and added to `ALLOWED_HOSTS` in
  `pipeline/verify_sources.py` deliberately — not with a wildcard suffix.

---

## 5. Commands that matter

```bash
# Local rebuild (fetches nothing in the sandbox — run on CI or a networked box)
python3 pipeline/main.py --outdir data
python3 pipeline/build_calendar.py
python3 pipeline/landlord_summary.py
python3 pipeline/verify_claims.py
python3 tests/test_parsers.py
python3 tests/falsify_guards.py
npm install && npm test
python3 tests/falsify_smoke.py
python3 -m http.server 8000   # http://localhost:8000
```

---

## 6. Links for manual review (all official, free, no key)

* Live site — <https://buffedlizard55-lab.github.io/SFWeather/>
* Repo — <https://github.com/buffedlizard55-lab/SFWeather>
* **Official ONI product** — <https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt>
* **ENSO Diagnostic Discussion** — <https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml>
* CPC long-lead discussion — <https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html>
* CPC GIS archive root — <https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/>
* NWS gridpoint MTR 82,105 — <https://api.weather.gov/gridpoints/MTR/82,105>
* NWS hourly — <https://api.weather.gov/gridpoints/MTR/82,105/forecast/hourly>
* NWS alerts CAZ006 — <https://api.weather.gov/alerts/active?zone=CAZ006>
* NWS AFD — <https://api.weather.gov/products/types/AFD/locations/MTR>
* GHCN-Daily USW00023272 — <https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv>
* GSOD archive — <https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/>
* GSOD README (units) — <https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt>
* Storm Events — <https://www.ncdc.noaa.gov/stormevents/>
* Census Gazetteer (ZCTA 94122) — <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip>
* Census reverse geocoder — <https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x=-122.483894&y=37.760459&benchmark=Public_AR_Current&vintage=Current_Current&format=json>
