# Next session — handoff

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
