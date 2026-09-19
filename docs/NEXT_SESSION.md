# Next session — handoff

## 1. State at the end of this session (18 Sep 2026 — Pass 1: CPC back-test pipeline, GSOD/ISD retirement, deep links, AFD history, digest)

**Ledger:** 67 checks, 19 claims — all pass, 0 warnings. Pass 8's 59 plus 8 ported
from the parallel pass 9 (`cpc-record-coverage-declared`, `cpc-season-covers-complete`,
`cpc-record-reach`, `auxiliary-manifests-vetted`, `auxiliary-manifests-separate`,
`model-guidance-isolation`, `feed-traceable`, `feed-provenance`). Two more
(`model-guidance-quotes-verbatim`, `model-guidance-links-fetched`) run only when
`data/model_guidance.json` exists, i.e. after a live CI run.

**Tests:** `tests/test_parsers.py` 409/409 · `tests/falsify_guards.py` 56 cases ·
`tests/falsify_smoke.py` 23 cases · `npm test` (jsdom smoke, guards 1–29) passes ·
`pipeline/verify_sources.py` passes (every manifest) · `pipeline/verify_claims.py`
passes · module self-tests: `model_guidance` 25, `build_feed` 36.

**Pass 9 (parallel session, merged as PR #18):** the model-guidance tier and the
official-product feed were built (pass 8 had left model guidance open), and one
live bug was found in the merged tree — cross-New-Year CPC season labels were
attached to no day at all. See `docs/VERIFICATION.md` Session 9, including the
table recording which implementation won each collision and why.

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

`pipeline/model_guidance.py` (+25 offline self-checks, its own workflow step and
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
official text. **Open:** the tier has never run live, so the first CI run should be
watched (see §2.7).

### 7. Watch the next live CI run of the two new tiers

The first live run happened on 19 Sep 2026 at `3941ac6`: every step exited 0 and
the ledger then **failed the publish** on `model-guidance-links-fetched`, because a
raw-archive probe that could not run published `ok: false` with no `error`. That is
fixed (bug 68 in `docs/VERIFICATION.md`) and covered by six new self-checks, but the
run did not publish, so `data/model_guidance.json` and its archived PNGs are still
unseen. On the next nightly run, check that:

* `MODEL_GUIDANCE_EXIT=0` and `FEED_EXIT=0` appear in `data/run_diagnostics.txt`
  (the publish gate now requires all nine exit codes);
* `assets/model_guidance/*.png` were archived and their hashes match
  `data/model_guidance.json` (the ledger re-hashes them);
* the two dormant checks `model-guidance-quotes-verbatim` and
  `model-guidance-links-fetched` appear in `data/verify.json` and pass — if a
  NOAA page moved, they fail rather than silently dropping;
* `data/feed.json` gains the model-guidance rows labelled `NOT OFFICIAL`, and the
  feed's `provenance_unverified` count stays small and explained;
* if the raw-archive probe is skipped again, the reason it publishes tells you
  whether NOAA was unreachable or whether `ARCHIVE_ROW_RE` no longer matches their
  page — the second needs a code fix, the first needs nothing.

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
