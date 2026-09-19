# Limitations, and what to build next

This file is deliberately blunt. Everything here is a real limit of the current
build; nothing is softened, and each item says what it would take to fix.

## Limitations that cannot be engineered away

### 1. No daily forecast exists for most of the window
The NWS gridded forecast reaches about 7 days. Every other official product is a
probability for a *period*. Any site that shows a specific temperature or rainfall
for a named day in January 2027 is producing it from a model or a guess — not from
an official forecast. This project refuses to do that, which necessarily makes the
far end of the calendar less "exciting" than a fabricated forecast would be.

**Mitigation:** two clearly separated tiers, a nightly rebuild, automatic promotion
of days into `NWS FORECAST` as they come into range, and — new this session — a
"Today's real forecast" panel that shows the actual NWS window, including when it
falls entirely before 1 October.

### 2. Three stations, none of them in the Sunset
| Quantity | Station | Distance | Note |
| --- | --- | --- | --- |
| Rain, temperature | `USW00023272` San Francisco downtown | ~3.2 mi | closest long daily precipitation record |
| Wind, gusts | `72494023234` KSFO | **11.9 mi SE** | most exposed; an **upper bound** for 94122 |
| Humidity normals | `USW00023234` KSFO hourly normals | 11.9 mi SE | the only hourly normals file available for the city |

The wind/humidity distance is not typed in: it is the great-circle distance from the
94122 centroid to the station coordinates the NWS returns, published as
`climatology.meta.station_distance_mi.wind_ksfo` (it read "~10 miles" in prose until
a line-by-line pass caught the drift — see bug 34 in `docs/VERIFICATION.md`).

San Francisco microclimates are strong: the Sunset can be several degrees cooler and
materially wetter or drier than downtown on the same day. The site names every
station and shows the coordinates.

### 3. GSOD days are UTC days
Per the [NCEI README](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt),
GSOD summarises 0000Z-2359Z ≈ 16:00-16:00 Pacific, while GHCN rain days are local
days. The joint "wind + rain" statistic therefore pairs a local-day rainfall with a
UTC-day wind figure for the same date. **Fix:** hourly ISD (below).

### 4. Humidity on climatology days is a derivation, not an observation
NOAA does not publish a relative-humidity normal. The value shown is computed from
the official 1991-2020 hourly **temperature** and **dew-point** normals with the
Magnus formula, so it inherits both the formula's ~1-2% error and the file's
"normal" smoothness. It is labelled as a derivation everywhere it appears. Where
the hourly-normals file is unavailable, the field is left empty rather than
estimated.

### 5. Small samples
Single-date percentages use 30 seasons. ENSO-stratified samples are 7-12 seasons.
A single extra season moves a single-date percentage by ~3.3 points, and the
standard error of a 30-season count is about **±9 percentage points** near p = 40 %
(sqrt(p(1-p)/30)). These are indicative, not precise.

This has a visible consequence now that NOAA's own published per-date normals are
shown beside this project's count: the two agree on average (mean difference under
half a point over the 123 dates of this window, and under a degree on the
temperature normals) but **25 of 123 dates differ by more than 10 points**, and one
differs by 21. That is the sampling noise of a 30-season count plus NOAA's smoothing
across dates, not a defect on either side — but a reader who wants a single best
number for a date should prefer NOAA's published value, and a reader who wants to
reproduce the arithmetic should use this project's count. The page states both and
never averages them.

### 5b. Some published normals are legitimately absent
NOAA cannot compute a wet-day precipitation percentile for a calendar date with too
few wet days in the 1991-2020 record, and writes its missing-value sentinel `-9999`
in that cell instead (229 of 366 dates carry a real percentile; 110 of the 123
scoreboard dates do). The site drops the sentinel and shows the row blank, with a
line in the day dialog saying the date is normally too dry for NOAA to publish one.
An earlier build published `-9999.00 in` as if it were a reading — bug 37.

### 6. CPC outlooks are regional, and coastal point-sampling can miss
CPC's prose describes broad regions ("the southern half of California"), which is
not a statement about 94122. The site reports the polygon that actually contains
the ZIP centroid, publishes the polygon index and bounding box, and flags any case
where the point fell between polygons and the nearest one had to be used.

### 7. Storm Events is a reported-events database
It contains what somebody reported to an NWS office. Quiet but damaging events can
be missing. It is not a census.

### 8. "Expected days per season" is an expectation, not a forecast
The landlord cost-driver block publishes *expected counts* (e.g. ~15.0 days ≥ 0.25 in
and ~3.2 days ≥ 1.00 in per season) computed as sums of each calendar date's
1991-2020 observed probability across the 123-day window. That is a linear
expectation over the observed distribution — a budgeting baseline — and it says
nothing certain about 2026-27. Aggregation smooths out year-to-year bunching
(atmospheric rivers arrive in clusters), which is exactly the structure the wet-spell
streak statistics carry. The method is published next to the numbers on the site and
re-derived by the claim ledger on every run.

### 9. Storm Events damage figures are near-token entries
For San Francisco County the NCEI Storm Events files mostly record `0.00K` damage,
and the few non-zero flood entries are `0.01K` ($10) placeholders. The site therefore
reports **event counts**, and how many reports carry any damage figure at all — never
a dollar total — because the totals as recorded would misstate real losses.

### 10. No bias correction, downscaling or post-processing
Numbers are used exactly as published. A research-grade product would calibrate CPC
probabilities against local observations and downscale the NWS grid to the
neighbourhood.

### 11. AccuWeather and other commercial providers are excluded
They require a paid key, their terms do not allow redistribution, and their output
cannot be verified line by line against a public endpoint. `verify_sources.py`
fails the build on any non-official host, so this cannot drift by accident. If you
want a commercial second opinion you must read it at the source.

### 12. Forecast gusts and rain amounts carry one allocation step
The `/forecast/hourly` product returns **no `windGust` and no QPF** for grid
`MTR 82,105` — the pipeline counts the null periods on every run and reports the
count in `data/quality_report.json` rather than quoting a snapshot here — so those
two fields come from the raw gridpoint series at the same point.

* **Gusts** are an instantaneous value, so the daily figure is simply the maximum
  over the hours falling in that local day, converted km/h → mph. No modelling.
* **QPF is an accumulation over a 3–6 hour interval**, not a rate. Where an
  interval crosses local midnight, the published total is split between the two
  days **in proportion to the hours each receives**. That split is the only
  derivation in this path; it conserves the official total exactly (asserted in
  `tests/test_parsers.py`), and every day publishes a `rain_amount_basis` naming
  what was used.
* A day with **no** QPF value shows an em dash, never `0.00`. A day showing
  `0.00 in` is one where NWS published a zero accumulation — those are different
  statements and the site keeps them different.

Cross-check available by hand: NWS's own text forecast for this run says "gusts as
high as 18 mph" for Friday 18 Sep and "20 mph" for Saturday 19 Sep; the derived
daily maxima are 18.4 and 19.6 mph.

### 13. Two official answers can disagree on a single date
Since this session the site publishes NOAA's own per-date daily normals beside this
project's count of the same thing, with the difference shown rather than reconciled.
On the 123 dates of this window the means agree to under half a point, but 25 dates
differ by more than 10 points (worst 21.0). A reader must not read the smaller number
as "the truth": NOAA's value is smoothed across dates and is the better single
estimate; this project's is a raw 30-season count with a standard error near ±9
points. Both are official-derived, both are shown, and the arithmetic of the gap is
stated on the page. This is a limit of a 30-year record, not a defect to be fixed by
choosing a winner. See `docs/METHODS.md` §9.

### 14. The two halves of a "rain day" are different things
The calendar's `rain 0.01"` on an NWS-forecast day is a **predicted accumulation for
that day**. On a climatology day the same slot says `mean 0.01"` and is the
**1991-2020 average total for that calendar date over 30 seasons** — a much weaker
statement. The tile wording, the day dialog and the legend all keep the two apart,
and the smoke test refuses a climatology tile that uses the word "rain" (bug 39).
Readers comparing a September-looking tile with a January one should know they are
reading two different quantities.

### 15. The Area Forecast Discussion is written for a whole forecast area, not for 94122
The AFD scan quotes NWS forecasters verbatim, but the discussion covers the entire
MTR forecast area — the Bay Area, the Central Coast, the Delta, the Sierra
foothills and the coastal waters. A sentence like "strongest winds for the inland
valleys and gaps/passes" is true *somewhere in that area* and says nothing about
one ZIP code in the Sunset.

* The card publishes a `scope_caveat` to that effect, and the site renders it
  with the quotations rather than below them.
* `MARINE`, `AVIATION` and `FIRE WEATHER` sections are excluded from the scan
  (open-ocean and airport conditions are not a landlord's roof), and the
  exclusion is published with its reason.
* The scan publishes **no numbers**: no date, no rainfall amount, no probability.
  A quoted amount stays inside quotation marks with its own words ("rainfall
  totals of 3 inches possible along the coast range"), and the ledger fails the
  run if a date or an amount is attached to any quotation.
* Nothing in the scan promotes a day's tier. Days inside the official horizon
  keep their NWS values; days outside it stay climatology.
* The scan reflects the most recent discussion at the time of the run — usually
  issued within the last 24 hours — and is re-run nightly. It is not an archive
  of discussions.

### 16. "Sunset District" is a Census name, not a city neighbourhood boundary
The forecast point is called the Sunset District because the Census geographer
places the published 94122 centroid inside the county subdivision **Sunset CCD**
(GEOID `0607593267`). That is an official statistical boundary, and it is the
evidence the site publishes.

What it is **not**: a city-defined neighbourhood boundary. The City and County of
San Francisco publishes analysis neighbourhoods (Inner Sunset, Outer Sunset,
Parkside, …) whose edges differ from the Census subdivision, and the ZIP 94122
itself spans more than one of them. So the site does not claim to cover "Outer
Sunset" as a municipal unit; it covers the ZCTA centroid and names the geography
the Census reports. If the geocoder is unreachable on a run, no name is printed —
the card says the geography was not retrieved and the irregularity is recorded.

### 17. Model guidance is archived, not interpreted
The NMME tier gives a reader NOAA's own ensemble maps and NOAA's own explanation of
what the contours mean. It deliberately stops there:

* **No value is read out of an image.** Transcribing "41 % above" from a pixel would
  be a number this project cannot trace to a fetched field, so it does not exist here.
* **No GRIB2 or netCDF is decoded.** Decoding the raw archive would need a
  third-party library this project does not take (the pipeline is standard library
  only, so any reviewer can run it), and a decoded field re-gridded to one ZIP code
  would be a *new forecast* — one that could not be checked against a published
  official product, which is the standard everything else on the site meets. The
  archive's location, its newest run and CPC's own coverage label are recorded
  instead, with `decoded: false` on every probe.
* **No ensemble is converted into a probability for 94122.** NMME grids are
  continental; the polygons CPC publishes for the official outlook are already
  sampled point-in-polygon, with their geometry published. Doing the same to raw
  model output would produce a number with no official product to compare it to.
* **Skill is linked, not summarised.** NOAA publishes RPSS maps and real-time
  verification for these ensembles; the site links them next to the maps rather than
  restating a skill score in this project's own words.

If a future session wants model numbers on the page, the honest route is to quote a
value NOAA itself publishes in text or a machine-readable field — not to read one
off a picture.

### 18. The discussion history covers what NWS currently publishes
`pipeline/afd_history.py` reads the NWS products API, which lists the office's
recent issuances (typically a few weeks). There is no anonymous official archive of
older discussions, so the history is a window, not a record: it cannot answer "when
was the last atmospheric river mentioned in November 2024?". The window is stated
on the page. Quotations are verbatim, stored with the product text and its SHA-256
so the ledger can re-check them offline, and — as with the AFD card — no date,
amount or probability is ever attached to one.

### 19. Per-day deep links are offered for dates this run did not fetch
Each day cell links the official rows for that one date. For the 123 days of the
season those URLs were **not** individually fetched (that would be 369 requests a
night for links, not for data), so each is labelled *link only* rather than
presented as evidence. What *is* verified every run: the URL shape — one Access
Data Service request for a date the station file actually holds, recorded in
`data/ghcn_probe.json` — plus every link's host, station and date
(`day-deep-links-vetted`). Note also that NCEI publishes GSOD and hourly ISD annual
files after the year ends, so a link into the current year may legitimately 404
until it exists; the note on each link says so.

### 20. The archive probe answers one question, and only about one station
`pipeline/ncei_archive_probe.py` classifies why the wind archive stops where it
does. It does not repair the archive, and its verdict is only as good as the
comparison it can make: if no control station's file is readable for a year, the
verdict is `not-determinable` rather than a guess. Control stations are within
~100 mi of SFO and are not microclimate equivalents — they are used to answer "did
the archive stop for everyone?", never to substitute wind values for 94122. If a
successor identifier exists, the probe recommends stitching it and does not do it:
changing the wind station would move every published 1991–2020 wind statistic, so
that is a documented maintainer decision, not a side effect of a nightly run.

---

## Recommended next work, in priority order

### High value, moderate effort

1. **Hourly ISD wind → true simultaneous wind+rain.** Replaces the day-level
   approximation in limitation 3 with hour-by-hour overlap. Source: NOAA Integrated
   Surface Database hourly (`https://www.ncei.noaa.gov/data/global-hourly/access/{year}/{station}.csv`),
   free, no key. Cost: 30+ files of tens of MB each, so it should be its own job
   with its own timeout, publishing only aggregates (never the raw hours).

2. **NWS forecast verification loop.** Store each night's forecast for the 94122
   grid and score it against what was observed, then publish hit rates: did it rain
   when POP ≥ 50%? How far off was the forecast high? This turns the site from a
   viewer into an accountability tool, and the data is already being fetched.

3. **CPC back-testing.** Accumulate each issuance (a small history file) and, once
   the season completes, score CPC's period probabilities against the observed
   GHCN totals for 94122. Then the site can say "when CPC tipped above-median for
   OND here, it verified X% of the time" instead of only reporting the tip.

4. **Atmospheric-river awareness.** ARs drive almost all high-impact California
   winter rain and are directly relevant to the "days of straight rain" question.
   The Area Forecast Discussion is already fetched verbatim; extracting AR language
   (and later, the CW3E/NOAA AR scale references) adds signal cheaply. Keep it as a
   clearly-labelled flag, never a number.

### Moderate value, low effort

5. **A nearer wind source.** `SFOC1` (NWS station on the Bay) reports wind; a
   documented ratio between it and KSFO, computed only over overlapping periods,
   would tighten the Sunset wind estimate. Any such adjustment must be labelled an
   estimate and published with its method.

6. **Per-field provenance in the day dialog.** Each row currently links to the day's
   sources; pointing each individual number at the exact element of the exact file
   would make the manual check even faster.

7. **Email/RSS digest** when a day enters the 7-day window with a high POP, or when
   an NWS alert is issued for `CAZ006`. Requires opt-in and a privacy story.

### Larger undertakings

8. **Multi-ZIP support.** The pipeline is already parameterised by coordinate; the
   front end would need to fetch dynamically instead of reading static JSON.

9. **CFSv2 / NMME ensemble sampling.** Genuine model view of Oct-Jan, but requires
   GRIB2 decoding, heavy storage, and very prominent caveats: raw single-member
   output at 2-6 month leads has little skill for a specific day and is **not** an
   official forecast. This would be a *separate* tier or a separate page, never
   merged into the scoreboard.

10. **Bias correction and downscaling** of the gridded guidance to the Sunset,
    calibrated against the downtown gauge and validated out-of-sample.

---

## Operational notes

* The nightly job runs at **07:15 UTC (00:15 Pacific)**, after the NWS 00Z cycle and
  after CPC posts its daily 6-10 / 8-14 day outlooks.
* `pipeline/verify_sources.py` fails the build on any non-official host.
* `pipeline/verify_claims.py` re-derives every headline number; **on failure the
  workflow commits diagnostics only**, so the site keeps the last verified data.
* `npm test` renders the whole page headlessly (jsdom) and fails on empty sections,
  a broken day dialog or a broken CSV export. Runs as the `smoke` job of the `Tests`
  workflow.
* `python3 tests/test_parsers.py` runs offline assertions on the parsing, derivation,
  and official-host allow-list code as the `parsers` job of the same workflow, on
  every push that touches `pipeline/**` or `tests/**`.
* The workflow commits data with `[skip ci]` so it cannot trigger itself.
* The site is static; if `data/` is missing it shows an explicit error banner rather
  than rendering blanks.

## Storm-severity counters (added 18 Sep 2026)

* **The severity counters are daily ones.** `severe_wind_and_rain_days` pairs a
  rain total and a gust from the **same GSOD daily row**, which is a UTC day
  (00–24Z, about 16:00–16:00 Pacific). Two events that a tenant experienced as
  simultaneous within one local day can therefore fall on different GSOD dates,
  and two that fell either side of a UTC midnight can be counted together. The
  *wind-and-rain* headline no longer depends on this — it is now counted hour by
  hour on local days from the ISD archive (see §"Wind and rain at the same time"
  below) — but these storm-severity counters still do.
* **No named warning category is applied.** "Days with a gust ≥ 40 kt" is not
  "High Wind Warning days". NWS writes those criteria per forecast zone and this
  project deliberately does not restate them, so the counters cannot be read as
  an official severity classification.
* **The wind counters are SFO's.** The rain counters are the downtown gauge
  `USW00023272`; the wind counters are KSFO `72494023234`, 11.9 mi away and more
  exposed. Joint counters therefore mix two stations: an upper bound on wind, a
  downtown rain total.
* **The ≥ 4.00 in row is thin.** One day in 30 seasons. Project 0.00 vs NOAA 0.02
  is a difference of one event in the record, not a disagreement; NOAA's
  per-date values are smoothed across years by construction.
* **The published damage column is unusable as a cost figure.** Every non-zero
  property-damage value NCEI holds for San Francisco County is a token amount
  (12 of 119 records). The site says so on the page instead of quietly omitting
  the column or summing it.



## Wind and rain at the same time — what the hourly method does and does not fix (added 18 Sep 2026)

* **It is still SFO, not the Sunset.** The hourly co-occurrence is measured at
  `72494023234` (KSFO), 11.9 mi away and more exposed than the Sunset, so every
  wind figure here remains an **upper bound** for 94122. What the hourly method
  fixes is *when* the two happened, not *where* they were measured.
* **A wind speed at the observation time is not a gust.** The hourly statistic
  uses the sustained wind in the ISD `WND` field. Gusts are only published in the
  GSOD daily file, so the "heavy" rows (≥0.50 in and a ≥35 kt gust) remain
  whole-day pairings and are labelled as such.
* **Some ISD precipitation reports cover more than one hour.** Those hours are
  counted as hours with rain *and* disclosed separately
  (`simultaneous_hours_from_multi_hour_reports`); they are not presented as
  hour-by-hour measurements.
* **Three of the 30 seasons used are missing 1–4 of the 123 dates** (2009-10,
  2016-17, 2019-20). The minimum coverage is published with the statistic. The
  1990-91 and 2024-25 seasons, and 2021-22 onwards, are excluded because they are
  outside the 1991–2020 window the daily method uses; the exclusion list is on the
  page.
* **The hourly archive itself is not current.** NCEI's annual GSOD and ISD files
  for this station end well before the run date (the GHCN-Daily file is current).
  Every published statistic is a 1991–2020 statistic and is unaffected, but the
  dates are now published (`run.json` → `record_coverage`) so that nothing here is
  read as a statement about this week — and a stale archive is flagged as an
  irregularity rather than passing silently.
* **The two methods are not interchangeable.** The whole-day figure counts a day
  if rain and wind each occurred somewhere in that day, which is why it is higher.
  It is kept on the page, labelled, and the same-station whole-day row exists to
  show how much of the gap is the pairing rule rather than the station.

## The hourly record, and what it does and does not settle (added 18 Sep 2026 session 8)

* **It is SFO, not the Sunset.** The hour-by-hour coincidence is measured at
  station 72494023234 (KSFO), 11.9 mi away and more exposed.  Every wind figure
  here stays an **upper bound** for 94122 — the hourly method fixes *when*, not
  *where*.
* **A sustained wind at the observation time is not a gust.**  The hourly
  statistic uses the ISD `WND` speed.  Gusts exist only in the GSOD daily file, so
  the "heavy" row (≥ 0.50 in and a gust ≥ 35 kt) is still a whole-day pairing and
  is labelled as one.
* **Some ISD precipitation reports cover more than one hour.**  Those hours are
  counted and disclosed separately; they are not hour-by-hour measurements.
* **Three of the 30 seasons used are missing 1–4 of the 123 dates** (2009-10,
  2016-17, 2019-20); the thinnest coverage is published with the figure.  Seasons
  outside the 1991–2020 window are excluded and named.
* **The station's own hourly record is not current.**  NCEI's ISD and GSOD files
  for this station end well before the run date while GHCN-Daily is current, so
  the site publishes the newest row it actually fetched for each archive, its age
  in days and its URL, and flags anything more than 180 days behind.  Every
  published statistic is a 1991–2020 statistic and is unaffected — the flag exists
  so nothing here is read as a statement about this week.
* **The two methods are not interchangeable.**  The whole-day figure counts a day
  if rain and wind each occurred somewhere in that day.  It is kept, labelled, and
  the same-station row shows how much of the gap is the pairing rule.
* **A missing fetch is published, not hidden.**  Fetches that are supposed to be
  absent (a not-yet-published annual file, a station with no observations product)
  are counted separately from failures and each must name a checkable reason; a
  fetch that was supposed to work and did not is listed by URL on the status line
  and recorded as a ledger warning.
