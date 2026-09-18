# Next session — handoff, open work and limitations

Read this first. It says what is done, what is verified, what is still open, and
which official endpoint each open item depends on. Everything below refers to
official, free, no-key sources; nothing here depends on commercial data.

---

## 1. State at the end of this session (18 Sep 2026, session 7 — forecaster language, named geography, per-field basis)

**What is live:** the nightly pipeline; the Oct 2026 – Jan 2027 scoreboard with a
per-field basis behind every headline number; the landlord dashboard and its
executive bottom line; the current-forecast panel; a new *Area Forecast Discussion
language* card quoting NWS forecasters verbatim; a *Location* card naming the
forecast point from the Census geographer; the verification ledger at **47 checks
/ 18 recorded claims**; and three committed test harnesses (316 offline
assertions, jsdom render guards, and falsification harnesses that prove each
guard can fail). GitHub Pages serves `main` from the repository root; the
`Update NOAA data` workflow refreshes `data/` on every push and nightly at
07:15 UTC.

### What changed in this session

1. **AFD language scan** (`climo.afd_language_scan`, `docs/METHODS.md` §14): six
   storm-language categories, section-aware, marine/aviation/fire excluded,
   furniture filtered, quotations only — no date, amount or probability is ever
   attached to a quote. Card renders in `#now`; ledger checks
   `afd-language-verbatim` and `afd-language-quotations-only`; render guard 19.
2. **Census reverse geocode** (`main.fetch_census_geographies`,
   `climo.parse_census_geographies`, `docs/METHODS.md` §15): the published
   centroid is looked up against the Census geographer and the site names the
   geography the Census reports (`Sunset CCD`) instead of asserting a
   neighbourhood. Offline fixture from the real response at
   `tests/fixtures/census_geocoder_94122.json`; ledger check
   `census-geographies-traceable`; graceful degradation published as an
   irregularity when the lookup fails.
3. **Per-field basis on every published day value**, both tiers (bug 43): all six
   headline fields plus temperature now name their basis. Ledger check
   `day-field-basis-complete`; render guard 20.
4. **Documentation-drift guards** (`readme-figures-traceable`,
   `docs-current-dates-traceable`, warnings): a figure quoted in the README that
   the dataset does not publish, or a date near the run date that this run never
   published. The first run of that guard found **four real drift defects** —
   bugs 40, 41 and 42: a hand-typed CPC table in `LANDLORD_GUIDE.md` that
   mislabelled two 33% *Above normal* categories as "EC", a README forecast
   snapshot quoting a horizon and temperatures from a past run, and two files
   quoting a past run's null-period count. The hand-typed values were **removed,
   not corrected** — a number in prose cannot be re-derived by the ledger, so it
   will contradict the dataset again.
5. **Falsification harnesses committed and wired into CI**:
   `tests/falsify_guards.py` (15 ledger cases) and `tests/falsify_smoke.py`
   (8 render cases). Two of my own new render guards were caught by them on the
   first run (bug 47), and after the data refresh the ledger harness caught
   *itself*: two cases had quietly become no-ops because the refreshed dataset
   really did carry the evidence they were supposed to remove (bug 48). Both now
   mutate by removal and raise `AssertionError` if the target is absent, so a
   future refresh fails the harness loudly rather than weakening it.

   **Keep that property when adding cases:** a falsification case must assert
   that its mutation actually changed something.

### Known state to expect on the next run

* `census-geographies-traceable` **fails against the currently committed
  `data/run.json`**, which predates the geocode step. The first CI run that
  repopulates `run.json` resolves it; the check accepts either the published
  evidence or a recorded `geography` irregularity and rejects only the silent
  third case (a name with no evidence). If it still fails after a refresh, read
  `data/quality_report.json` first.
* The AFD card will look sparse in September: the current discussion contains no
  atmospheric-river, prolonged-rain or heavy-rain language. That is the correct
  output and the card says so — it is not a scanner failure. Re-check in January.
* `docs/LANDLORD_GUIDE.md` and `README.md` now contain **no** volatile CPC, ONI or
  forecast-window numbers. Keep it that way; the two warning guards exist to
  catch a regression.

---

### Session 6 (18 Sep 2026) — the executive-summary session

**What is live:** unchanged in shape — the nightly pipeline, the Oct 2026 – Jan
2027 scoreboard, the landlord dashboard, the current-forecast panel, the
verification ledger, and the headless tests. GitHub Pages serves `main` from the
repository root; the `Update NOAA data` workflow refreshes `data/` on every push
and nightly at 07:15 UTC.

### What changed in this session

1. **A real executive summary now leads the dashboard.** New card *"The bottom
   line — your six questions, answered in order"* (`landlord.json` →
   `executive_summary.bottom_line`, rendered by `renderBottomLine`): rain amount,
   rain duration, hard-rain days, wind, wind+rain together, storm severity. Each
   answer carries its numbers, a stated basis (observed record vs official
   outlook), a confidence line, and the official links. An answer with no source
   link is *withheld and marked*, not shown unsourced.
2. **Official-outlook strip** beside it (`executive_summary.official_outlook`):
   current ENSO state + Alert System Status + discussion link; how many CPC
   long-lead periods covering Oct–Jan carry a tilt above the 33.3% baseline; the
   observed record *conditioned on the same ENSO phase*; and how many scoreboard
   days are inside the real NWS horizon.
3. **Storm severity, quantified without borrowing a warning category.** New
   per-season counters from the same GHCN/GSOD files: days ≥0.50 / 1.00 / 2.00 /
   4.00 in (the exact thresholds NOAA NCEI publishes a percent-of-years value
   for), sustained wind ≥30 kt, gusts ≥40 / 50 kt, and
   `severe_wind_and_rain_days` (≥1.00 in **and** a gust ≥40 kt on the same date).
   Published as distributions plus records bound to the season that produced them.
4. **A counted-vs-NOAA-published table** for heavy-rain days per season, so the
   project's own count and NOAA's own published expectation appear side by side
   on the same thresholds instead of asking anyone to trust one of them.
5. **Two real pipeline bugs and six bugs in the project's own guards** found by
   mutating fixture copies and requiring each new guard to *fail* (VERIFICATION.md
   bugs 40–47). Notably: NCEI's Storm Events CSVs are CP1252 and were being
   decoded with `errors="replace"`, which had committed `5.46\ufffd\ufffd\ufffd in`
   into the published narrative; and a number row whose value was blank
   *disappeared* from the executive summary instead of rendering as an em dash.
6. **Ledger 32 → 39 checks; `test_parsers.py` 170 → 212; smoke guards +4.**
7. **CPC baseline honesty enforced in both directions** — a polygon whose
   probability sits on the 33.3% three-way baseline may not be rendered as a
   tilt, and nothing may be flagged as a baseline case that is not one. The rule
   now applies identically in the landlord table, the main CPC season table and
   the day dialog.

### Still open from this session

* The committed `data/` in this branch was refreshed by the workflow triggered by
  the push. `severity-counters-arithmetic` starts comparing real per-season
  values on that run; before it, the counters were absent and the check sat in
  its deferred branch.
* `data/storm_events.json` is only clean once the *fixed* fetch runs. Until that
  refresh lands, `no-replacement-characters` correctly reports one dataset.
* **Session 5 (17 Sep 2026, second working session)**

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

### 0. Finish what this session opened — mostly done, two items left
**Done on the 04:05 UTC run:** the ledger is **41 of 41** with 0 warnings; the
severity counters are in the committed data; the character-loss disclosure works
and `no-replacement-characters` passes.

**The result that came back is the best evidence on the site** — the project's own
count and NOAA's own published expectation agree to within **0.06 days per
season** across all four thresholds NOAA publishes (0.50 in: 8.40 vs 8.39;
1.00 in: 3.20 vs 3.26; 2.00 in: 0.50 vs 0.51; 4.00 in: 0.00 vs 0.02). A second
cross-check landed too: NCEI's Storm Events narrative for 31 Dec 2022 says the
5.46 in that day was "0.08 less than 1st place (11/5/1994) with 5.54", and the
GHCN-derived record independently reports `max_daily_prcp_in = 5.54 in` in
season 1994-1995.

**Still open:**
1. Re-run `bash /tmp/negsmoke.sh`-style falsification against the *refreshed*
   data for `severity-counters-arithmetic` (it now has real per-season values to
   compare, so removing a per-season counter must fail the check) and for
   `threshold-table-recomputable` with the real published probabilities.
2. Decide whether the four-method picture in the bottom line (3.19 expected /
   3.20 counted / 3.26 NOAA-published, all for "days ≥ 1.00 in") is clearer as
   one merged row. It is currently three rows with explicit method labels.
**Effort:** an hour.

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

### 4. ~~Atmospheric-river flag from the NWS Area Forecast Discussion~~ — DONE 18 Sep 2026
**Shipped:** `climo.afd_language_scan()` scans six categories (atmospheric river,
prolonged rain, heavy rain/flooding, strong wind, an explicit rainfall amount,
wind+rain in one sentence) across the fetched discussion, and the site renders the
result as the *Area Forecast Discussion language* card in `#now`. Section-aware
parsing, `MARINE`/`AVIATION`/`FIRE WEATHER` excluded and published as excluded,
preamble not scanned, furniture dropped and counted, bullets split, counts and
lists produced by one matching pass. Ledger checks `afd-language-verbatim` and
`afd-language-quotations-only`; render guard 19; 19 offline unit assertions;
methods in `docs/METHODS.md` §14; scope in `docs/LIMITATIONS.md` §15.

**The one part of the original plan that was deliberately NOT built:** "attach
date-coded mentions to the days they refer to". Doing that would turn a
qualitative statement about a forecast area into a per-day claim for 94122 — the
exact fabrication this project exists to avoid — and no rule could reliably infer
which day a sentence refers to ("Friday into the weekend" spans a tier boundary
that moves). The scanner therefore publishes the sentence, its section and its
matched patterns, and nothing else. If a future session wants dates, it must read
them from NWS's own `validTimes`, never from prose.

**Still open, cheap:** an archive of scanned discussions (`data/afd_history.json`,
one entry per issuance) so the card can say "the last discussion to mention an
atmospheric river was issued on …". That is a *history of what NWS wrote*, not a
forecast, and would make the card useful in January rather than only today.

### 5. A nearer wind record than SFO — ASSESSED 18 Sep 2026, no better source exists
Checked every station the NWS point metadata returns for this coordinate, with
great-circle distances and which elements each feed actually carries:
`SFOC1` San Francisco Downtown 3.67 mi (**no precipitation and no wind in the
feed**), `DW7094` Mill Valley 11.07 mi, `KSFO` 11.88 mi, `MDEC1` Middle Peak
12.75 mi, `OAMC1` Oakland Museum 12.8 mi, `DW3169` Oakland 14.17 mi. Nothing
nearer than the pair already used (GHCN downtown 3.2 mi for rain/temperature,
GSOD SFO 11.9 mi for wind) provides **both** elements from an official archive.

So the honest position stands and is documented rather than papered over: wind is
an upper bound for 94122 (`docs/LIMITATIONS.md` §2), and every wind/gust basis
string says so in the day dialog. **Reopen only if** an official ISD-lite or
MESOWEST station appears inside the Sunset with a multi-decade archive; a ratio
derived from a 3-year overlap would be an estimate dressed as a measurement.

**Still worth doing, different shape:** publish the SFO-vs-downtown *rain* ratio
that the record does support (two long archives, same city) as a labelled
estimate, so a reader can see how much of the SFO wind upper bound is exposure
and how much is distance. That needs ISD hourly (`docs/NEXT_SESSION.md` item 1).

### 6. Per-field provenance in the day dialog (basis strings DONE, deep links open)
**Done 17 Sep 2026:** humidity, gust and rain amount each publish the basis actually
used (`humidity_basis`, `gust_basis`, `rain_amount_basis`) and the dialog shows it.
**Done 18 Sep 2026:** temperature, wind and rain chance now carry a per-field basis
on **both** tiers, so all 123 scoreboard days and all current-forecast days name the
station, the variable, the season count and the unit conversion behind every one of
the six headline fields. At HEAD, `temp_basis`, `wind_basis` and `gust_basis` were
empty on all 123 climatology days while the days published values — that was bug 43.
Enforced by ledger check `day-field-basis-complete` (fails the run) and render
guard 20 (fails the page), both falsified.

**Still open:** none of the six links to the exact *element of the exact file* (e.g.
the `PRCP` column of the `2026-12-14` row of `USW00023272.csv`). Cheap and high
value for manual review: emit a per-field deep link (GHCN CSV row anchor, GSOD
`{station}-{yyyy}.csv` URL, NWS hourly `startTime`) and render it beside the basis.
**Effort:** a couple of hours.

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
