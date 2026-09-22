# Next session — handoff

## 1. State at the end of session 19 (21 Sep 2026 — the near-term window, verbatim; the staging guard)

**Ledger:** 90 checks, 21 claims — 90 pass, 0 fail, 1 standing warning
(`docs-current-dates-traceable` on one September date in bug-history prose;
benign). `tests/test_parsers.py` 501/501. `tests/falsify_guards.py` 115/115.
`tests/falsify_smoke.py` 62/62. `pipeline/repair_maintenance_summary.py
--selftest` 59/59. `pipeline/generator_outputs.py --selftest` 13/13.
`npm test` passes.

**What session 19 changed:**

1. **Near-term window on the repair tier (schema 2 → 3).** The page now
   publishes the *only* official day-by-day forecast that exists — the NWS
   gridpoint window — as a "The next few days" card under the repair hero.
   `pipeline/repair_maintenance_summary.py` publishes a
   `near_term_forecast` block: the verified window copied verbatim from
   `calendar.json`'s `current_forecast` (per day: high/low, humidity,
   rain chance, rain amount, max wind, peak gust, grid hours covered, and
   each field's own basis string), window counts under a published
   plain-threshold rule (rain >= 0.1 in, gust >= 30 mph, "together" = both,
   printed on the page next to the numbers), and one plain summary sentence
   published as a unit. In the 21 Sep 2026 data state: 2026-09-21 through
   2026-09-28, 8 local days, 156 grid hours, 0.0 in, peak gust 19.6 mph
   (2026-09-25). First/last days are partial (the hourly grid starts and
   ends mid-day) and the note is part of the block. If the NWS fetch fails,
   the block is published as *unavailable with a note* — never climatology,
   never model data, never a throw.
   * Verified by: `verify_claims.py` §12m `repair-near-term-traceable`
     (independent recompute of every day, the counts, the sentence, the
     window geometry, the source links, and the printable page — incl. the
     unavailable state and its note), the render contract's `ntf` alias,
     `tests/smoke.js` guard 37, 8 new `tests/falsify_guards.py` cases,
     5 new `tests/falsify_smoke.py` cases, near-term unit tests in
     `tests/test_parsers.py`, and 12 new `selftest_repair_tier.py` checks.
     See `docs/LIMITATIONS.md` §29 for what the block does and does not
     reach (nothing beyond the NWS horizon; the window shifts each
     issuance).
2. **Generator output contract — the staging guard (the defect-84 class,
   closed before the commit instead of after).** New
   `pipeline/generator_outputs.py`: a registry of the twelve pipeline steps
   and every file each writes (31 fixed outputs, 7 optional, 2 globs), plus
   `problems(root, after_stage)`. Enforced three ways: every ledger pass
   (`generator-outputs-declared` — a registered output missing or an
   unregistered file in the output area **fails the build**, so a broken run
   cannot silently shrink to a shorter green check list; verified absent
   state = 80 pass / 1 fail / 2 warnings), the nightly workflow (hard gate
   `GENERATOR_OUTPUTS_EXIT=0` in `STEPS_OK`, and `--after-stage` after
   `git add -A` on the publish branch — missing, stray, or unstaged output
   refuses the publish), and the parsers job on every push. Allowlisted as
   shell/hand-written: `data/README.md`, `pipeline_run.log`.
   * Two CI-only defects were found in the *new* code by its own hermetic
     self-test, not by CI: defect 85 (the nightly shell's `pipeline_run.log`
     is unregistered and would refuse every publish — fixed by the
     allowlist, log still scanned by content checks) and defect 86
     (porcelain off-by-one — index 2 is always the separating space in
     `XY PATH`; a fully-staged nightly state was silently flagged; the
     check now reads index 1, the Y column). `docs/VERIFICATION.md` has the
     full table; `docs/LIMITATIONS.md` §30 has the guard's scope and its
     edges (it covers files the pipeline *writes*, not the whole repo).

**First live exercise of both is the next nightly run** (the sandbox has no
NOAA access; everything above was run offline). When reviewing that run:
the ledger line should read 90 pass / 0 fail / 1 warning, and the commit
step should show `generator output contract: 12 steps, 31 fixed output(s),
7 optional, …` followed by `contract holds` *and* the after-stage
assertion passing after `git add -A`.

**Remaining / Limitations:** see `docs/LIMITATIONS.md` §29–§30. Open items
unchanged plus the new first-live-run check: the NCEI successor archives
(GHCNh/SSODv2 — a maintainer decision that would move every published wind
statistic), the CPC back-test pending its per-issuance backfill from the
Oct-1995 archive index, multi-ZIP support (front-end only; the pipeline is
already coordinate-parameterised), and the first live nightly run of the
staging guard and the near-term block.

## 1. State at the end of session 18 (21 Sep 2026 — repair tier schema v2, render guard 36, tier wired into CI)

**Ledger:** 88 checks, 21 claims — all pass (1 standing warning: `docs-current-dates-traceable`
flags two September dates in bug-history prose that were never forecast-window dates; benign). `tests/test_parsers.py` 485/485.
`tests/falsify_guards.py` 107/107. `pipeline/repair_maintenance_summary.py --selftest` 47/47.

**What session 18 changed:**

1. **Repair & maintenance tier (schema v2).** `pipeline/repair_maintenance_summary.py` rewritten; `data/repair_maintenance_summary.json` (62,284 B) now publishes `schema_version`,
   `generated_utc` (= `landlord.json`'s stamp, never a wall clock), `sources_read`, `currency`
   (`is_current`, `sources_agree`, which inputs carry no build stamp, newest fetched content),
   `scoreboard`, `current_enso`, `official_enso`, `cpc_tilt`, `caveats`, `next_issuances`
   (three NOAA sentences, each with URL + SHA-256), `expected_rain`, `rain_duration`
   (incl. `phase_conditioned`), `wind_rain`, `peak_gusts`, `ocean_wind`, `cost_drivers_ranked`
   (severity = f(rank): 1-3 high, 4-5 medium, 6+ low, rule published), `outer_sunset_profile`,
   `sources` + `sources_list`. Two values are **parsed, not typed**: the SFO-to-centroid distance
   (read from a `landlord.json` sentence) and the gale threshold (read from the dataset key name).
2. **Claim ledger section 12m — nine checks** (`repair-artifact-published` warns when the tier is
   absent, `repair-numbers-traceable`, `repair-severity-and-rank-rule`, `repair-quotes-verbatim`,
   `repair-currency-honest`, `repair-render-contract`, `repair-printable-page-generated`,
   `repair-links-official`, `repair-absence-labelled`) plus the claims `repair-season-total-mean`
   and `repair-wind-rain-hourly`. `repair-render-contract` compares every field the renderer reads
   with the payload and every container it writes with the page — the em-dash defect it exists for.
3. **Render guard 36** in `tests/smoke.js` (hero grid, watch list, drivers, outlook table, sunset
   table, source links, and the "not published" fallback when the payload is absent), with five
   falsification cases in `tests/falsify_smoke.py`. Eleven new ledger falsification cases in
   `tests/falsify_guards.py`.
3b. **Two harness defects fixed.** The falsification case that guards the scoreboard grid
   against model-guidance tokens had become a silent no-op (its `grid.innerHTML` anchor matched
   the repair hero's grid, so it passed on `main` while guarding nothing — main's Tests workflow
   was red for the wrong reason); it now anchors on the calendar renderer. And the repair hero
   used an em dash as prose punctuation while the section uses it to mean "no value published";
   the separator is now `:`, so "renders an em dash" keeps one meaning. Both harnesses run
   locally: this sandbox cannot reach NOAA, but `npm ci` works.
3c. **First live nightly run (23:24 UTC) and defect 84.** The tier ran in the real pipeline and
   published a fresh artifact (stamp = `landlord.json`'s, schema 2, currency current, 6 drivers,
   3/3 watch-list sentences, ledger verdict pass). That run also exposed a staging bug: the
   nightly commit staged `data/` and `assets/` but not the tier's generated copy in `docs/`, so
   the tracked printable page kept the previous stamp. The commit step now stages
   `docs/REPAIR_MAINTENANCE_EXECUTIVE_SUMMARY.md` — the ledger check that caught it
   (byte-equality of the two copies) was right.
4. **Tier wired into CI.** `update-data.yml` now runs the tier after `landlord_summary.py`,
   before the ledger (so a stale artifact can never be committed), and `site-test.yml` runs its
   offline self-test beside the other tier self-tests. The artifact had been a day stale because
   nothing ran it.
5. **Printable page formatting.** The printable md now prints numbers **as published** (no
   re-rounding a 7.37 to 7.4, which would be a value in no dataset) and generates its definition
   sentences and basis text from the datasets' own `definitions` / `record_coverage` blocks. It
   also carries the landlord's six questions — rain amount, rain duration, heavy-rain days, wind,
   wind + rain together, storm severity — answered in the order asked, copied from
   `landlord.json`'s verified bottom line, and the ledger fails if a page drops one of them.
   The station-distance sentence it republishes is now chosen from the dataset's own sentences
   (preferring one with no internal field path), and `repair-numbers-traceable` checks that the
   sentence is one `landlord.json` actually wrote.

**Remaining / Limitations:** see the section below and `docs/LIMITATIONS.md` §28. The open items
are the NCEI successor archives (GHCNh/SSODv2 — a maintainer decision that moves every published
wind statistic), the CPC back-test pending per-issuance backfill, and multi-ZIP support
(front-end work; the pipeline is already coordinate-parameterised).

## 1. State at the end of session 17 (21 Sep 2026 — Repair & Maintenance Cost Impact Executive Summary)

**Ledger:** 81 checks, 19 claims — all pass. `tests/test_parsers.py` 485/485. New artifact: `pipeline/repair_maintenance_summary.py` + `data/repair_maintenance_summary.json` (57K) + printable md copies in `data/` and `docs/`.

**What session 17 changed:**

1. **Repair & Maintenance Cost Impact Executive Summary (top of page).** New pipeline `pipeline/repair_maintenance_summary.py` reads only verified datasets (landlord.json, calendar.json, run.json, cpc.json, enso.json, nws.json) — no invented numbers. Outputs:
   - *(Superseded in session 18 — the published key names are in section 1 above; the tier
     now publishes schema 2 and the ledger re-derives every number.)* `data/repair_maintenance_summary.json` with keys: executive_headline, current_enso (phase_label, oni_c_fmt, strength_quotes verbatim), cpc_tilt (periods_with_a_tilt, highest DJF 40% Above / JFM 50% Above, baseline 33%, OND EC), expected_rain (season_total_mean 12.79in median, oct/nov/dec/jan means), rain_duration (ge_7 53.3% — 81.8% El Niño — longest mean, ge_10), wind_rain (hourly_mean_days 7.9 median max hourly_mean_hours 29.5 whole_day 11.1), peak_gusts (mean 53.8 mph max 70 mph SFO 72494023234 11.9mi), ocean_wind (46026 19.4mi gale_mean), cost_drivers_ranked 6 with severity HIGH rank1-3 MEDIUM 4-5 LOW 6, official_outlook verbatim quotes, sources ledger.
   - `data/repair_maintenance_executive.md` (164 lines) and `docs/REPAIR_MAINTENANCE_EXECUTIVE_SUMMARY.md` printable copy with verification URLs for ghcn_daily, gsod, isd, cpc_gis, cpc_discussion, enso_discussion, oni, nws_api, census, storm_events, ndbc_46026.
2. **UI overhaul for landlord focus.** `assets/css/style.css`: sticky header backdrop-filter blur, enhanced .site-nav primary-nav styling (12.5px 600 weight, transition), hero-executive (left 6px accent border, hero-kicker uppercase badge), hero-grid, hero-stat with severity left-border (high/medium/low/enso), repair-cost-hero dark gradient #0f2f52 to #14497a, repair-driver-compact with rdc-rank white circle, severity-badge high #fdeaea #c0392b / medium #fff8e6 #8a6d00 / low #e3f5ea #0f7b3f, section h2 21px 800 weight with .section-icon, card padding 20px 22px hover shadow-lg, grid-4.
3. **index.html top hero.** New `<section id="repair-executive">` as first content section: hero-executive with headline + hero-grid (ENSO, CPC tilt, expected rain, duration, wind+rain hourly, peak gusts + ocean), repair-cost-hero with ranked drivers compact list, current official forecast card + Outer Sunset profile card. Nav: primary-nav Repair Risk Summary link first.
4. **app.js rendering.** FILES.repair added, `renderRepairExecutive()` renders headline, hero-grid stats, compact drivers with severity badges, official outlook verbatim, Outer Sunset profile. Boot loads repair.json alongside others.
5. **PR #28 merged to main.** Commit `1c27f8d` feat: repair & maintenance executive summary, merged as `4a11f39`.

**Verified:** parser tests 485/485, claim checks 81 passed, no hallucinations, all numbers traceable.

**Remaining / Limitations:**

- The repair summary currently re-uses landlord.json evidence strings; future work could derive cost estimates from external contractor datasets (not official weather, so would need separate tier with clear non-weather disclaimer).
- No dollar figure is computed — only ranked likelihood and physical mechanism — because no official source publishes repair cost vs weather for 94122.
- Ocean wind 46026 still provisional in some seasons; thin-season flagging already in ocean_wind.json.
- CPC back-test still pending-backfill until per-issuance URLs found in llarc.ind.php.
- Multi-ZIP front-end picker still open; pipeline already coordinate-parameterised.

**Priorities for session 18:**

1. Watch first live run with repair tier in nightly workflow (add step to .github/workflows).
2. CPC issuance watches 8 Oct + 15 Oct.
3. Add repair tier to nightly workflow publish gate.
4. Multi-ZIP support, GHCNh/SSODv2 wind stitching, CPC back-test archive.

## 1. State at the end of session 16 (20 Sep 2026 — the ocean-side wind record; NDBC station 46026)

**Ledger:** **76 checks live** in the committed data state, **81** once
`data/ocean_wind.json` is published (19 claims, 0 warnings in both states).
Verified in the sandbox by running the ledger against the committed data and
against a staged fixture build of the buoy dataset in a scratch copy — the
ocean-wind checks are exercised end to end that way, because the sandbox has no
network and the real fetch happens on CI.

**Tests:** `tests/test_parsers.py` **485/485** (486 with the guarded gust
cross-check) · `tests/falsify_guards.py` **96 cases** (11 ocean-wind) ·
`tests/falsify_smoke.py` **51 cases** (7 ocean-wind) · `npm test` passes with the
new card · `pipeline/ocean_wind.py --selftest` **46/46**.

**What session 16 changed:**

1. **A new tier: the ocean-side wind record (NDBC 46026).**  `pipeline/ocean_wind.py`
   + `pipeline/selftest_ocean_wind.py` + `data/ocean_wind.json` (written by the
   nightly run, not committed yet) + `data/ocean_wind_provenance.json`.  Three NDBC
   file eras are parsed by header name, missing-value sentinels are respected, the
   three marine statements are published with the data, and every counter prints the
   number of seasons behind it.
2. **Two bugs found while building it.**  Bug 77: the modern NDBC header names its
   month and its minutes column `MM` alike, and resolving columns by name dropped
   every report's minutes (published "strongest gust at" timestamps were hours
   only).  Bug 78: a season with no data was averaged into the day counters as a
   zero, so a gale record read as "0.07 gust days per season" when the record had
   outages.  Both are fixed with self-tests and ledger rules that fail if they
   return.
3. **The page and the summary carry it, caveated.**  `#ocean-wind-card` in the wind
   section, `renderOceanWind` in `app.js`, a section in `data/executive_summary.md`
   (4b) and an `ocean_wind` block in `landlord.json`, all printing the dataset's own
   caveat character for character.
4. **Gates and workflows.**  `www.ndbc.noaa.gov` added to the source gate's allow-list
   and to the ledger's official-host list; the nightly workflow runs the tier before
   the landlord summary and includes its exit code in the publish gate; `site-test.yml`
   runs its self-test.

**Open at the end of this session:** the first live run of the tier (next nightly),
the mid-October CPC issuances, multi-ZIP support, GHCNh/SSODv2 wind stitching, and
the CPC back-test archive.  See the priorities below.

## Priorities for session 17 (as of 20 Sep 2026, end of session 16)

1. **Watch the first live ocean-wind run.**  Confirm the fetch, the coverage, the
   thin seasons and the ledger's 81 checks on the first nightly that publishes
   `data/ocean_wind.json`; treat any irregularity as work, not as noise.
2. **CPC issuance watches (8 Oct + 15 Oct)** — low effort, time-critical.
3. **Multi-ZIP support.**  (a) ZIP→centroid manifest from the Census Gazetteer fetch,
   (b) per-ZIP tiers in the nightly job, (c) a front-end picker.
4. **Wind successor stitching (GHCNh/SSODv2)** — monitor NOAA/NCEI station listings.
5. **CPC back-test archive** — inspect `llarc.ind.php` raw HTML or POST `llarc.php`.

## 1. State at the end of session 15 (20 Sep 2026 — Outer Sunset 94122 Property & Weather Profile; localized cost drivers; local Storm Events; guard 34)

**Ledger:** **74 checks live**, 19 claims — all pass, 0 warnings. Verified in
the sandbox by running the ledger against the regenerated datasets.

**Tests:** `tests/test_parsers.py` **474/474** (or 475 with the guarded gust
cross-check) · `tests/falsify_guards.py` **85 cases** · `tests/falsify_smoke.py`
**44 cases** · `npm test` (jsdom smoke) passes with the new Outer Sunset
property profile card (guard 34) and day finder enter-key listener.

**What session 15 changed:**

1. **Outer Sunset SF 94122 Property & Weather Profile.** Added a structured
   Outer Sunset profile card (`#landlord-sunset-card`) to `index.html` and the
   dashboard rendering pipeline (`renderSunsetProfile` in `assets/js/app.js`),
   as well as `data/executive_summary.md` and `data/executive_summary.json`.
   Captures neighborhood centroid coordinates (37.760459, -122.483894 at
   41st/42nd Ave, ~0.6 mi from Ocean Beach), direct Pacific oceanfront exposure,
   sandy dune subsoil with shallow water table, 1920s–1950s stucco row-home
   typology (zero-lot-line, flat roofs, parapet caps, internal lightwells,
   and subterranean drive-in garages), and marine salt-air corrosion.
2. **Neighborhood-calibrated cost driver guidance.** Re-anchored the physical
   vulnerability explanations in `pipeline/landlord_summary.py` across all 6
   cost drivers specifically for Outer Sunset building envelopes (wind-driven
   rain soaking west-facing stucco, lightwell drain blockages, street-level sewer
   surcharges at low-lying intersections, and salt spray attacking metal flashings).
3. **Local Storm Events integration.** Parsed the NOAA Storm Events archive for
   events specifically citing the 94122 corridor (e.g. Judah & 30th Ave 6–12 inch
   roadway flooding, Great Highway storm closures) and integrated them directly
   into Driver 2 evidence.
4. **Day Finder keyboard listener.** Added Enter key listener (`keyup`) on
   `#day-find` in `assets/js/app.js` so pressing Enter automatically jumps to
   and highlights the specified date.
5. **Render Guard 34 and Falsification.** Added guard 34 to `tests/smoke.js`
   asserting that `#landlord-sunset-card` is rendered with all 6 categories
   naming Outer Sunset 94122. Added 2 new falsification cases to
   `tests/falsify_smoke.py` (`_osp1`, `_osp2`), bringing the suite to 44 cases.
6. **Parser Test.** Added an offline unit test in `tests/test_parsers.py`
   confirming the Outer Sunset profile is present and intact in both markdown
   and JSON mirrors.

**Watch items for the next session:**

* **8 October 2026** — next ENSO Diagnostic Discussion; the strength card
  requotes from the new text the same run (`LIMITATIONS.md` §20).
* **15 October 2026** — the current fxus05 says it "will be superseded by the
  issuance of the new set next month on Oct 15 2026"; the caveat card's three
  quotes rotate that day.
* **19 Oct – 19 Nov 2026** — the ubuntu-latest migration window; workflows are
  pinned to ubuntu-24.04.

## Priorities for session 16 (as of 20 Sep 2026, end of session 15)

1. **CPC issuance watches (8 Oct + 15 Oct)** — low effort, time-critical.
2. **A wind record nearer the ocean.** SFO is the standard 30-year long-term record,
   but examining coastal sensors (e.g., NDBC/CO-OPS met sensors or coastal ASOS)
   could provide additional insights.
3. **Multi-ZIP support.** (a) ZIP→centroid manifest from the Census Gazetteer fetch,
   (b) per-ZIP tiers in the nightly job, (c) a front-end picker.
4. **Wind successor stitching (GHCNh/SSODv2)** — monitor NOAA/NCEI station listings.
5. **CPC back-test archive** — inspect `llarc.ind.php` raw HTML or POST `llarc.php`.

## 1. State at the end of session 14 (20 Sep 2026 — storm severity conditioned on the ENSO phase; the "upper bound" wording withdrawn; the Congress-vintage hole; live re-verification)

**Ledger:** **74 checks live**, 19 claims — all pass, 0 warnings (session 13's
73 plus `enso-severity-recompute`). Verified in the sandbox by running the
ledger against the regenerated datasets; the next full proof is the CI run
this push triggers.

**Tests:** `tests/test_parsers.py` **473/473** in this data state (one
cross-check is guarded — see PR #24's correction, carried into the README) ·
`tests/falsify_guards.py` **85 cases** · `tests/falsify_smoke.py` **42 cases** ·
`npm test` (jsdom smoke) passes with the new strip cell, the three new ENSO-card
columns and the page-wide wording ban (guard 33).

**What session 14 changed:**

1. **Storm severity asked of *this* ENSO phase** (handoff priority 7, now
   closed). `climo.enso_stratified_severity()` splits ten existing per-season
   counters — days ≥ 0.50/1.00/2.00 in, wettest day, the three wind + rain
   pairings, gust ≥ 40 kt and sustained ≥ 30 kt days, the season-max gust — by
   phase, from the same season rows as the totals and spell tables. Published
   as `calendar.enso_stratified_severity`; `landlord_summary.py` derives a
   full-width strip cell (`official_outlook.enso_conditioned_severity`, phase
   mean · median · max beside the all-season mean · max, every row with
   `(n of the N)`), phase rows and one sentence each on bottom-line answers 3–6
   and cost drivers 2–4; the ENSO season card gained three columns; the
   printable summary gained the table. Ledger check `enso-severity-recompute`
   rebuilds the table from the 30 season rows and checks every derived row's
   n / mean / median / max / label. 6 ledger + 9 render falsification cases,
   19 offline assertions. Finding: El Niño tilts the heavy-rain-day count up
   (3.7 vs 3.2 days ≥ 1.00 in) and the ≥ 40 kt gust-day count (3.2 vs 2.4);
   the joint counters and the season-max gust do not separate the phases at
   n = 11 / 12 / 7. The site says exactly that.
2. **Bug 74 — "SFO is an upper bound for the Sunset" withdrawn.** Written in
   session 1, copied to five documents, `index.html`, the wind card, the
   bottom line and the cost drivers; no source in the project establishes the
   direction (bay-shore airport vs ocean-facing ZIP, no long wind record inside
   94122). One caveat string (`WIND_STATION_CAVEAT`) now states station,
   distance and the gap; guard 33 bans the old sentence page-wide; all docs
   corrected in place (`LIMITATIONS.md` §26).
3. **Bug 75 — the congressional district blanked by a hard-coded Congress
   number.** PR #24's data diff showed the Census geocoder answering
   `120th Congressional Districts` (+ 2026 legislative layers) at 01:23Z and
   `119th` (+ 2024 layers) at 01:38Z for the same `Current_Current` request;
   the parser read the literal `119th` key and published `null` on the first.
   The parser now takes the highest-numbered Congress layer present and
   publishes `congressional_district_layer`; the page prints it; the ledger
   fails a returned layer with no district. **The vintage flip itself is an
   irregularity in the Census service, flagged for review** — expect the layer
   label on the page to alternate until the Bureau settles its vintage.
4. **Live re-verification (~02:00 UTC).** ONI tail, the 10 Sep ENSO discussion
   (status + both strength sentences verbatim, `RONI value).` with no space),
   fxus05 (all three caveats, the Oct-15 supersession line, the CA coastal
   50–60% maximum), NWS gridpoint (14 periods identical to the committed file;
   only period 1's start hour moved), CAZ006 alerts (empty), the GSOD README
   (units and UTC-day statements). NCEI `access/*.csv` again HTTP 500 through
   the fetch tool — recorded as a gap, not retried.
5. **PR #24 superseded.** Its 449/450 count correction is carried into the
   README as 473–474 with the same explanation; the PR itself conflicts with
   `main` and should be closed, not merged.

**Watch items for the next session:**

* **8 October 2026** — next ENSO Diagnostic Discussion; the strength card
  requotes from the new text the same run (`LIMITATIONS.md` §20).
* **15 October 2026** — the current fxus05 says it "will be superseded by the
  issuance of the new set next month on Oct 15 2026"; the caveat card's three
  quotes rotate that day. NOAA's own words: the coastal-CA probabilities "may be
  increased further".
* **First pipeline run after this merge** — confirm `enso-severity-recompute`
  passes on freshly fetched data, that the strip cell renders with `(11 of the
  30)`, and which congressional layer the geocoder answered with (the page now
  prints it).
* **19 Oct – 19 Nov 2026** — the ubuntu-latest migration window; workflows are
  pinned to ubuntu-24.04.

## Priorities for session 15 (as of 20 Sep 2026, end of session 14)

1. **CPC issuance watches (8 Oct + 15 Oct)** — low effort, time-critical.
2. **Confirm the post-merge live run** passes `enso-severity-recompute` and
   `census-geographies-traceable` on freshly fetched data, and close PR #24.
3. **A wind record nearer the ocean.** Bug 74 leaves the Sunset's wind exposure
   genuinely unknown to this project. Candidates, all official: NDBC/CO-OPS
   coastal stations (e.g. the San Francisco tide station's met sensor at
   `tidesandcurrents.noaa.gov`, a new host that would need a deliberate
   `ALLOWED_HOSTS` entry), the GHCNh hourly successor, or a NWS/ASOS station on
   the ocean side. Any addition must publish its own coverage and distance and
   must not silently move the 1991–2020 SFO statistics.
4. **Multi-ZIP support.** (a) ZIP→centroid manifest from the Census Gazetteer
   fetch, (b) per-ZIP tiers in the nightly job, (c) a front-end picker.
5. **Wind successor stitching (GHCNh/SSODv2)** — a maintainer decision; probes
   keep recording coverage.
6. **CPC back-test archive** — inspect `llarc.ind.php` raw HTML or POST
   `llarc.php` with candidate parameters.
7. **The two PR-15 follow-ups**: explicit "not returned" rows for individual
   Census geography fields (bug 75 makes this more useful — the
   `geography_types_returned` list already shows what came back), and a
   `failed-fetches-explained` ledger check.
8. **Deliberate ubuntu-26.04 migration** after the window opens.

## 1. State at the end of session 13 (20 Sep 2026 — verbatim-quote fidelity fix; rain duration conditioned on the ENSO phase; live re-verification)

**Ledger:** **73 checks live**, 19 claims — all pass, 0 warnings (session 12's
72 plus `enso-streaks-recompute`). Verified in the sandbox by running the ledger
against the regenerated datasets; the next full proof is the CI run this push
triggers.

**Tests:** `tests/test_parsers.py` **450/450** · `tests/falsify_guards.py`
**77 cases** · `tests/falsify_smoke.py` **33 cases** · `npm test` (jsdom smoke)
passes with the new ENSO column present.

**What session 13 changed:**

1. **Bug 73 — a "verbatim" quotation carried a space NOAA never wrote.**
   `html_to_text()` replaced *every* tag with a space, so an inline hyperlink
   inside the ENSO strength sentence produced `… RONI value ).` where CPC
   publishes `… RONI value).` (the same sentence is plain text in CPC's own
   fxus05 product, which is how it was caught). Inline tags are now removed
   without a space, block tags still separate, and six assertions pin the
   behaviour including the `<span>`/`<s>` prefix hazard. The archived text and
   the quotations built from it update on the next live run.
2. **Rain duration conditioned on the ENSO phase.** `climo.enso_stratified_streaks()`
   publishes per phase: n, the ≥3/5/7/10-day spell counts and percentages, and the
   longest-spell distribution — computed from the same season rows as the existing
   phase table. El Niño: **81.8% (9 of 11)** of seasons had a 7+ day wet spell
   against 53.3% of all 30, 33.3% of La Niña and 42.9% of neutral. It appears in
   the bottom-line answer 2 (with `n` and a confidence line), as cost-driver 1
   evidence, as two columns on the season card, and in both places in the
   printable summary. Ledger check + 4 falsification cases + 2 render guards +
   5 offline assertions, all falsified before being kept.
3. **Live re-verification (~01:00 UTC).** ONI tail (`JJA 2026 +1.80`), the
   10 Sep 2026 ENSO discussion (status + both strength sentences, verbatim),
   fxus05 (issuance line, all three caveats, the Oct-15 supersession line),
   the NWS gridpoint forecast (`updateTime` and `elevation` exact), the hourly
   product (156 periods to 2026-09-26T05:00 local — the committed 8-day window is
   right, and the product's `validTimes` header is *shorter* than the periods it
   publishes) and CAZ006 alerts (empty). Table in `docs/VERIFICATION.md` session 13.
4. **A verification gap, recorded as one.** The sandbox's fetch tool returns
   HTTP 500 on NCEI's `access/*.csv` endpoints, so the GHCN-Daily / GSOD / ISD /
   normals files could not be re-read live in this session; they rest on the
   pipeline's recorded, hashed fetches. Worth a second look from a machine that
   can reach them.

**Watch items for the next session:**

* **8 October 2026** — next ENSO Diagnostic Discussion. Confirm the nightly run
  picks it up; the strength card requotes from the new text the same run. Expect
  its quotes and `not_found` list to rotate — designed behaviour (`LIMITATIONS.md` §20).
* **Mid-late October 2026** — next long-lead outlook + prognostic discussion.
  NOAA's own words (quoted on the site): probabilities "may be increased further".
* **19 Oct – 19 Nov 2026** — the ubuntu-latest migration window; the workflows are
  pinned to ubuntu-24.04, so nothing should change.
* **First pipeline run after this merge** — check that the regenerated
  `sources[].text` no longer carries the inline-tag space and that the strength
  quotation reads `… RONI value).`; if CPC's markup turns out to have had
  trailing whitespace inside the anchor, the text will be unchanged and that is
  also a pass (the fix removes *added* whitespace either way).

## Priorities for session 14 (as of 20 Sep 2026, end of session 13)

1. **CPC issuance watches (8 Oct + mid-late Oct)** — low effort, time-critical.
2. **Confirm the post-merge live run** reparses the quotes cleanly (see the watch
   item above) and that `enso-streaks-recompute` passes on freshly fetched data.
3. **Multi-ZIP support.** (a) a ZIP→centroid manifest from the same Census
   Gazetteer fetch, (b) per-ZIP tiers in the nightly job, (c) a front-end picker.
   Opened in session 8, still open.
4. **Wind successor stitching (GHCNh/SSODv2).** The nightly probes keep recording
   coverage; stitching moves every published 1991–2020 wind statistic, so it stays
   a maintainer decision.
5. **CPC back-test archive.** Next attempt: inspect the raw HTML of `llarc.ind.php`
   or POST `llarc.php` with candidate parameter names.
6. **The two PR-15 follow-ups**: explicit "not returned" rows for individual Census
   geography fields, and a `failed-fetches-explained` ledger check.
7. **Extend the phase-conditioned view.** Session 13 stratified *spells* by phase;
   the same treatment for heavy-rain days (≥1 in) and for the wind+rain counters
   would answer the remaining landlord questions "for this El Niño" too — worth
   doing while the sample-size caveat machinery is fresh.
8. **Deliberate ubuntu-26.04 migration** after the window opens.

## 1. State at the end of session 12 (19 Sep 2026 — dry-discussion seed fix; ENSO strength probabilities on the outlook strip)

**Ledger:** **72 checks live**, 19 claims — all pass, 0 warnings (session 11's
71 plus `enso-strength-verbatim`). Verified in the sandbox after every
change; the next full proof is the CI run this push triggers.

**Tests:** `tests/test_parsers.py` **439/439** · `tests/falsify_guards.py`
**73 cases** · `tests/falsify_smoke.py` **31 cases** · `npm test` (jsdom
smoke, guards 1–31) passes.

**What session 12 changed:**

1. **Bug 72 — dry-discussion seed fix.** The September AFD carries no
   quotable storm-language sentence, so five falsification mutations had
   nothing to mutate and passed vacuously. Both harnesses now seed one
   verbatim sentence from the archived AFD text and then mutate it (failing
   loudly on empty discussions was rejected: it would redden CI on every dry
   discussion). See `docs/VERIFICATION.md` session 12.
2. **ENSO strength probabilities on the outlook strip (closes session-11
   priority 6).** `enso_strength_outlook()` extracts CPC's two strength
   sentences from the archived ENSO Diagnostic Discussion and the site quotes
   them verbatim with a no-added-number marker, a source link, and a
   `not_found` line; the printable executive summary carries the same bullet.
   A discussion with no current-year text is refused outright rather than
   quoted as current. Ledger check + render guard + 13 offline assertions,
   all falsified before being kept. A pattern-tail truncation ("(+2." instead
   of the full "+2.5 °C or more" threshold) was caught by the new tests
   before merge and is pinned against.
3. **Live re-verification (~21:55 UTC).** NWS forecast (14 periods), CAZ006
   alerts (0), ONI `JJA 2026 +1.80`, the full ensodisc page including both
   strength sentences, and the fxus05 issuance line / OND wording / third
   caveat / Oct-15 supersession line re-checked against the live official
   pages: exact matches, table in `docs/VERIFICATION.md` session 12.

**Watch items for the next session (one new behaviour added):**

* **8 October 2026** — next ENSO Diagnostic Discussion. Confirm the nightly
  run picks it up; the diagnostic_status/synopsis should change only if CPC
  changes them. The new strength card will requote from the new text the same
  run — expect its quotes and `not_found` list to rotate, which is designed
  behaviour, not a bug (`docs/LIMITATIONS.md` §20).
* **Mid-late October 2026** — next long-lead outlook + prognostic discussion.
  NOAA's own words (quoted on the site): probabilities "may be increased
  further". After that issuance the caveat card's `not_found` list will grow
  as CPC rewrites sentences — designed behaviour, not a bug
  (`docs/LIMITATIONS.md` §19).
* **19 Oct – 19 Nov 2026** — the ubuntu-latest migration window. This repo is
  pinned to ubuntu-24.04, so nothing should change; if a nightly run shows
  OS-related irregularities anyway, that is the first place to look. The
  deliberate migration to ubuntu-26.04 is an open item below.

## Priorities for session 13 (as of 19 Sep 2026, end of session 12)

1. **CPC issuance watches (8 Oct + mid-late Oct)** — low effort, time-critical,
   nothing to code unless a pattern breaks (see watch items above; the 8 Oct
   watch now covers the strength card's requote as well as the status line).
2. **Multi-ZIP support.** The pipeline is parameterised by coordinate; what
   remains is (a) a ZIP→centroid manifest derived from the same Census
   Gazetteer fetch the pipeline already performs (one fetch, all SF ZIPs),
   (b) running the per-point tiers for each selected ZIP in the nightly job,
   (c) a front-end picker. Opened in session 8, still open.
3. **Wind successor stitching (GHCNh/SSODv2).** The nightly probes keep
   recording coverage; stitching moves every published 1991–2020 wind
   statistic, so it stays a maintainer decision.
4. **CPC back-test archive.** Next attempt: inspect the raw HTML of
   `llarc.ind.php` from a real browser (the markdown render strips the form
   field names) or POST `llarc.php` with candidate parameter names; the GIF
   archive is mapped but not sampleable by `lib_shape`.
5. **The two PR-15 follow-ups**: explicit "not returned" rows for individual
   Census geography fields (latent bug-49 path in `kvTable` callers), and a
   `failed-fetches-explained` ledger check (every failed, non-expected-absent
   fetch must carry an explanation that renders).
6. **Deliberate ubuntu-26.04 migration** after the window opens: test both
   workflows on `ubuntu-26.04`, then unpin.

---

## 1. State at the end of session 11 (19 Sep 2026 — stale-PR audit; falsify time bomb #2; printable executive summary; CI migration hardening)

**Ledger:** **71 checks live**, 19 claims — all pass, 0 warnings (session 10's
70 plus `executive-summary-traceable`). Verified in the sandbox after every
change; the next full proof is the CI run this push triggers.

**Tests:** `tests/test_parsers.py` **426/426** · `tests/falsify_guards.py`
**65 cases** · `tests/falsify_smoke.py` **27 cases** · `npm test` (jsdom
smoke, guards 1–30) passes.

**What session 11 changed:**

1. **PR #15 audit & closure.** Session 7's PR had been left open while
   sessions 8–10 merged. Audited line by line: merging would have deleted
   34,911 lines (8 sessions of verified work); the three headline features
   (AFD scan, Census naming, per-field basis) are verifiably in main already.
   Closed with the audit attached. Two of its never-merged commits describe
   gaps that remain live (individual Census geography fields silently dropped
   by `kvTable`; no `failed-fetches-explained` ledger check) — carried below
   as follow-ups, deliberately not rebuilt in the same session that closed
   the PR, so each gets its own tests.
2. **Bug 71 — falsify time bomb #2.** The "README quotes a horizon date"
   case hard-coded 2026-09-29, which became a real CPC 8–14 day end date on
   19 Sep, silently turning the mutation into a no-op pass. The case now
   computes a date provably absent from the ledger's own vocabulary; the
   README-figure case asserts its mutation target exists before replacing.
   See `docs/VERIFICATION.md` session 11.
3. **Printable executive summary.** `pipeline/executive_summary.py` generates
   `data/executive_summary.md`/`.json` from the committed datasets on every
   run (new workflow step, `EXEC_SUMMARY_EXIT=0` in the publish gate); every
   figure and link is copied from the datasets, thresholds derived from the
   dataset's own key names; ledger check + 7 offline assertions + 2
   falsification cases. The dashboard callout and README link it.
4. **CI migration hardening.** Runners pinned `ubuntu-24.04` (ubuntu-latest
   migrates to Ubuntu 26.04 between 19 Oct and 19 Nov 2026 per GitHub's
   2026-09-17 changelog); actions bumped to the lowest node24 majors, read
   from each action.yml at the tag (checkout@v5, setup-node@v5,
   setup-python@v6, upload-artifact@v6).
5. **Live re-verification (~20:40 UTC).** NWS forecast PoPs (13 periods),
   ONI `JJA 2026 +1.80`, ENSO Advisory status + 8 Oct next-issuance date, and
   all three caveat quotes in fxus05 re-checked against the live official
   pages: exact matches, table in `docs/VERIFICATION.md` session 11.
6. **CPC archive probe (bounded).** `llarc.php` is alive and validating input
   ("Bad month entry" responses), per-month GIF outlooks live at
   `products/archives/long_lead/gifs/YYYY/YYYYMMmonth.gif` back to 1997
   (graphics, not sampleable), `data/YYYY/` tree exists (live dir 403). The
   form's parameter names are still unknown → back-test stays
   `pending-backfill`.

**Watch items for the next session (unchanged, now nearer):**

* **8 October 2026** — next ENSO Diagnostic Discussion. Confirm the nightly
  run picks it up; the diagnostic_status/synopsis should change only if CPC
  changes them.
* **Mid-late October 2026** — next long-lead outlook + prognostic discussion.
  NOAA's own words (quoted on the site): probabilities "may be increased
  further". After that issuance the caveat card's `not_found` list will grow
  as CPC rewrites sentences — designed behaviour, not a bug
  (`docs/LIMITATIONS.md` §19).
* **19 Oct – 19 Nov 2026** — the ubuntu-latest migration window. This repo is
  pinned to ubuntu-24.04, so nothing should change; if a nightly run shows
  OS-related irregularities anyway, that is the first place to look. The
  deliberate migration to ubuntu-26.04 is an open item below.

## Priorities for session 12 (as of 19 Sep 2026, end of session 11)

1. **CPC issuance watches (8 Oct + mid-late Oct)** — low effort, time-critical,
   nothing to code unless a pattern breaks (see watch items above).
2. **Multi-ZIP support.** The pipeline is parameterised by coordinate; what
   remains is (a) a ZIP→centroid manifest derived from the same Census
   Gazetteer fetch the pipeline already performs (one fetch, all SF ZIPs),
   (b) running the per-point tiers for each selected ZIP in the nightly job,
   (c) a front-end picker. Opened in session 8, still open.
3. **Wind successor stitching (GHCNh/SSODv2).** The nightly probes keep
   recording coverage; stitching moves every published 1991–2020 wind
   statistic, so it stays a maintainer decision.
4. **CPC back-test archive.** Next attempt: inspect the raw HTML of
   `llarc.ind.php` from a real browser (the markdown render strips the form
   field names) or POST `llarc.php` with candidate parameter names; the GIF
   archive is mapped but not sampleable by `lib_shape`.
5. **The two PR-15 follow-ups**: explicit "not returned" rows for individual
   Census geography fields (latent bug-49 path in `kvTable` callers), and a
   `failed-fetches-explained` ledger check (every failed, non-expected-absent
   fetch must carry an explanation that renders).
6. **Surface the ENSO strength probabilities.** The archived discussion
   already carries CPC's ">90% chance of a very strong event" and "75% chance
   of a historic event (+2.5 °C or more)" sentences in
   `data/enso.json::diagnostic_key_sentences`; promoting them into the outlook
   strip needs a pattern + falsification tests like the caveat quotes.
7. **Deliberate ubuntu-26.04 migration** after the window opens: test both
   workflows on `ubuntu-26.04`, then unpin.

---

## 1. State at the end of session 10 (19 Sep 2026 — review of merged main; bug 70; outlook caveats, verbatim)

**Ledger:** **70 checks live**, 19 claims — all pass, 0 warnings (session 9's 69
plus `prognostic-caveats-verbatim`). Verified twice on 19 Sep: once offline
against the committed dataset, once on the live CI pipeline run that followed
the session's push (run 35462855471, all nine step exits 0, data published).

**Tests:** `tests/test_parsers.py` **419/419** · `tests/falsify_guards.py`
**63 cases** · `tests/falsify_smoke.py` **27 cases** · `npm test` (jsdom smoke,
guards 1–30) passes · `pipeline/verify_sources.py` passes (every manifest) ·
module self-tests: `model_guidance` 53, `build_feed` 36. All of these also ran
green on CI for the session's commit.

**What session 10 changed:**

1. **Bug 70 — a time bomb in the offline suite.** Re-running the suite on the
   merged main found `tests/test_parsers.py` failing 1/409: the gust
   cross-check hard-coded "18 Sep = 18 mph, 19 Sep = 20 mph" from the NWS text
   forecast as it stood on 18 Sep. The nightly refresh moved the window past
   that date, so the next PR would have failed CI for no reason. The check is
   now dynamic — it reads the periods the run actually fetched (see
   `docs/VERIFICATION.md` session 10 for the asymmetric bounds and why).
2. **The outlook's own caveats, verbatim.** Hand-verification of the live CPC
   products (ENSO discussion, ONI file, fxus05 prognostic discussion) showed
   the site published the El Niño tilt without NOAA's own stated caveats —
   the negative PDO that "may dampen the typical impacts of a strong El Niño"
   and the "probabilities may be increased further… mid-late October" note.
   The outlook strip now quotes those sentences verbatim (pattern-located in
   the archived, hashed discussion), with ledger check 70, render guard 30,
   10 offline assertions and 11 falsification cases behind it. See
   `docs/VERIFICATION.md` session 10 and `docs/LIMITATIONS.md` §19.
3. Independent live verification this session (sandbox-side, not CI): ENSO
   Diagnostic Discussion page and `oni.ascii.txt` fetched and compared
   line-by-line against `data/enso.json` — ONI JJA 2026 = +1.80 °C, Advisory
   status, both verbatim quotes: **exact match, no hallucination**. The fxus05
   discussion's precipitation section matches the sampled outlook tilts
   (OND wet signal starts at the southern half of California, so EC at the
   94122 point is correct; DJF/JFM "reaching a maximum of 50-60 percent near
   the coast").

**Watch item for the next session:** the next CPC long-lead issuance is due
**mid-late October 2026** (CPC's own words, quoted on the site). NOAA says the
DJF/JFM probabilities "may be increased further". After that issuance the
caveat card's `not_found` list will grow (the patterns watch for sentences CPC
rewrites monthly) — that is designed behaviour, not a bug; see
`docs/LIMITATIONS.md` §19. The ENSO Diagnostic Discussion is next issued
**8 October 2026**.

**Pass 9 (parallel session, MERGED to main as PR #18 → `2d62c3d`):** the
model-guidance tier and the official-product feed were built (pass 8 had left model
guidance open), and three live-run bugs were found and fixed — cross-New-Year CPC
season labels attached to no day at all (bug 65), a probe publishing `ok: false`
with no `error`, which correctly blocked a publish (bug 68), and every NMME page
fetching HTTP 200 while yielding nothing, because the extraction patterns assumed
one markup shape (bug 69). After the last fix CI archived 10 maps and both probes
resolved. See `docs/VERIFICATION.md` Session 9, including the table recording which
implementation won each collision and why.

**Pass 2 (same session, bug/edge-case review of the diff above):** 10 further
defects found and fixed, all with regression tests — a wrong helper name that
would have crashed the nightly run, a successor rule that reported a buoy,
unmerged back-test provenance, a JFM year-mapping error, a dropped NWS dialog
link, a ledger leniency keyed on one day, a stale-pass hole in the publish
gate, and a wrong GHCNh probe URL. See `docs/VERIFICATION.md` Session 8,
Pass 2 table (bugs 55–64). All suites re-green after the fixes.

### What changed in this session (Pass 1)

1. **CPC back-test pipeline** (`pipeline/cpc_backtest.py`, new workflow step):
   samples each historical August `seasprcp` issuance at the 94122 centroid with
   the same `main._sample_shapefile_archive` → `lib_shape` code path as the live
   outlooks, scores Above/Below against the GHCN-Daily OND/NDJ/DJF/JFM tercile,
   writes `data/cpc_backtest.json`. EC outlooks are unscored by construction.
   When no archive is retrievable it writes `status: pending-backfill` and each
   404 is recorded under the new expected-absence rule
   `historical-archive-not-retained`. **IRI vetting concluded: rejected** (academic
   mirror, HTTP-only, no outlook polygons) — documented in
   `docs/DATA_SOURCES.md` §3 and kept off `ALLOWED_HOSTS`. The card renderer was
   rewritten for the real file schema (it previously expected a shape the writer
   never produced).
2. **GSOD/ISD stop at 2025-08-27 explained**: NCEI retired both archives on
   2025-08-29. Coverage notes and the stale-archive flag now say "retired", and
   each run probes the official successors (GHCNh hourly, SSODv2) into
   `data/isd_history.json` / `data/ghcnh_probe.json`.
3. **Per-field deep links**: every scoreboard day carries `deep_links` (NWS days:
   hourly `startTime` values named in the hint; climatology days: GHCN row,
   GSOD annual-file pattern, hourly-normals rows, published-normals row), rendered
   in the day dialog as "Verify each number yourself". Ledger check `deep-links-traceable` fails
   the run if a day lacks its tier's keys.
4. **AFD issuance history** (`data/afd_history.json`, append-only, deduped,
   capped at 120): the AFD card now shows "the last discussion to mention X was
   …" per category. Quotations only — never attached to a scoreboard day.
5. **Storm-watch digest** (`pipeline/build_digest.py`, new workflow step):
   `data/alerts.xml` (RSS 2.0) + `data/digest.json`, one entry per active CAZ006
   alert and per NWS-window day with POP ≥ 50. Test messages excluded,
   climatology can never trigger. Opt-in only: static files, no addresses stored,
   no email offered (a static project cannot send mail honestly). Rendered in a
   `#digest` card with a subscribe link and the privacy statement.
6. Six new ledger checks cover all of the above (deep links, back-test method,
   AFD history, digest/RSS, model-guidance separation, successor probes). All suites
   green (see §1 counts).

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

### Priorities for session 11 (as of 19 Sep 2026, end of session 10)

1. **Mid-October CPC issuance watch (low effort, time-sensitive).** The next
   long-lead outlook + prognostic discussion lands **mid-late October** and
   the ENSO discussion on **8 October**. After each: confirm the nightly run
   picked them up, check the caveat card's `not_found` behaviour (expect the
   PDO sentences to be rewritten — the card must drop them, not hold them
   over), and see whether the DJF/JFM precipitation probabilities rose as
   NOAA hinted. Nothing to code unless a pattern breaks.
2. **Wind successor stitching (GHCNh)** — see §2.2 below. The pipeline probes
   the successor every night; stitching is a maintainer decision because it
   moves every published 1991–2020 wind statistic.
3. **CPC archive back-fill** — see §2.1. The per-issuance URLs inside the
   official Oct-1995 archive index still need to be located; until then the
   back-test card honestly reports `pending-backfill`.
4. **Multi-ZIP support** — front-end work; the pipeline is already
   parameterised by coordinate.
5. **Ubuntu-latest migration warning**: CI annotations say the
   `ubuntu-latest` label migrates to Ubuntu 26 on **19 October 2026**, and
   actions now warn about Node 20 deprecation. Not breaking today; worth
   pinning or updating `actions/checkout@v4`/`setup-python@v5` when convenient.

### 1. Back-fill the CPC archive to run the back-test for real — pipeline done, archive fetch still open

**Done 18 Sep 2026:** `pipeline/cpc_backtest.py` exists, runs as a workflow step,
samples with the live-outlook code path, scores EC as unscored, writes rows +
hit-rate-by-category/lead, and degrades to `pending-backfill` with per-issuance
attempt records. Ledger check + render guard + offline scoring tests all exist.
**IRI vetting concluded: REJECTED** — do not revisit without new evidence (see
`docs/DATA_SOURCES.md` §3).

**Still open:** the nightly run attempts the August issuances 1995–2020 against
the live GIS server and the `www` mirror, but both usually 404 for old months.
What remains is finding the per-issuance file URLs inside the official Oct-1995
archive (<https://www.cpc.ncep.noaa.gov/products/archives/long_lead/llarc.ind.php> —
currently an index of graphics pages, not direct ZIP links) and teaching the
back-test to follow them. Until then the card honestly reports pending-backfill
with the attempt table.

### 2. Chase why GSOD/ISD for KSFO stop at 2025-08-27 — RESOLVED, successor stitching open

**Resolved 18 Sep 2026:** NCEI retired GSOD and ISD on 2025-08-29; no station-ID
change, no lag. Coverage notes and the stale flag now say "retired", and each
run records `data/isd_history.json` + `data/ghcnh_probe.json`.

**Still open:** stitch the successors once probe coverage is confirmed — GHCNh
hourly for the hour-by-hour wind+rain statistic (post-Aug-2025 hours), SSODv2
for daily wind/gust. Keep GHCNd as the daily precipitation authority. Do not
drop the frozen 1991–2025 ISD/GSOD aggregates: they are the only record for
those years.

### 3. Deep links in the day dialog

Every field already names its basis, but a reader trying to manually verify
temperature on 14 December still has to download the whole GHCN CSV and search.
**Done 18 Sep 2026:** per-field deep links (`deep_links_for_nws_day` /
`deep_links_for_climo_day`) with `startTime`-naming hints, rendered as "Verify
each number yourself" in the day dialog and enforced by ledger check `deep-links-traceable`.

### 4. AFD history archive

Store each scanned Area Forecast Discussion in `data/afd_history.json` so the
AFD card can say "the last discussion to mention an atmospheric river was
issued on …". **Done 18 Sep 2026:** `data/afd_history.json` (append-only,
deduped, capped at 120) with a per-category last-mention table on the card and
ledger check `afd-history-consistent`. Quotations only — never attached to a scoreboard day.

### 5. Multi-ZIP support and a digest

The pipeline is already parameterised by coordinate; multi-ZIP is mostly
front-end work and is still open. **Digest done 18 Sep 2026:** RSS
(`data/alerts.xml`) + JSON (`data/digest.json`) for "a day enters the NWS window
with POP ≥ 50" or "an NWS alert is issued for CAZ006", with an opt-in-only
privacy story (static files, no addresses, no tracking). **Email deliberately
not offered**: it would require storing addresses and running a sender, which
this static project cannot do honestly.

### 6. Model guidance — DONE 18 Sep 2026, as a separate warned tier

`pipeline/model_guidance.py` (+53 offline self-checks, its own workflow step and
its own manifest `data/model_guidance_provenance.json`) archives NOAA's NMME
seasonal probability maps locally with their SHA-256, quotes NOAA's definition
sentences verbatim (the description page is **CP1252** — decode it with the
publisher's encoding or the substring checks break), prints the coverage period
NOAA states on its index page rather than deriving one from a filename, and
records the raw archive / NOMADS locations with `decoded: false`.

What it deliberately does **not** do: read a value out of an image, decode
GRIB2/netCDF, convert an ensemble into a probability for 94122, or restate a skill
score (NOAA's RPSS and verification pages are linked instead). Isolation is
enforced twice — pass 8's `model-guidance-separated` inspects the scoreboard days,
pass 9's `model-guidance-isolation` also audits the guidance file and scans
`calendar.json` / `landlord.json` for model-guidance mentions outside quoted
official text. **No longer open:** the tier has run live three times (see §2.7),
publishing 10 archived maps, 7 verbatim definition sentences and 2 resolved
probes.

### 7. Live CI runs of the two new tiers — DONE, and they found two real bugs

Three live runs happened on 19 Sep 2026. Read this before trusting any tier that
has not been exercised against the publisher's real markup.

| Run | Commit | Outcome |
| --- | --- | --- |
| 1 | `3941ac6` | Every step exited 0; the ledger **refused to publish** on `model-guidance-links-fetched` — a raw-archive probe that could not run published `ok: false` with no `error`. Diagnostics only were committed. Fixed as bug 68 (+6 self-checks) |
| 2 | `7290d32` | Ledger **passed and published** (69 checks, 0 failed, 0 warnings; both dormant checks running for the first time) — but the tier was empty: 7 pages at HTTP 200, `images_archived: 0`, archive probe skipped with "page retrieved but listed no run directories". Fixed as bug 69 (+22 self-checks) |
| 3 | `3f89643` | **Passed and published as `561544d`**: 10 maps archived under `assets/model_guidance/` (30,357–31,998 bytes, each re-hashed by the ledger), `nmme_archive_latest` resolved to `…/NMME/archive/2026080800` at HTTP 200, `probes_ok: 2`, `irregularities: []`, coverage verbatim `October 2026 - April 2027`. Merged to main by PR #18 as `2d62c3d` |

What run 2 teaches, and what to check on any future nightly run:

* `MODEL_GUIDANCE_EXIT=0` and `FEED_EXIT=0` in `data/run_diagnostics.txt` (the
  publish gate requires all nine exit codes);
* `assets/model_guidance/*.png` present and matching the hashes in
  `data/model_guidance.json` (the ledger re-hashes them);
* `counts.images_archived` **non-zero**. A tier can be honest and still be empty:
  run 2 passed every check while archiving nothing. If it drops to 0 again, look at
  `n_links_seen` and `markup_excerpt` on the affected page — those are published
  precisely so a markup change at NOAA is diagnosable from committed data without
  network access;
* the two model-guidance checks appear in `data/verify.json` and pass — if a NOAA
  page moved, they fail rather than silently dropping;
* `data/feed.json` keeps its model-guidance rows labelled `NOT OFFICIAL`, and
  `provenance_unverified` stays small and explained;
* if the raw-archive probe is ever skipped again, the reason it publishes says
  whether NOAA was unreachable (nothing to do) or whether the listing stopped
  matching (a code fix). The stale `ARCHIVE_ROW_RE` name is gone from that message —
  extraction now matches resolved URLs, not markup.

### 8. Still open from earlier passes

Back-filling the CPC archive (§2.1), stitching a successor wind identifier if one
appears (§2.2 — a documented maintainer decision, because it would move every
published 1991–2020 wind statistic), and multi-ZIP support (§2.5).

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
* **Decode with the publisher's encoding.** Some NOAA/CPC pages are CP1252, not
  UTF-8 (`NMME_PROB_descr.html` is). `lib_fetch.decode_text` tries the publisher's
  encoding first and counts any character it still cannot represent; decoding such a
  page as UTF-8-with-replacement turns its typographic quotes into U+FFFD and breaks
  every verbatim-substring check that depends on them.
* **Model guidance never merges into the scoreboard.** It is a separate tier with a
  warning that renders before its content and again on every item, its own dataset
  and its own manifest. Nothing is read out of an image and no GRIB2/netCDF is
  decoded. Two ledger checks enforce the separation from different angles.
* **A date the publisher did not give is never invented.** Date-only means
  `time_known: false` with the publisher's own wording beside it; no date at all
  means the entry is listed undated. A timestamp that will not parse is dropped with
  a warning, not guessed at.
* **Match resolved URLs, not markup.** Anything scraped from a publisher's page is
  extracted by resolving every `href`/`src` against that page's own URL and matching
  the resolved URL — never by assuming a quoting style, an absolute path, or a label
  with no tag inside it. Bug 69 was exactly that assumption, and it cost a whole
  live run: seven pages fetched at HTTP 200 and nothing understood from any of them.
* **An empty result that passes every check is still a failure.** Assert the counts a
  tier exists to produce (`images_archived`, `n_archived_runs_listed`, entries per
  month), not only the exit codes. And when a page is retrieved but parses to
  nothing, publish a bounded `markup_excerpt` plus a warning irregularity — the next
  such failure has to be diagnosable from committed data, because the sandbox that
  finds it may have no route to the publisher at all.
* **Two provenance conventions coexist on purpose** (`docs/METHODS.md` §26): a step
  whose rows must appear in the run's published totals merges back into
  `provenance.json`; a tier meant to be read on its own writes
  `data/<area>_provenance.json`. Either way a fetch is recorded exactly once and
  `verify_sources.py` scans every manifest.

---

## 5. Commands that matter

```bash
# Local rebuild (fetches nothing in the sandbox — run on CI or a networked box)
python3 pipeline/main.py --outdir data
python3 pipeline/build_calendar.py
python3 pipeline/cpc_backtest.py
python3 pipeline/landlord_summary.py
python3 pipeline/build_digest.py
python3 pipeline/model_guidance.py     # NMME tier (needs network; separate manifest)
python3 pipeline/build_feed.py         # derived feed — run last, it reads the rest
python3 pipeline/verify_sources.py     # host gate, every manifest
python3 pipeline/verify_claims.py
python3 tests/test_parsers.py
python3 tests/falsify_guards.py
npm install && npm test
python3 tests/falsify_smoke.py
for m in model_guidance build_feed; do python3 pipeline/$m.py --selftest; done
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
* Storm-watch feed — <https://buffedlizard55-lab.github.io/SFWeather/data/alerts.xml> (+ `data/digest.json`)
* AFD issuance history — <https://buffedlizard55-lab.github.io/SFWeather/data/afd_history.json>
* CPC long-lead archive index (Oct 1995 →) — <https://www.cpc.ncep.noaa.gov/products/archives/long_lead/llarc.ind.php>
* GHCNh station list (ISD successor) — <https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-station-list.csv>
* GHCN-Daily USW00023272 — <https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv>
* GSOD archive — <https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/>
* GSOD README (units) — <https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt>
* Storm Events — <https://www.ncdc.noaa.gov/stormevents/>
* Census Gazetteer (ZCTA 94122) — <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip>
* Census reverse geocoder — <https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x=-122.483894&y=37.760459&benchmark=Public_AR_Current&vintage=Current_Current&format=json>
