# Methods

How each number on the site is produced. Nothing here is interpolated,
reconstructed or modelled by this project - the pipeline only fetches, converts
units using documented factors, and counts.

## 1. Locating the ZIP code

1. Download the Census Bureau ZCTA Gazetteer.
2. Find the row whose `GEOID` equals `94122`.
3. Use `INTPTLAT` / `INTPTLONG` as the coordinate for every subsequent query.

Gotcha handled: the Gazetteer is tab-delimited with **CRLF** line endings, so the
last header arrives as `INTPTLONG\r`. Headers and values are stripped before
lookup, and the matched column names are recorded in `data/run.json`.

## 2. Inside the NWS forecast horizon

The NWS hourly gridded forecast for grid cell `MTR/82,105` is aggregated into
**local calendar days** (`America/Los_Angeles`, because a "day" for a resident of
94122 means a Pacific-time day, not a UTC day):

| Scoreboard field | Formula |
| --- | --- |
| High | max of hourly `temperature` |
| Low | min of hourly `temperature` |
| Humidity | mean of hourly `relativeHumidity` |
| Max wind | max of hourly `windSpeed` (parsed from strings like `"5 to 11 mph"`, taking the upper bound) |
| Max gust | max of hourly `windGust` |
| Rain chance | max of hourly `probabilityOfPrecipitation` |
| Rain amount | sum of hourly `quantitativePrecipitation`, converted mm -> in |

Days with fewer than 8 covered hours are not treated as forecast days.

## 3. Outside the horizon: climatology

Built from the observed record, **1991-2020**, for the season
1 Oct - 31 Jan (a "season" is Oct of year Y through Jan of year Y+1).

### Per calendar date

Using GHCN-Daily `USW00023272`:

* `normal_high_f` / `normal_low_f` - mean of the 30 observed daily values.
* `p_rain_day_pct` - share of the 30 years with >= 0.01 in.
* `p_rain_ge_025in_pct`, `p_rain_ge_100in_pct` - same, at 0.25 in and 1.00 in.
* `mean_daily_prcp_in` - mean over all 30 years (including dry ones).
* `median_wet_day_prcp_in` - median over wet days only, i.e. "when it rains, how
  much does it usually rain".
* `max_daily_prcp_in`, `wettest_on_record` - the extreme and the year it fell.

Using GSOD `72494023234` (KSFO), on the same calendar dates:

* `normal_mean_wind_mph`, `normal_max_sustained_mph`, `normal_max_gust_mph`.
* `p_gust_ge_25kt_pct`, `p_gust_ge_35kt_pct`, `p_gust_ge_45kt_pct`.
* `p_wind_and_rain_pct` - share of days with precipitation >= 0.01 in **and**
  max sustained wind >= 20 kt.
* `p_heavy_wind_and_rain_pct` - share with >= 0.50 in **and** gust >= 35 kt.

The joint statistics only use days where **both** the precipitation and the wind
value are present; the count of usable years is published alongside each figure.

### Wet streaks

For each season, the Oct 1 - Jan 31 sequence of wet/dry flags is scanned for
maximal runs of consecutive wet days. Reported:

* the distribution of the longest run per season;
* the share of seasons containing at least one run of >= 3, 5, 7 and 10 days;
* the full per-season list (`data/climatology.json`), which the site charts.

### ENSO stratification

Each season is labelled with the phase implied by its Oct-Nov-Dec ONI, and the
Oct-Jan rainfall totals are summarised per phase. Sample sizes are small (a
dozen or so seasons each) and are printed next to the statistics.

## 4. Attaching CPC outlooks

Every shapefile in every CPC archive is point-sampled. Each sample yields a
record containing the forecast date, the valid period, the probability and the
favoured category.

* Short-range records carry explicit `Start_Date` / `End_Date` and are attached
  to the days inside that span.
* Seasonal records carry a `Valid_Seas` string such as `OND 2026`. CPC writes
  three-month seasons in upper case and single months in mixed case, so
  `OND 2026` is expanded to Oct/Nov/Dec 2026 and `Sep 2026` to September 2026.
  Month initials are ambiguous (J, M, A), so a season code is only accepted if
  its three letters can be resolved to three *consecutive* months
  (`DJF` -> 12,1,2; `JJA` -> 6,7,8; `MAM` -> 3,4,5).

Outlooks are attached **as probabilities for the period**. They are never
disaggregated into daily values.

## 5. Unit conventions - verified, not assumed

Both were confirmed against the publishers' own documentation before any number
was used, and both were initially got wrong:

| Dataset | Units (as served) | Conversion applied |
| --- | --- | --- |
| GHCN-Daily CSV | `PRCP` tenths of mm; `TMAX`/`TMIN` tenths of degC | `/10 /25.4` for inches; `/10 * 9/5 + 32` for degF |
| GSOD CSV | `WDSP`/`MXSPD`/`GUST` **knots**; `PRCP` **inches**; `MAX`/`MIN` **degF** | knots -> mph via `x 1.15078`; no other change |

The GSOD convention is documented in the
[official README](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt):
"*WDSP - Mean wind speed for the day in knots to tenths. Missing = 999.9*".
The parenthetical is the reporting **precision**, not a multiplier - a reading
confirmed by the missing-value sentinel being `999.9` rather than `9999`.

## 6. Guardrails in the build

* **Host allow-list.** `pipeline/verify_sources.py` fails the workflow if any
  fetch targeted a host outside the vetted official list.
* **Staleness guard.** Scraped NOAA/CPC pages that never mention the current year
  are discarded rather than quoted.
* **Provenance manifest.** Every request is recorded with URL, HTTP status, byte
  count, SHA-256 and retrieval timestamp.
* **Irregularity log.** Missing data, record-count mismatches, coastal
  point-in-polygon misses and thin samples are written to
  `data/quality_report.json` and shown on the site.
* **No silent fallbacks.** Every fallback (nearest polygon, hard-coded centroid,
  fixed time-zone offset) raises a visible flag.

---

## 7. ENSO (updated 17 September 2026)

The ENSO number on the site is **NOAA's published ONI product**
(`data/indices/oni.ascii.txt`), read directly:

* the file's seasons are written as three **month initials** (DJF, NDJ, …), so the
  parser builds all 12 possible rotations to resolve ambiguous letters (J, M, A);
* the year label follows CPC's convention, verified against the published file:
  `NDJ 2015 = +2.59` covers Nov 2015 – Jan 2016, and `DJF 2016 = +2.50` covers
  Dec 2015 – Feb 2016 (the 2015-16 El Niño peak);
* the value shown is the last row of that file, byte-for-byte, with the file's
  SHA-256 recorded.

The project also computes its own 3-month running mean from the detrended monthly
Niño 3.4 table. That derivation is **published as a cross-check**, not as the
headline: if it disagrees with NOAA's published season for the same three months by
more than 0.15 °C, the run raises an irregularity.

ENSO stratification of the rainfall record uses the official seasons covering each
rainy season — OND of year Y, NDJ of year Y and DJF of year Y+1 — averaged. This
replaced an earlier version that used a single locally derived month.

## 8. Humidity on climatology days

NOAA publishes no relative-humidity normal. The pipeline therefore:

1. downloads the official 1991-2020 **hourly normals** for the city
   (`HLY-TEMP-NORMAL`, `HLY-DEWP-NORMAL`, and the file's own `month`/`day`/`hour`
   columns — matched by exact name, because substring matching also picks up
   `meas_flag_…` and `…-10PCTL` columns);
2. converts °F → °C and computes relative humidity with the Magnus formula
   (`17.625/243.04` constants) for every hour of every calendar date;
3. averages the hours to give one value per calendar date, falling back to the
   monthly mean only if the file has no day column.

The site labels this everywhere as a **derivation from official normals**, names the
station, and leaves the field empty when the file is unavailable. A value is never
estimated or interpolated.

## 9. Two official answers: NOAA's published daily normals vs this project's count

The 1991-2020 U.S. Climate Normals **daily** product
(`https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/USW00023272.csv`)
publishes, for every calendar date at this station, NOAA's own probability that the
date records at least a threshold amount of precipitation. That is the same
quantity section 3 counts from GHCN-Daily, so the two are shown side by side and
the difference is published — never averaged, never reconciled.

**The threshold each column means is read out of the column name, not assumed.**
The `GE###HI` columns encode hundredths of an inch (`GE001HI` = ">= 0.01 in",
`GE600HI` = ">= 6.00 in"); the parser stores the mapping it used in
`layout.thresholds_in` and the page builds its labels from that stored mapping, so
a label and a number cannot drift apart.

Three independent checks established the hundredths reading before anything was
published:

| Derived here | Best-matching column | Mean absolute difference | Against the neighbouring columns |
| --- | --- | --- | --- |
| share of years >= 0.01 in | `GE001HI` | 6.3 points | 11.4 against `GE010HI` |
| share of years >= 0.25 in | `GE025HI` | 3.7 points | 9.2 / 7.5 against the columns either side |
| share of years >= 1.00 in | `GE100HI` | 2.7 points | 6.0 / 3.7 against the columns either side |

The threshold sequence for 01-01 is also monotone and physically consistent
(36.8, 25.3, 16.8, 10.3, 4.3, 0.6, 0.0, 0.0 %), and the published 50th percentile
(0.21 in) is far above 0.025 in, so the 16.8 % column cannot mean ">= 0.025 in".

### Why the two never agree exactly

1. **NOAA smooths across dates.** The published normals are a fitted/smoothed
   product, so a date's value is influenced by its neighbours. This project's
   count is the raw share of 30 seasons, which can only move in steps of
   1/30 = 3.33 points. A few points of difference is therefore expected.
2. **This project counts only 30 seasons.** A probability estimated from 30
   independent seasons carries a standard error of about **±9 percentage points**
   near p = 40 % (sqrt(p(1-p)/30)), and this project's counts can only move in steps
   of 3.33 points. So a single date differing by 10-20 points is inside the noise of
   the sample itself, and the comparison that means something is the *average*: over
   the 123 dates of this window the mean difference is under half a point
   (−0.4, −0.1, +0.1 pp for the three thresholds; −0.6 / −0.3 °F for the
   temperature normals), i.e. no bias.  NOAA's smoothed value is the better single
   estimate; this project's raw count is the one a reader can reproduce line by line.
3. **Published percentiles are conditional on a wet day.** `DLY-PRCP-50PCTL` for
   01-01 is 0.21 in, while an unconditional 50th percentile cannot exceed
   ~0.025 in when only 36.8 % of years are wet. `landlord_summary.py`'s median
   wet-day amount is computed the same conditional way, so the two are
   comparable; the page labels the rows "wet days" for that reason.

A disagreement larger than **10 percentage points** on any date is listed on the
page under "Two official answers"; larger than **15 points** fails the build
(`official-daily-normals-cross-check`).

### What is stored

Only the parsed per-date values and the column layout are committed
(`data/daily_normals.json`), not the ~1 MB CSV. An earlier version of the
pipeline committed the raw text truncated to 200,000 characters, which cut the
file off at 04 June and left the entire Oct-Jan window absent; the parser now
requires all 366 dates and raises an irregularity if any are missing.

## 10. Verification (why a number cannot silently be wrong)

`pipeline/verify_claims.py` runs after the datasets are built and:

* re-derives published aggregates from the same file (means, medians, percentiles,
  streak percentages) and compares;
* compares the project's GHCN-derived monthly rainfall means with NOAA's **published
  monthly normals** for the same station and publishes the difference;
* checks production rules — no `NWS FORECAST` tier outside the official horizon, no
  humidity value presented as an observation, NOAA test messages counted separately
  from real alerts, every source URL traced to a recorded fetch;
* writes `data/verify.json` + `data/verify_report.txt`, and **exits non-zero on any
  failure**.

The workflow treats a non-zero exit as a hard stop: diagnostics are committed, the
datasets are not, so the site keeps the last verified numbers.

## 11. Storm severity: counts at plain thresholds, never a warning category

"Severe" is a word with an official meaning in the United States — NWS issues
Wind Advisories, High Wind Warnings and Flood Warnings against criteria written
per forecast zone. Those criteria are not restated anywhere in this project,
because restating them from a secondary source is exactly how a site ends up
telling a landlord there was a "High Wind Warning day" when there was not.

What the project publishes instead is a set of **counts of days at a plain
numeric threshold**, each one re-derivable from the station file it came from:

| Counter | Threshold | Source file |
| --- | --- | --- |
| `wet_days_ge_050in` | ≥ 0.50 in of liquid precipitation | GHCN-Daily USW00023272 |
| `wet_days_ge_1in` | ≥ 1.00 in | GHCN-Daily USW00023272 |
| `wet_days_ge_2in` | ≥ 2.00 in | GHCN-Daily USW00023272 |
| `wet_days_ge_400in` | ≥ 4.00 in | GHCN-Daily USW00023272 |
| `wind_days_ge_30kt` | daily maximum sustained wind ≥ 30 kt | GSOD 72494023234 (KSFO) |
| `gust_days_ge_40kt` | daily maximum gust ≥ 40 kt | GSOD 72494023234 (KSFO) |
| `gust_days_ge_50kt` | daily maximum gust ≥ 50 kt | GSOD 72494023234 (KSFO) |
| `severe_wind_and_rain_days` | ≥ 1.00 in **and** a gust ≥ 40 kt on the same date | both |

The four precipitation thresholds are not arbitrary: they are exactly the
thresholds NOAA NCEI publishes a percent-of-years value for in the 1991-2020
daily normals (`DLY-PRCP-PCTALL-GE050HI`, `GE100HI`, `GE200HI`, `GE400HI`, plus
`GE001HI`, `GE010HI`, `GE025HI`, `GE600HI`). Putting this project's own count on
the same thresholds is what makes the **two-method table** possible: the site
shows "days per season at ≥ X in, counted from the record" next to "days per
season at ≥ X in, summed from NOAA's own published probabilities" for every
threshold both methods cover. Agreement is evidence; disagreement is published
too, not reconciled away.

`severe_wind_and_rain_days` is the strict joint tier the brief asked for
(simultaneous wind and rain), one step harder than the looser
`heavy_wind_and_rain_days` (≥ 0.50 in and a gust ≥ 35 kt). Both are computed
from **GSOD daily rows**, so "at the same time" means "within the same UTC day
(00–24Z, about 16:00–16:00 local)". That limitation is stated on the page and in
`docs/LIMITATIONS.md` rather than hidden; hourly data would be needed to do
better and is listed as open work.

## 12. The only bridge between the outlook and the cost question

The brief asks what the *forecast* implies for repair and maintenance cost. The
honest answer is limited, and the site keeps the two halves apart:

* **Official outlook** — the current ENSO state and status (CPC ENSO Diagnostic
  Discussion), the CPC long-lead probability for each period covering Oct 2026 –
  Jan 2027, and how many scoreboard days sit inside the real NWS forecast
  horizon. A period probability is never converted into a daily one.
* **Conditional record** (`official_outlook.enso_conditioned_record`) — the
  observed Oct 1 – Jan 31 totals of the seasons in the 1991-2020 record whose
  *published CPC ONI* placed them in the same phase as the current state,
  with the spread (min / median / max) and the other phases shown for contrast.
  It is computed from `enso_stratified_season_total_prcp_in`, which is itself
  derived from the ONI season means, so it is re-derivable end to end.

The card labels this "a conditional average of what happened, not a forecast for
2026-27", and the ledger checks that the sentence is present and that the block
is `None` — never a zero-filled table — when the record has no seasons in that
phase.

## 13. CPC probabilities at the 33.3% baseline

CPC publishes whole percentages. Its three-way long-lead split has a
climatological baseline of exactly 100/3 = 33.3%, so a polygon whose probability
reads 33.0% is **not** a tilt — even when CPC's own `Cat` field says `Above` or
`Below`. Presenting that as "Above median (33%)" would overstate the signal.

The pipeline therefore flags every record whose probability is within 0.5
percentage points of 33.3% while its category is directional, publishes the
flag (`probability_at_climatological_baseline`) plus a plain-language
`baseline_note`, and renders a "at the 33% baseline" badge wherever the record
appears — the landlord CPC table, the main CPC season table and the day dialog.
`cpc_tilt_summary` counts tilted periods separately from baseline periods, so
"3 of 8 periods carry a tilt" cannot silently become "8 of 8".

Two ledger checks police it in both directions: no directional-baseline record
may be unflagged, and nothing may be flagged as a baseline case that is not one.


## 14. Scanning the Area Forecast Discussion for storm language (added 18 Sep 2026)

The brief asks about rain duration, simultaneous wind and rain, and storm
severity. NWS publishes numbers for all of those only inside its ~7-day horizon,
but its forecasters write *qualitative* statements about the coming days in the
Area Forecast Discussion (AFD). That text is official and free, so it is fetched
and scanned — with a hard rule about what the scan may publish.

**The rule: the scan publishes quotations, never numbers.** A discussion that
says "rainfall totals of 3 inches possible along the coast range" is evidence
that NWS wrote that sentence; it is *not* evidence of 3.00 in at 94122. So the
scanner emits the sentence verbatim, the section it came from, and the patterns
it matched. It emits no date, no amount, no probability and no per-day value. Two
ledger checks enforce this from the data side (`afd-language-verbatim`,
`afd-language-quotations-only`) and one render guard enforces it on the page.

How the scan works (`climo.afd_sections`, `climo.afd_sentences`,
`climo.afd_language_scan`):

1. **Sections.** The AFD is split on its own `.HEADER...` markers, keeping the
   text before the first one as `(preamble)` — the AWIPS transmission block
   (`FXUS66 KMTR ...`), which is product furniture, not forecast prose. The body
   stops at the `&&` separator.
2. **Exclusions.** `MARINE`, `AVIATION` and `FIRE WEATHER` are excluded, because
   "gale warning … storm-force gusts to 50 kt across the coastal waters" is a
   statement about the ocean, and quoting it beside a landlord's roof would
   overstate the hazard at the forecast point. Exclusions are published with the
   reason, so a reader can see what was not scanned.
3. **Sentences.** Hard line wraps are rejoined into whole sentences. A hyphen at
   end of line is treated as a wrap, not as part of the word (`Above-\nnormal`
   → `Above-normal`). `KEY MESSAGES` bullets are split into separate statements,
   because merging them would join two unrelated hazards into one quotation.
4. **Furniture filter.** Dropped: URLs, all-caps runs of 6+ characters, a
   forecaster-initials footer, and "Issued at"/"Updated at" lines. The count of
   dropped sentences is published.
5. **Six categories.** `atmospheric_river`, `prolonged_rain`, `heavy_rain`,
   `strong_wind`, `quoted_rainfall_amount`, `wind_and_rain_together` — each with
   a `why_it_matters` sentence tying it to a repair or maintenance cost.
6. **The bare-`AR` gate.** `\bARs?\b` is a legitimate abbreviation, but it is
   also an ordinary English fragment. It is accepted **only** if the same
   discussion spells out "atmospheric river" somewhere. `\bPWAT\b` and `\bIVT\b`
   are matched case-sensitively for the same reason.
7. **Matching once.** A single `_afd_match_sentence()` pass decides both the
   count and the list, so a count can never disagree with the sentences published
   beneath it.

Each published sentence must be a whitespace-collapsed substring of the fetched
text; the ledger re-checks that against `data/nws.json` and fails the run if any
sentence cannot be found. On the current discussion (issued 2026-09-18T14:34Z)
the scan covers 5 sections and 43 sentences, drops 7 furniture sentences, and
finds one `strong_wind` match — no atmospheric-river, prolonged-rain or heavy-rain
language, which in mid-September is the expected result. The card states that
explicitly, along with the fact that finding none is **not** evidence that the
season will be dry.

## 15. Naming the forecast point (Census reverse geocode)

The site says "Sunset District". Since that is a naming claim, it is read from
the Census geographies endpoint at the published centroid rather than asserted.
The response is parsed by *name* (so a re-ordered payload still parses), and the
GEOIDs are required to nest: county `06075` must be a prefix of the county
subdivision, the tract, and the block. The lookup URL and SHA-256 are recorded in
`data/provenance.json` like every other fetch.

If the lookup fails, the pipeline records an irregularity in `quality_report.json`
under area `geography` and the site prints that the geography was "not retrieved
this run" instead of naming a district without evidence — the claim ledger
accepts either outcome and rejects a silent third one (a name with no evidence).

## 16. Wind and rain *at the same time* — two methods, both published (added 18 Sep 2026)

The landlord's question is whether rain and wind arrive together, and the project
used to answer it with a **whole-day pairing**: a day counted when the GHCN
downtown gauge recorded ≥0.01 in and the GSOD SFO daily maximum sustained wind
reached ≥20 kt. That method cannot tell rain in the morning from wind at night,
and its two halves come from two stations 11.9 miles apart. It was, and remains,
an upper bound.

The hour-by-hour answer is now computed from the NCEI **ISD global-hourly**
archive for the same wind station (`72494023234`, KSFO, the same station GSOD is
derived from). An hour counts when **one observation** carries both a usable wind
speed and usable liquid precipitation, with `wind ≥ 20 kt` and `precipitation > 0`
at that observation. A local date (`America/Los_Angeles`) counts when at least one
such hour falls on it. Thresholds, units and the local-day convention are written
into `data/isd_hourly_summary.json` and re-read by the ledger, so the published
method cannot drift from the code that computed it.

Four numbers are published together on the landlord card, each labelled with what
it measures:

| Figure | What it counts | Source |
| --- | --- | --- |
| Days per season with a **simultaneous hour** | hour-by-hour co-occurrence at SFO | ISD hourly |
| Simultaneous hours per season | the hours themselves | ISD hourly |
| Days per season, **same station**, whole-day pairing | a day's rain × that day's wind maximum, both from SFO | ISD hourly (per-date rollup) |
| Days per season, whole-day pairing, **downtown gauge × SFO wind** | the figure this project published first | GHCN-Daily + GSOD |

The same-station whole-day figure exists to separate the two effects: the drop
from it to the simultaneous figure is the co-occurrence effect (days where the two
never overlapped), while the difference between the two whole-day rows is the
station/gauge effect. Neither is "the right answer" — they answer different
questions, so both are on the page.

**Rules attached to this block:**

1. **Seasons are filtered, and the filter is published.** A season enters only if
   the station reported on at least 95% of the 123 Oct 1 – Jan 31 dates, and only
   if it lies inside the same 1991–2020 season-year window the daily statistic
   uses. Excluded seasons are listed with their coverage and the reason.
2. **An absent measurement is never zero.** If the committed hourly summary
   predates the per-date fields the same-station comparison needs, that row reads
   "not published in this run's hourly dataset" and the block says so in `notes`.
   The ledger fails the run if the published value disagrees with the underlying
   per-season arithmetic, if a season is both used and excluded, or if a used
   season sits below the published coverage floor.
3. **Multi-hour accumulations are disclosed.** Some AA1 reports cover more than
   one hour; those counted hours are reported separately rather than being
   described as hour-by-hour measurements.
4. **The whole-day figure is never deleted.** It stays on the card and in the
   bottom line, labelled with its own method, because a reader comparing this
   site with an older note of it should find the older number still there.

## 17. How current each source archive is (added 18 Sep 2026)

`run.json` publishes `record_coverage`: the newest row this project actually
fetched from each NCEI archive (GHCN-Daily for rain and temperature, GSOD for
daily wind, ISD hourly for the same station), the age of that row in days, and
the URL it came from. Any archive more than 180 days behind the run date is
listed in `stale_archives` and recorded as a **warning** irregularity, with the
explanation that every published statistic is a 1991–2020 statistic and does not
depend on the recency — the flag exists so that nothing on the page is read as
describing *current* conditions from a stale file.

This was added because NCEI's annual GSOD and ISD files for this station stop
well before the run date while the GHCN-Daily file is current, and nothing on the
site said so. The archive dates are now re-derived from the datasets by the
ledger (`record-coverage-published`), so a wrong date or age fails the run.

## 18. Wind and rain *at the same time*: what the site now publishes (added 18 Sep 2026 session 8)

The landlord question "does the wind arrive with the rain?" used to be answered
one way: count a day when the downtown gauge recorded rain and SFO's daily
maximum sustained wind reached 20 kt.  That figure (11.1 days a season) cannot
tell rain in the morning from wind at night, and its two halves come from
different stations.  It is still published — **and it is still labelled** — as
the whole-day method.

The site now leads with the hour-by-hour count from the NCEI **ISD global-hourly**
archive for the same wind station (72494023234, KSFO):

| Figure | Definition | Source |
| --- | --- | --- |
| Days a season with a simultaneous hour | a local date with >= 1 observation carrying both `wind >= 20 kt` and liquid precipitation > 0 | ISD hourly |
| Simultaneous hours a season | those hours, counted | ISD hourly |
| Days a season, whole-day, same station | a local date whose rain total > 0 and whose maximum sustained wind >= 20 kt | ISD hourly rollup |
| Days a season, whole-day, downtown gauge x SFO wind | the figure published before | GHCN-Daily + GSOD |

**Why three of the four rows exist.** They separate two effects that the single old
number conflated: the same-station row isolates *pairing* (whole days against the
same hour), and the cross-station row isolates the *gauge* (downtown rain against
SFO rain).  On the 1991-92..2020-21 seasons the two whole-day rows agree, which is
the site's own evidence that the gap to the hourly number is the pairing rule, not
the change of station — and the bottom line says exactly that, computed at build
time rather than typed.

**Rules attached to the hourly statistic.**

1. **A season is used only if it is inside the same season-year window as the
   daily statistic and the station reported on >= 95% of the 123 Oct 1 - Jan 31
   dates** (`HOURLY_SEASON_MIN_COVERAGE_PCT`).  Excluded seasons are listed with
   their coverage and the reason, and the ledger fails the run if a season is both
   used and excluded, or if a used season sits below the published floor.
2. **An absent measurement is never a zero.**  If the committed hourly summary
   predates the per-date wind maximum and precipitation total, the same-station
   row reads "not published in this run's hourly dataset" and a note says so;
   publishing 0.0 would state that wind and rain never share a day at SFO.
3. **Multi-hour accumulations are disclosed.**  ISD `AA1` field 1 is the number of
   hours the reported depth covers.  Hours counted from reports covering more than
   one hour are published separately rather than described as hour-by-hour
   measurements.
4. **The whole-day figure is never removed**, only labelled: a reader comparing an
   older note of it must still find it.

## 19. Failures, expected absences, and why the two numbers are separate (added 18 Sep 2026 session 8)

`run.json` publishes three fetch counts — `successful_fetches`, `failed_fetches`
and `expected_absences` — and the page prints all three.  The split exists because
four of the ~140 fetches in a normal run are *supposed* to 404:

| Case | Rule token | Why it is expected |
| --- | --- | --- |
| NCEI annual file for the current year | `annual-file-not-yet-published` | NCEI publishes an annual file after the year ends |
| A station NWS lists with no `observations/latest` product | `station-without-observations-product` | the provider answers 404 for stations that do not publish it (OAMC1 in this grid cell) |
| A candidate station with no hourly-normals file | `candidate-station-without-the-product` | NCEI publishes hourly normals for some stations only (not `USW00023272`) |

Counting those as failures would hide a real one: an archive that stopped
answering would look like the same routine 404s.  So each absence must name a rule
from the closed set, the ledger re-checks each rule against the fetch's own URL
(`expected-absences-justified`), the three counts are re-derived from the manifest
entry by entry (`fetch-counts-recompute`), and any fetch that was supposed to work
and did not is listed by URL on the page and recorded in the ledger
(`fetch-failures-flagged`, a warning rather than a hard failure so one flaky
request cannot stop the nightly publish).

## 20. One definition per published quantity (added 18 Sep 2026 session 8)

A line-by-line pass over the rendered page found the same phrase, "flood-type
storm reports", carrying **98** in one card and **99** in another, because two
functions each defined the set of event types themselves.  The set now lives once
(`landlord_summary.RAIN_RELATED_EVENT_TYPES` = Flood, Flash Flood, Heavy Rain,
Debris Flow), both cards name the types in the label, and the ledger re-derives
every published Storm Events count from `storm_events.json` and fails the run if
the two cards disagree (`storm-events-counts-recompute`).
