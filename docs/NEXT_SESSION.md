# Next session — handoff

## 1. State at the end of this session (18 Sep 2026 — model-guidance tier, product feed, archive probe, deep links)

**Ledger:** 65 checks, 19 claims — 64 pass, 1 warning by design
(`day-deep-link-shape-verified`: it clears on the first run that fetches NCEI's
Access Data Service, which the sandbox cannot reach; CI can).

**Tests:** `tests/test_parsers.py` 369/369 · `tests/falsify_guards.py` 65 cases ·
`tests/falsify_smoke.py` 29 cases · `npm test` (jsdom smoke) passes ·
`pipeline/verify_sources.py` passes · `pipeline/verify_claims.py` passes ·
five module self-tests 143/143 (`cpc_backtest` 30, `ncei_archive_probe` 25,
`model_guidance` 25, `afd_history` 27, `build_feed` 36).

### What changed in this session

1. **CPC coverage bug found and fixed (the important one).** `parse_season_year`
   understood `OND 2026` but returned nothing for `NDJ 2026-2027`, so the two
   rainy-season outlooks that cross New Year were sampled, published in the season
   table, and attached to **no day at all**. Day attachments after the fix:
   2026-11 120 → 180, 2026-12 62 → 186, 2027-01 62 → 186. A reader opening
   15 December now sees the DJF outlook that covers it. Three new ledger checks
   (`cpc-record-coverage-declared`, `cpc-season-covers-complete`,
   `cpc-record-reach`) recount all 123 days × 38 records every run, and the
   monthly roll-up now walks the season window instead of using a hand-written
   month→year map (the same bug class).
2. **Model-guidance tier (`pipeline/model_guidance.py`, `#model-guidance`).**
   NMME seasonal probability maps archived locally and hashed; NOAA's own
   definitions quoted verbatim; the coverage period read from NOAA's index page
   ("For: October 2026 – April 2027"); the raw archive and NOMADS CFSv2 located
   and **not decoded**. Warning renders before content and on every item; the
   ledger fails the build if any model field or value reaches `calendar.json` or
   `landlord.json` (`model-guidance-isolation`).
3. **Official-product feed (`pipeline/build_feed.py`, `#feed`).** One
   chronological list of everything NOAA published or this project fetched,
   derived only from files already in `data/`. Every row says whether the link it
   offers was itself fetched or is a convenience page verified through the
   machine-readable product behind it (`evidence_url`); date-only and undated
   entries are labelled rather than given a time; model-guidance rows are labelled
   `NOT OFFICIAL` in the same list.
4. **Archive-staleness probe (`pipeline/ncei_archive_probe.py`,
   `#archive-probe`).** Successor search in `isd-history.csv`, year-by-year
   comparison against up to four control stations within ~100 mi (same-airport
   rows excluded), a GHCN-Daily wind-element probe, and NCEI's service-alerts
   page. Verdict is one of `station-specific-gap` / `archive-wide-lag` /
   `not-determinable`, with the measured gap, the 15-day slack, and the action
   that follows. The ledger requires the verdict to match its own evidence and to
   agree with the dates `run.json` publishes.
5. **AFD history (`pipeline/afd_history.py`).** Recent MTR Area Forecast
   Discussions downloaded in full; sentences about rain, wind, duration, storms,
   dry spells and fog quoted verbatim with the product text and its hash stored
   beside them, so the ledger re-checks each quote offline. Prose is never turned
   into a number.
6. **Per-day deep links.** All 123 day cells carry links to the official rows for
   that one date (NCEI Access Data Service station-day, GSOD and hourly ISD annual
   files, NWS product inside the horizon), each labelled *fetched this run* or
   *link only*. `pipeline/main.py` fetches one such request per run so the URL
   shape rests on a recorded response (`climo.ncei_day_link`).
7. **Provenance convention for auxiliary scripts (`pipeline/lib_provenance.py`).**
   Each auxiliary script writes `data/<area>_provenance.json` and merges its
   findings into `data/quality_report.json` under a removable tag, so
   `data/provenance.json` — and the counts `run.json` publishes from it — are
   touched only by the nightly pipeline. `verify_sources.py` now scans **every**
   manifest.
8. **Renderer bug fixed:** thirteen `\\u2014`-style double escapes in `app.js`
   printed the literal text `\u2014` in the NWS-verification and CPC-back-test
   cards. They now render as the characters they were meant to be.

---

## 2. Open work — next session priority order

### 1. Back-fill the CPC archive so the back-test scores real seasons

`pipeline/cpc_backtest.py` exists, is self-tested (30/30) and publishes
`data/cpc_backtest.json`; the site card renders it. What it lacks is **historical
issuances**: `ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/` hosts only
`seasprcp_YYYYMM.zip` / `seastemp_YYYYMM.zip` for roughly the last eight months
(202602–202609 at the time of writing), which is enough for a short recent
back-test and not enough for a hit-rate by lead.

* The IRI Data Library holds issuances back to 1995 but redirects to a **login**,
  so it is not an anonymous official source and was deliberately not added to
  `ALLOWED_HOSTS`.
* Work remaining: find a vetted anonymous archive of past issuances (or accept the
  ~8-month rolling window and say so on the card, which is what it does today);
  then the existing sampling + tercile scoring path produces the rows.
* Do not loosen `cpc-backtest-*` checks to make an empty file look scored.

### 2. Watch the first live run of the new tiers

The five auxiliary scripts have never run outside their self-tests (the sandbox
has no egress to NOAA hosts). On the first CI run check:

```bash
cat data/run_diagnostics.txt        # CPC_BACKTEST_EXIT / NCEI_PROBE_EXIT / MODEL_GUIDANCE_EXIT / AFD_HISTORY_EXIT / FEED_EXIT
python3 -c "import json;print(json.load(open('data/verify.json'))['summary'])"
```

Expected: `day-deep-link-shape-verified` turns from warn to pass; the four
"dataset not published" warnings disappear; `assets/model_guidance/*.png` appear
in the commit. If a module crashes, its dataset is absent, the ledger warns, and
the site shows "Not yet built" — that is designed behaviour, but it should be
fixed rather than left.

### 3. Act on the archive-probe verdict (deliberately not automatic)

If the verdict is `station-specific-gap` and a successor identifier exists, the
probe recommends stitching it into the wind archive but **does not do it**: moving
the wind station would move every published 1991–2020 wind statistic, so it is a
documented maintainer decision. If it is `archive-wide-lag` (the likely answer
while NCEI's cloud-migration delay notice is active), nothing changes except that
the flag now has evidence behind it.

### 4. Multi-ZIP support and a digest

The pipeline is parameterised by coordinate; multi-ZIP is mostly front-end work. A
digest ("a day entered the 7-day window with POP ≥ X", "an alert was issued for
CAZ006") needs an opt-in and a privacy story first.

### 5. Nice-to-haves that are *not* blocked

* Score the NMME probability maps against observations once a season closes —
  CPC already publishes real-time verification, so link to it rather than
  re-implementing it.
* Add the AFD history to the day dialog ("what the office said about this period")
  — quotations only, no dates or amounts attached, same rule as the AFD card.
* Publish the feed as RSS. It is already chronological and every entry carries a
  publisher timestamp, so this is a serialisation task.

---

## 3. How to tell whether the last nightly run was good

```bash
gh run list --branch main --limit 3
gh run watch <run-id> --exit-status
# After it finishes:
cat data/run_diagnostics.txt           # *_EXIT codes, all 0 = good
cat data/verify_report.txt | head -6   # "checks: N passed, M failed"
python3 -c "import json;print(json.load(open('data/verify.json'))['summary'])"
python3 -c "import json;q=json.load(open('data/quality_report.json'));print(q['counts'])"
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
* **Model guidance is never a forecast.** It stays in its own file, section and
  manifest, flagged on the file and on every item, and out of the scoreboard.
* **Never loosen a check to make a run pass.** If a check is wrong, fix the check
  and say so in `docs/VERIFICATION.md`. A guard that cannot be made to fail is a
  bug in the guard: falsify it in `tests/falsify_guards.py` or
  `tests/falsify_smoke.py` before keeping it.
* **Never force-push.** The data workflow appends commits to the same branch; a
  rejected push means `git pull --rebase origin <branch>` first.
* **Quotes are copied, never paraphrased**, decoded with the publisher's own
  encoding first (CPC's NMME description page is CP1252 — decoding it as UTF-8
  with replacement turns its typographic quotes into U+FFFD and the ledger's
  substring check then fails).
* Commercial providers (AccuWeather and similar) stay excluded; the exclusion is
  documented. Any new host must be vetted and added to `ALLOWED_HOSTS` in
  `pipeline/verify_sources.py` deliberately — not with a wildcard suffix.
* Auxiliary scripts write their **own** manifest
  (`data/<area>_provenance.json`) and merge findings into
  `data/quality_report.json` under their own tag. Nothing but
  `pipeline/main.py` writes `data/provenance.json`.

---

## 5. Commands that matter

```bash
# Local rebuild (fetches nothing in the sandbox — run on CI or a networked box)
python3 pipeline/main.py --outdir data
python3 pipeline/build_calendar.py
python3 pipeline/landlord_summary.py
python3 pipeline/cpc_backtest.py
python3 pipeline/ncei_archive_probe.py
python3 pipeline/model_guidance.py
python3 pipeline/afd_history.py
python3 pipeline/build_feed.py          # last: it reads what the others produced
python3 pipeline/verify_sources.py
python3 pipeline/verify_claims.py

# Offline checks (no network, standard library / jsdom only)
python3 tests/test_parsers.py           # 369 assertions
python3 tests/falsify_guards.py         # 65 ledger guards can fail
npm install && npm test                 # jsdom render
python3 tests/falsify_smoke.py          # 29 render guards can fail
for m in cpc_backtest ncei_archive_probe model_guidance afd_history build_feed; do
  python3 pipeline/$m.py --selftest
done
python3 -m http.server 8000             # http://localhost:8000
```

---

## 6. Links for manual review (all official, free, no key)

* Live site — <https://buffedlizard55-lab.github.io/SFWeather/>
* Repo — <https://github.com/buffedlizard55-lab/SFWeather>
* **Official ONI product** — <https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt>
* **ENSO Diagnostic Discussion** — <https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml>
* CPC long-lead discussion — <https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html>
* CPC GIS archive root — <https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/>
* **NMME probability forecasts (model guidance)** — <https://www.cpc.ncep.noaa.gov/products/NMME/probindex.shtml>
* **How to read the NMME maps (verbatim source)** — <https://www.cpc.ncep.noaa.gov/products/NMME/NMME_PROB_descr.html>
* **NMME real-time archive** — <https://ftp.cpc.ncep.noaa.gov/NMME/archive/>
* NWS gridpoint MTR 82,105 — <https://api.weather.gov/gridpoints/MTR/82,105>
* NWS hourly — <https://api.weather.gov/gridpoints/MTR/82,105/forecast/hourly>
* NWS alerts CAZ006 — <https://api.weather.gov/alerts/active?zone=CAZ006>
* NWS AFD — <https://api.weather.gov/products/types/AFD/locations/MTR>
* GHCN-Daily USW00023272 — <https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv>
* **NCEI Access Data Service docs (per-day deep links)** — <https://www.ncei.noaa.gov/support/access-data-service-api-user-documentation>
* GSOD archive — <https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/>
* GSOD README (units) — <https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt>
* **ISD station history (successor search)** — <https://www.ncei.noaa.gov/pub/data/ISD/history/isd-history.csv>
* **NCEI service alerts (archive delays)** — <https://www.ncei.noaa.gov/alerts>
* Storm Events — <https://www.ncdc.noaa.gov/stormevents/>
* Census Gazetteer (ZCTA 94122) — <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip>
* Census reverse geocoder — <https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x=-122.483894&y=37.760459&benchmark=Public_AR_Current&vintage=Current_Current&format=json>
