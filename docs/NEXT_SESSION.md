# Next session — handoff, open work and limitations

Read this first. It says what is done, what is verified, what is still open, and
which official endpoint each open item depends on. Everything below refers to
official, free, no-key sources; nothing here depends on commercial data.

---

## 1. State at the end of this session (17 Sep 2026, second working session)

**What is live:** the nightly pipeline, the Oct 2026 – Jan 2027 scoreboard, the
landlord dashboard, the current-forecast panel, the verification ledger, and the
headless/inline tests. GitHub Pages serves `main` from the repository root, and the
`Update NOAA data` workflow refreshes `data/` on every push and nightly at 07:15 UTC.

### What changed in the second session (17 Sep 2026)

1. **The executive summary the brief leads with is now on the page**: a ranked
   list of **repair & maintenance cost drivers** (`data/landlord.json` →
   `executive_summary.cost_drivers`, rendered as the "Repair & maintenance cost
   drivers" card on the landlord dashboard). Six drivers: prolonged wet spells,
   heavy single-day rain, wind + rain together, peak gusts, total seasonal water
   load (with the ENSO/CPC tilt), and wet-day frequency. Every evidence number is
   copied from the verified structures; the "why it matters" sentence is labelled
   on the card as guidance, not a weather claim.
2. **New published statistics**: expected heavy-rain days per season as sums of the
   per-date 1991-2020 probabilities — 14.97 days ≥ 0.25 in and 3.19 days ≥ 1.00 in
   (method published next to the numbers; the ledger re-derives them). Plus NCEI
   Storm Events county context: 99 flood-type reports 2014-2026 (under-reporting
   flagged), of which 4 carry a recorded property-damage figure.
3. **Bugs 31-33 found and fixed** (table in `docs/VERIFICATION.md`): the ENSO stat
   printed the raw token `el_nino` and a bare " ONI ·" subtitle; the key finding
   and ENSO action item printed the raw token and a unit-less `1.8C` with a tilt
   sentence that always claimed "wetter"; and a latent `None%` formatting defect
   on CPC probabilities in the action checklist.
4. **Ledger 23 → 26 checks** (`cost-drivers-structure`,
   `cost-driver-expected-days-arithmetic`, `raw-phase-tokens`); unit tests
   **89 → 121**; smoke test gained 4 render guards (cost-driver evidence/source
   rules, no raw phase tokens, ENSO season naming, no `NaN`/`undefined` in main
   sections). The source-traceability sweep now also covers the landlord action
   checklist and cost-driver source URLs — all pass.
5. **Pipeline determinism confirmed**: re-running the derive steps against the
   committed inputs reproduces `data/calendar.json` byte-for-byte.

### First session (17 Sep 2026), earlier the same day

The summary below is kept for history; the numbers it quotes are superseded by the
ledger and test counts above.

**How to tell whether the last run was good** — do this before anything else:

```bash
git fetch origin
git log --oneline FETCH_HEAD -3                                  # "refresh NOT published" = the gate held
git show FETCH_HEAD:data/run_diagnostics.txt                     # *_EXIT codes, all 0 = good
git show FETCH_HEAD:data/verify_report.txt | head -6             # "checks: N passed, M failed"
git show FETCH_HEAD:data/verify.json | python3 -m json.tool | head -20
```

A failing ledger run commits **diagnostics only** and publishes nothing; the site then
keeps the last verified dataset. That is the designed behaviour, not an outage.

### What this session changed

1. **ENSO is now NOAA's published ONI product**, not a value derived here. The site had
   been showing a locally derived "+0.98 °C (May 2026)" while NOAA's published product
   already listed **JJA 2026 = +1.80 °C**. The derivation survives only as a published
   cross-check (AMJ 2026: 0.98 derived vs 0.95 official).
2. **Every quoted CPC sentence is fetched at build time** and stored verbatim with the
   SHA-256 of the page. The site previously hard-coded prose that quoted a superseded
   issuance (69% where the live discussion says 75%).
3. **Humidity exists on climatology days** — derived per calendar date from NCEI's
   1991–2020 hourly temperature and dew-point normals (Magnus formula), labelled as a
   derivation and naming the station. 365 dated values; all 123 days covered.
4. **A NOAA TEST tsunami warning is no longer shown as a real alert**; test messages
   are counted and displayed separately.
5. **CPC records are auditable**: each sampled outlook carries the containing polygon
   index, its bounding box, vertex count and the raw DBF attribute row.
6. **Verification ledger** (`pipeline/verify_claims.py`): 23 checks, 17 claims, each with
   URL, HTTP status, bytes, SHA-256, retrieval time, method and a cross-check.
7. **Offline unit tests** (`tests/test_parsers.py`, 89 assertions after the current
   host-allow-list checks, stdlib only) and a **headless render test** (`npm test`,
   jsdom). Both run in the `Tests` workflow.
8. Bugs **14–22** found and fixed, with root causes and evidence, in
   [`docs/VERIFICATION.md`](VERIFICATION.md) — including a deleted function that broke
   the pipeline, HTML-entity corruption of every quote, and a banner reading
   "reaches 0 day(s)". Nothing was hidden.

### Second pass, later the same day (17 Sep 2026)

A line-by-line re-read of the **rendered page** against `data/` and against the live
official endpoints. Every fetched value re-checked correctly — grid `MTR 82,105` and
zone `CAZ006` against `api.weather.gov/points`, `JJA 2026 = +1.80` and `AMJ 2026 = 0.95`
against the live `oni.ascii.txt`, and all four quoted CPC sentences verbatim against
the ENSO Diagnostic Discussion issued 10 Sep 2026 — but the pass found eight defects
(**bugs 23–30**, full table in [`docs/VERIFICATION.md`](VERIFICATION.md)).

The one that matters: **gusts and rain amounts were em dashes on every forecast day.**
The aggregation read only `/forecast/hourly`, which carries neither for this grid cell
(0 of 156 periods). The pipeline had *already fetched* `gridpoint_raw`, which has both.
Both fields — the brief's first two priorities — were therefore blank while NWS
published them. They are now filled from the gridpoint series, with the basis named on
every day, and cross-validated against NWS's own text ("gusts as high as 18 mph" /
"20 mph" against 18.4 and 19.6 mph derived here).

Also fixed: a CPC explanation describing a category it was not showing; a grammatically
broken sentence in the reality-check panel; source labels truncated to
`...access/USW000`; temperature outlooks sitting unlabeled in a rainfall table; humidity
rendered as `64.980032379224%`; source links resolved by array position (so adding one
made "Open on weather.gov" point at an API URL); and README prose that disagreed with
the data it described.

**Tests: 55 → 89 offline assertions**, and 7 new render checks. Each new check was
verified to **fail on the old code** before being committed, so none of them is
vacuous. Full suite is green: `89/89`, `npm test` passes, `verify_sources` 105 fetches
across 5 exact official hosts, `verify_claims` 23/23.

---

### Third pass, 17 Sep 2026 (this session) - the published-normals session

**What was added**

1. **NOAA's own published per-date daily normals**, shown beside this project's
   count of the same quantity, date by date, with the difference published rather
   than reconciled (`pipeline/climo.py` `parse_daily_normals` /
   `compare_daily_normals`; new section "Two official answers" and a per-day table in
   the day dialog). On the 123 dates of this window: rain day >= 0.01 in mean
   difference **-0.4 pp**, >= 0.25 in **-0.1 pp**, >= 1.00 in **+0.1 pp**, normal high
   **-0.6 F**, normal low **-0.3 F**. 25 dates differ by more than 10 points, which the
   page explains (30-season sampling error is about +/-9 points near p = 40 %).
2. **A day finder** on the scoreboard ("Jump to a date"): picks the month, marks the
   day, opens its detail.
3. **`GE###HI` columns resolved from the file, not assumed**: the digits are
   hundredths of an inch (GE001HI = >= 0.01 in), and the mapping now travels with the
   data as `layout.thresholds_in`, so a label cannot drift from its column.

**Defects found and fixed** (full table in [`VERIFICATION.md`](VERIFICATION.md),
bugs 34-39): the published-vs-derived comparison had been producing **no pairs at
all** because `build_calendar.py` carried a duplicate aggregator keyed on
`..._001in_pct` columns that do not exist; **123 dates published `-9999.00 in`** as a
precipitation percentile because NOAA's missing-value sentinel was not in the
missing list; the check written to catch that **could not fire** (it tested
`endswith("_pctl_in")` against a key spelled `pcp_50pctl_in`); climatically-mean
amounts were labelled `rain` on the tile; `import climo` was shadowed inside
`main()`; and prose still said the wind station was "~10 miles" away when the
pipeline computes 11.9.

**Verification:** ledger **32 checks, 0 failed, 0 warnings** on the regenerated
dataset; `tests/test_parsers.py` **170 assertions**; `npm test` green with new
guards proven to fail on the old code before being kept. Sandbox has no egress to
NOAA/NWS hosts, so every number came from the `Update NOAA data` workflow.

**The lesson worth keeping:** bug 37 was invisible in every offline fixture and
appeared only when the first dataset produced by CI was read line by line. Fixture
data cannot prove a parser is right about a publisher's conventions. Bug 38 is its
companion - a guard that cannot fire is worse than no guard, so the range rule now
lives in `climo.implausible_normals_value()` and is unit-tested.

## 2. Open work, in priority order

### 1. Hourly ISD wind → hour-by-hour simultaneous wind and rain
**Why:** the joint wind+rain statistic currently pairs a local-day rain total with a
UTC-day wind figure (GSOD is 00–24Z ≈ 16:00–16:00 Pacific). This is the largest
remaining accuracy gap for the landlord's "wind and rain at the same time" question.
**Source:** `https://www.ncei.noaa.gov/data/global-hourly/access/{year}/{station}.csv`
(free, no key, station `72494023234`).
**Work:** fetch Oct–Jan hours for 1991–2025, convert to `America/Los_Angeles`, count
hours where precipitation > 0 and wind ≥ 20 kt coincide, and publish that **next to**
the current daily approximation until the two are shown to agree. Keep raw hourly
files out of the repository (aggregates only); give it its own job and timeout.
**Effort:** ~1 day plus runtime.

### 2. NWS forecast verification loop
**Why:** accountability, and the forecast is already fetched every night.
**Work:** append each run's 7-day forecast to a compact history file, then score it
against the following days' GHCN/GSOD observations: POP calibration (did it rain when
POP ≥ 50%?), mean absolute error of the forecast high, broken out by month.
**Effort:** ~1 day.

### 3. CPC back-testing for this location
**Work:** keep a compact extract of each issuance (the `seasprcp_YYYYMM.zip` archives
are already downloaded nightly), then once each valid period completes, compare the
sampled probability category with the observed GHCN total at 94122 and publish hit
rates. A 5–10 year back-test is possible immediately from archived issuances.
**Effort:** ~1–2 days.

### 4. Atmospheric-river flag from the NWS Area Forecast Discussion
**Why:** ARs drive most high-impact California rain and are the best available signal
for "days of straight rain"; the AFD is already fetched verbatim.
**Work:** match AR language, attach date-coded mentions to the days they refer to, and
show the quoted sentence with its source. Never turn a mention into a number.
**Effort:** ~0.5 day.

### 5. A nearer wind record than SFO
SFO is 11.9 mi away and more exposed, so every wind number is an upper bound. Assess
`SFOC1` and other ISD stations in the city; if a usable overlap exists, publish a
documented ratio (labelled an estimate) alongside — never instead of — the raw SFO
numbers.

### 6. Per-field provenance in the day dialog (partly done)
**Done 17 Sep 2026:** humidity, gust and rain amount each publish the basis actually
used (`humidity_basis`, `gust_basis`, `rain_amount_basis`) and the dialog shows it.
**Still open:** temperature, wind and rain chance carry no per-field basis, and none of
the six links to the exact *element of the exact file* (e.g. the `PRCP` column of the
`2026-12-14` row of `USW00023272.csv`). Cheap, and it makes the manual line-by-line
check faster.

### 7. Multi-ZIP support and a digest
The pipeline is already parameterised by coordinate; multi-ZIP is mostly front-end
work. A digest (RSS or email) for "a day enters the 7-day window with POP ≥ X" or "an
NWS alert is issued for CAZ006" needs an opt-in and a privacy story first.

### 8. Model guidance (only with heavy caveats)
CFSv2/NMME on NOMADS would give a genuine model view of Oct–Jan, but it needs GRIB2
decoding, large storage, and it is **not an official forecast**. If built, it must be a
separate tier or page with prominent warnings — never merged into the scoreboard.

---

## 3. Standing rules (do not break these)

* **No invented daily values** beyond the NWS horizon. Days are badged
  `NWS FORECAST` or `CLIMATOLOGY`; CPC outlooks stay probabilities for a period.
* **Every number must be traceable** to a recorded official fetch (URL + status +
  bytes + SHA-256). If it cannot be traced it does not get published — the ledger
  enforces this and the workflow gate refuses to publish on failure.
* **Never loosen a check to make a run pass.** Loosening hides exactly the class of
  defect this project exists to prevent. If a check is wrong, fix the check and say so
  in `docs/VERIFICATION.md`.
* **Never force-push.** The data workflow appends commits to the same branch, so a
  rejected push means `git pull --rebase origin <branch>` first.
* **Run `gh` from the repository directory** (otherwise: "not a git repository").
* **Quotes are copied, never paraphrased**, and are decoded to plain text first
  (the `quotes-plain-text` ledger check fails the run otherwise).
* Commercial providers (AccuWeather and similar) stay excluded; the exclusion is
  documented on the site, in the README and in `docs/DATA_SOURCES.md`.

---

## 4. Commands that matter

```bash
# full local rebuild (fetches nothing in the sandbox - run on CI or a networked box)
python3 pipeline/main.py --outdir data
python3 pipeline/build_calendar.py
python3 pipeline/landlord_summary.py
python3 pipeline/verify_claims.py        # exit 1 on any failed check
python3 tests/test_parsers.py            # offline, stdlib only
npm install && npm test                  # headless render of the page
python3 -m http.server 8000              # then open http://localhost:8000

# CI
gh run list --branch <branch> --limit 3
gh run watch <run-id> --exit-status
```

---

## 5. Links for manual review (all official, free, no key)

* Live site — <https://buffedlizard55-lab.github.io/SFWeather/>
* Repo — <https://github.com/buffedlizard55-lab/SFWeather>
* **Official ONI product** — <https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt>
* **ENSO Diagnostic Discussion** (Alert System Status) — <https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml>
* CPC long-lead discussion — <https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html>
* CPC 6–10 / 8–14 day and weeks 3–4 — <https://www.cpc.ncep.noaa.gov/products/predictions/610day/>, <https://www.cpc.ncep.noaa.gov/products/predictions/814day/>, <https://www.cpc.ncep.noaa.gov/products/predictions/WK34/>
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
