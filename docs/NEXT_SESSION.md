# Next session — handoff

## 1. State at the end of session 7 (18 Sep 2026 — hour-by-hour wind+rain, fetch accounting)

**Read these first:** `docs/METHODS.md` §18–§20 (the hourly statistic, expected
absences, one-definition rule), `docs/LIMITATIONS.md` (the hourly record),
`docs/VERIFICATION.md` (the pass-7 bug table).

**Ledger:** 53 checks, 19 claims.  On the committed data the only non-pass row is
the `fetch-failures-flagged` **warning** — the four fetches it lists are the
routine 404s that the next pipeline run classifies as `expected_absences`, after
which the row disappears.  Everything else passes.

**Tests:** `tests/test_parsers.py` 336/336 · `tests/falsify_guards.py` 23 cases ·
`tests/falsify_smoke.py` 13 cases · `npm test` (jsdom smoke) passes ·
`pipeline/verify_sources.py` passes.

### What changed in this session

1. **The hour-by-hour wind+rain statistic is published.**  NCEI ISD
   global-hourly (station 72494023234, KSFO) is aggregated into local dates and
   seasons; the landlord card, the bottom line, the action checklist and the wind
   section now lead with *rain and >= 20 kt wind in the same hour* (mean 7.9 days
   a season over 30 seasons, 29.5 simultaneous hours) instead of the whole-day
   pairing (11.1 days).  Both methods are published, each labelled with what it
   measures, and the same-station whole-day row exists to separate the pairing
   effect from the station effect.  The two whole-day constructions agree, so the
   gap is the pairing rule — and the bottom line says so, computed at build time.
2. **Rules attached to the new number:** a season is used only inside the same
   1991–2020 window AND with >= 95 % of the 123 Oct 1 – Jan 31 dates reported;
   excluded seasons are named with their coverage; an absent measurement is never
   a zero (the same-station row says "not published in this run's hourly
   dataset"); hours from multi-hour `AA1` reports are disclosed separately.
3. **`record_coverage` in `run.json`.**  The newest row actually fetched from each
   NCEI archive, its age in days and its URL, plus `stale_archives` for anything
   more than 180 days behind.  This exposed that the GSOD and ISD annual files for
   this station stop at **2025-08-27** while GHCN-Daily is current.  Nothing
   published depends on those months (every statistic is 1991–2020), and the site
   now says so instead of leaving it to be assumed.
4. **Fetch accounting.**  `failed_fetches` no longer absorbs the four routine
   404s; they are published as `expected_absences`, each with a reason the ledger
   re-checks against its own URL, and a real failure is named by URL on the status
   line.
5. **One definition per published quantity (bug 49).**  The same phrase
   "flood-type storm reports" carried 98 in one card and 99 in another.  Fixed,
   and `storm-events-counts-recompute` now re-derives every published Storm Events
   count from the county file.
6. **Docs updated:** README's typical-season table leads with the hourly figure,
   `docs/LANDLORD_GUIDE.md` points at the site card instead of restating numbers,
   `docs/METHODS.md` §18–20 and `docs/LIMITATIONS.md` cover the new statistic and
   its limits.
### Session 7b (18 Sep 2026) — the review passes: degradation honesty and explained failures

Session 7 above already carries the Area Forecast Discussion scan, the Census
reverse geocode and the per-field basis. This branch adds what the three review
passes found *on top of* that work — six defects, three of them in the guards
themselves.

1. **`tests/degrade_smoke.py` (10 cases).** Seven degraded dataset states must
   render honestly: AFD block absent, scan not run, scan found nothing, Census
   lookup absent, Census names all null, Census partial, a scoreboard day all
   null. Plus three cases that break the renderer on purpose, because a
   degradation check that only ever runs against a correct renderer cannot fail.
   Those three immediately found item 2.
2. **The Location card silently deleted a Census row** whenever the Census
   returned no name for it — `kvTable` drops a null value, so a lookup that
   returned only a county rendered as though the subdivision had never been asked
   about. Each row now prints "not reported by the Census for this point".
   Hiding a gap is the opposite of flagging it.
3. **Render guard 24** (Location card honesty): with no geography in the dataset
   the card must say it was not retrieved and must not name a district; with one
   it must print the name, its GEOID, the geocoder link, the `naming_note` and the
   geography types actually returned. Guard 19 now branches on `scanned`, so an
   honest "not scanned this run: <reason>" is not reported as a defect.
4. **Guard 16 was scanning four hard-coded sections** for `NaN`/`undefined` and
   omitted `#now` and `#location` — the two the newest cards live in. It now walks
   every `<section id>`, and rejects a cell whose entire content is a bare
   `null`/`undefined`/`NaN` (the word "null" still appears legitimately inside an
   irregularity message, so the check is on the shape of the leak).
5. **Real fetch failures are explained, not just counted.** Complements the fetch
   accounting above: `expected_absences` are labelled and justified there, and
   `main.flag_failed_fetches()` writes one irregularity per *remaining* failure
   into `quality_report.json`, naming the source and stating that nothing was
   inferred in its place. Ledger check `failed-fetches-explained` (warning) stays
   loud until each is explained. It deliberately skips `expected_absent` entries —
   re-flagging a not-yet-published annual file would only add noise, and noise is
   how a real outage gets ignored.
6. **Three defects in the new guards, all found by running the harnesses:**
   `docs-current-dates-traceable` did not know the scoreboard's own 123 dates, so
   it flagged the season's first day as drift; `failed-fetches-explained` accepted
   a match on a URL's last path segment, and since two NWS observation URLs both
   end in `latest`, one station's explanation silently covered another's failure;
   and the same date check could not tell a date *asserted about the world* from
   one *quoted as a literal*, so documenting the harness's own fixture date read
   as drift. Code spans are now stripped before the scan, matching is on the URL
   or the fetch note only, and the vocabulary includes every published date.

**Standing rule these produced:** a falsification case must assert that its
mutation actually changed something. Two cases silently became no-ops after a data
refresh because the real evidence was already present — a mutation test that
cannot mutate is worse than no test, since it reports confidence it does not have.

**Pass 3** re-checked all eight original requirements against the live dataset and
is recorded as a table at the end of `docs/VERIFICATION.md`, including what it did
not establish (the page is verified structurally, not aesthetically; the AFD scan
proves only that NWS wrote a sentence, never anything about 94122 on a named day).


### Known state to expect on the next run

* The ISD/GSOD archives for this station still end 2025-08-27; the coverage block
  will keep flagging `wind` and `isd_hourly` as stale.  That is correct.
* `data/isd_hourly_summary.json` currently carries 35 seasons; the 1990-91 season
  is partial (only January is inside the window because the annual files start in
  1991) and seasons after 2020-21 are outside the comparison window, so **30** are
  used.  If the CI run changes that count, re-read the exclusion list rather than
  the headline.
* The AFD card stays sparse until the forecast turns wet; that is the scanner
  working.

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

### 0. Finish what this session opened
1. **Watch the first CI run after this branch lands.**  It should produce
   `run.json` with `expected_absences: 4` and `failed_fetches: 0`, at which point
   `fetch-failures-flagged` disappears and the ledger reads 53/53.  If it does
   not, read `data/quality_report.json` before touching the check.
2. **`data/summary.txt`** now carries the hourly line; confirm it appears in the
   next run's digest and that the whole-day line is still labelled as such.
3. **Decide whether the four-method bottom-line picture** (hourly 7.9 /
   same-station whole-day 11.1 / cross-station whole-day 11.1 / heavy 2.2) is
   clearer as one merged row or as the current four.  The agreement sentence makes
   the reason explicit either way.

### 1. ~~Hourly ISD wind → hour-by-hour simultaneous wind and rain~~ — DONE 18 Sep 2026
The hourly statistic is published and is the headline for the landlord's "wind and
rain at the same time" question (`docs/METHODS.md` §18).  What is still open is
**why the station's ISD/GSOD record ends 2025-08-27**: either NCEI stopped
archiving it or the identifier changed.  Chase that next (the GSOD README, the
station's `isd-history.csv` row, and whether a successor identifier exists); if a
successor does, the pipeline can stitch it on and the wind record becomes current
again.  Everything published keeps working either way.

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
empty on all 123 climatology days while the days published values — that was bug 55.
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
* ISD hourly archive (the hour-by-hour wind+rain source since session 8) — <https://www.ncei.noaa.gov/data/global-hourly/access/>
* Storm Events — <https://www.ncdc.noaa.gov/stormevents/>
