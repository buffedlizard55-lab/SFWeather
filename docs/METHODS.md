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
and its two halves come from two stations 11.9 miles apart. It is the looser of
the two methods: it counts every day on which the two ever met plus the days on
which they happened hours apart — but because its rain half comes from the
downtown gauge rather than SFO, it is not a strict superset of the hourly count,
and it says nothing about whether the Sunset is windier or calmer than SFO
(`docs/LIMITATIONS.md` §26).

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

## 21. CPC coverage across New Year (added 18 Sep 2026, pass 9)

CPC writes a season label in two forms: `OND 2026` for a season inside one
calendar year, and `NDJ 2026-2027` for one that crosses New Year. The parser
handled only the first, so the two rainy-season outlooks were sampled from the
official shapefiles, printed in the season table, and then attached to **no day at
all** — a reader opening 15 December never saw the DJF outlook that covers it.

The fix is in `build_calendar.parse_season_year` / `parse_season_key`:

* `2026` → `(2026, None)`; `2026-2027` and `2026/2027` → `(2026, 2027)`;
  non-consecutive years (`2026-2028`) → `(None, None)`;
* a two-year label is only accepted for a season that actually crosses New Year
  (`NDJ`, `DJF`), and a one-year label only for one that does not. A contradiction
  means the label was misread, so nothing is returned rather than a wrong set of
  months being attached to days;
* coverage keys are zero-padded `YYYY-MM` strings, which is the contract the
  ledger's completeness check re-derives.

The monthly roll-up no longer uses a hand-written month→year map either: it walks
`SEASON_START` forward one month at a time, so a season crossing New Year yields
`2026-12` then `2027-01` by construction.

Three ledger checks keep it honest, and each was falsified before being kept
(`tests/falsify_guards.py`): `cpc-record-coverage-declared` (every record declares
coverage exactly one way — month keys, or a start and end date),
`cpc-season-covers-complete` (all 123 days × 38 records recounted: every day
carries exactly the records that cover it, and no record is attached to a day it
does not cover) and `cpc-record-reach` (each month/season record reaches every day
it covers; a record covering nothing in this season reaches no day).

## 22. The model-guidance tier (added 18 Sep 2026, pass 9)

`pipeline/model_guidance.py` retrieves NMME material and publishes
`data/model_guidance.json` plus `data/model_guidance_provenance.json`. The rules
are structural, not stylistic:

1. **The warning is data.** It lives in the file, renders before any content, and
   repeats on every item. The ledger requires the exact phrases, so a rewrite that
   softened it would fail the build.
2. **Nothing is read out of an image.** The seasonal PNGs are archived locally with
   their byte count and SHA-256 (so the picture cannot change under a reader), and
   the ledger re-hashes the file on disk against the recorded hash. No probability,
   amount or wind speed is transcribed, estimated or republished.
3. **No month range is invented.** The period the maps cover is quoted from NOAA's
   index page. A `season N` image's month range is printed inside the image by
   NOAA; the filename is not treated as a date.
4. **Quotes are substrings.** Definition sentences are extracted from the fetched
   page text and re-checked — in the module, in its self-test, and again by the
   ledger against the full page text stored beside them. The page is CP1252, so it
   is decoded with `lib_fetch.decode_text` (publisher encoding first) and any
   character that still cannot be represented is counted and reported rather than
   published as U+FFFD.
5. **Raw model output is located, not decoded.** The NMME archive directory and
   NOMADS CFSv2 are probed for availability; each probe records `decoded: false`
   and the reason. A location that does not answer is reported as not reachable and
   is not published as a working link.
6. **Isolation is enforced, not promised.** `model-guidance-isolation` fails the
   run if `merged_into_scoreboard` is not false, if `not_an_official_forecast` is
   not true, if the warning loses its wording, if any day cell or dataset grows a
   model-shaped field, or if a model-guidance mention appears anywhere in
   `calendar.json` / `landlord.json` **outside a quoted official document** — the
   last clause matters because CPC's own prognostic discussion says the official
   outlook was made using NMME and CFSv2, and this project quotes that discussion
   verbatim. A token scan would have flagged NOAA's own words as contamination.

## 23. The official-product feed (added 18 Sep 2026, pass 9)

`pipeline/build_feed.py` makes no network request. It reads the datasets already in
`data/` and emits one chronological list, newest first, of what NOAA published and
what this project fetched. Two distinctions keep it honest:

* **`url` vs `evidence_url`.** `url` is the link the reader gets; `evidence_url` is
  the URL whose recorded fetch justifies the row's content. They differ for NWS's
  human-facing pages (`forecast.weather.gov/MapClick.php`, an alert object's
  `@id`), which are linked for convenience but were never fetched themselves. Each
  row publishes `link_verified` (was that link fetched?) and `provenance_verified`
  (does a recorded fetch stand behind the content?), and a row with neither is
  labelled a pointer for manual review and raises a warning.
* **Dates the publisher did not give are not invented.** An NWS period's local
  `startTime` is converted to UTC; a CPC issue date printed as `18 Sep 2026` or
  `September 17, 2026` becomes a **date with no clock time** (`time_known: false`,
  the publisher's own wording kept beside it); a product with no issue date is
  listed undated; and a timestamp that will not parse is dropped with a warning
  rather than guessed at.

Model-guidance rows carry `official: false` and the tier's warning into the same
list, so the difference is visible where a reader might otherwise blur it. The
ledger check `feed-traceable` re-derives every count, checks the sort order, the
date/timestamp agreement, the host of every link, and that no model-guidance row is
marked official.

## 24. The retired wind archive: investigated every run, never papered over (pass 9)

The GSOD and hourly ISD files for the wind station stop well before the daily
rain/temperature record. NCEI retired those products for this station on
2025-08-29, and the nightly pipeline treats that as something to keep testing
rather than a fact to state once:

* `data/isd_history.json` records the search through NCEI's own ISD station history
  for a successor identifier, with one of three verdicts from a closed set
  (`successor-id-found`, `station-found-no-successor`, `station-not-in-history`).
* `data/ghcnh_probe.json` re-probes the GHCN-Hourly / SSOD replacements on every
  run, so a successor that appears later is picked up without a code change.
* The coverage notes on the site say the archive is retired and name the date; the
  wind statistics stay labelled with the archive they were counted from.
* `successor-probe-present` fails the run if the investigation stops happening, and
  `record-coverage-published` fails it if a published `last_date` stops matching
  the age printed next to it.

An earlier draft of this pass classified the same stop with a separate probe module
(station-specific gap / archive-wide lag / not determinable). It was retired in
favour of the above: NCEI's own retirement notice plus a per-run successor probe
answers the question with better evidence than inferring it from control stations,
and two published verdicts about one archive would invite exactly the confusion
this project exists to avoid.

## 25. Per-field deep links: every headline figure points at its own row (pass 9)

Each day cell carries deep links for **the field the reader is looking at**, not
one generic link per day. The day dialog renders them as *Verify each number
yourself*:

* temperature and rain name the GHCN-Daily row (wide CSV, one row per `DATE`) and
  say which columns to read, so a normals-derived figure is not mistaken for an
  observation;
* derived humidity names the hourly-normals file and says the value is derived by
  the Magnus formula from temperature and dew point;
* wind names the GSOD / hourly ISD file that holds the day's rows;
* inside the official horizon, the NWS links name the hourly `startTime` values
  that fell in the local day and the gridpoint `validTime` intervals behind the
  gust and rain amount — nothing is averaged away, the hint says what to search for.

`deep-links-traceable` holds every link to a vetted official host and requires each
headline field to offer one. The links are offered for manual review; they are not
evidence for a figure. Evidence remains the recorded fetch of the file the figure
was actually computed from, with its status, byte count and SHA-256.

## 26. Auxiliary manifests and one quality report (pass 9)

`data/provenance.json` is written by `pipeline/main.py` and by nothing else,
because `data/run.json` publishes its entry count and the ledger re-derives the
ok/failed/absent split from it. A second script appending rows would desynchronise
those numbers and silently stop the nightly publish.

So `pipeline/lib_provenance.py` owns one convention: every auxiliary script writes
`data/<area>_provenance.json` with the same `{"entries": [...]}` shape, names its
`area`, and says what it fetched; findings are merged into
`data/quality_report.json` under a removable `"source": area` tag, which makes the
merge idempotent (running a script twice cannot double-count a finding, and a
finding fixed on a later run cannot survive). Counts in the quality report are
recomputed from the entries, so published totals cannot disagree with them.

`pipeline/verify_sources.py` scans **every** manifest, not just the nightly one, so
a new script fetching from an unvetted host is caught on its first run. The ledger
adds `auxiliary-manifests-vetted` (host, HTTPS, evidence, area/note labelling) and
`auxiliary-manifests-separate` (no fetch double-recorded, and `run.json`'s
published total still describes the nightly manifest alone).

Two conventions coexist here, deliberately, and both satisfy those checks:

* **Merge back** — `pipeline/cpc_backtest.py` folds its fetches and findings into
  `provenance.json`, `run.json`, `quality_report.json` and `summary.txt`
  (`merge_run_manifests`), because its scored rows must appear in the same manifest
  the run's published totals describe.
* **Separate manifest** — `pipeline/model_guidance.py` writes
  `data/model_guidance_provenance.json`, because that tier is meant to be readable
  as its own thing, with its own area label and note.

Either way the invariants hold: a fetch is recorded in exactly one manifest, every
manifest is held to the vetted-host and evidence rules, and the totals `run.json`
publishes are recomputed from the entries rather than carried over.

## 27. Rain duration conditioned on the ENSO phase (added 20 Sep 2026, session 13)

The duration question ("will it rain for days or weeks straight?") was already
answered over all 30 seasons of the 1991–2020 record. For a season running under a
strong El Niño the useful denominator is narrower, so `climo.enso_stratified_streaks()`
publishes, per phase:

* `n` — how many of the 30 seasons the record assigns to that phase;
* for 3, 5, 7 and 10 consecutive wet days: `seasons` (the count) and `pct`
  (the count / `n`), where a wet day is ≥ 0.01 in and the run is counted inside
  Oct 1 – Jan 31;
* `longest_streak_days` — the same distribution summary (mean/median/min/max and
  the deciles) the season totals get, taken over the seasons in that phase.

Three rules, all enforced rather than promised:

1. **One source of phase assignment.** The function takes the season rows
   `build_season_statistics` already produced, so the duration table and the
   totals table cannot disagree about which season belongs to which phase. The
   ledger check `enso-streaks-recompute` re-derives the whole block from those
   same rows and fails on any difference.
2. **No denominator, no number.** Every percentage is published next to the
   counts it came from, and the site prints `81.8% (9 of 11)` — never a bare
   percentage. The bottom-line answer's confidence line reads
   `n = 30 seasons; the phase split rests on 11 of them`.
3. **Small samples are labelled, not smoothed.** With 11 El Niño, 7 neutral and
   12 La Niña seasons, one season moves a phase percentage by about 8–14 points.
   The site says so beside the table and in the cost driver, and the figures are
   described as observed frequencies in that subset of the record — never as a
   forecast for the coming season. A phase with no seasons yields no row at all,
   so a 0% can never be read as "never happens".

Regeneration: the new block was added to the committed `climatology.json` by
calling this same function on the season rows already in that file, and every
downstream dataset was rebuilt by the committed offline builders. The nightly job
re-derives it from the fetched sources; `calendar.json` gained exactly this one key.

## 28. Storm severity conditioned on the ENSO phase (added 20 Sep 2026, session 14)

Section 27 answered *how many days straight* for the phase this season is in.
This section does the same for *how hard*: `climo.enso_stratified_severity()`
takes the same season rows and, for each phase, summarises ten per-season
counters that already existed in those rows and were already published for the
whole record. Nothing is measured anew; the record is only split.

| Key | Counter (per Oct 1 – Jan 31 season) | Station | Rounding |
| --- | --- | --- | --- |
| `wet_days_ge_050in` / `_1in` / `_2in` | days with ≥ 0.50 / 1.00 / 2.00 in | GHCN-Daily `USW00023272` | 1 dp |
| `max_daily_prcp_in` | wettest single day | `USW00023272` | 2 dp |
| `wind_and_rain_days` | days with ≥ 0.01 in downtown **and** an SFO daily max sustained wind ≥ 20 kt (whole-day pairing) | both | 1 dp |
| `heavy_wind_and_rain_days` | ≥ 0.50 in and an SFO gust ≥ 35 kt | both | 1 dp |
| `severe_wind_and_rain_days` | ≥ 1.00 in and an SFO gust ≥ 40 kt | both | 1 dp |
| `gust_days_ge_40kt` / `wind_days_ge_30kt` | days with a gust ≥ 40 kt / a sustained wind ≥ 30 kt | GSOD `72494023234` | 1 dp |
| `max_gust_mph` | strongest gust of the season | `72494023234` | 1 dp |

The output, `calendar.enso_stratified_severity[phase]`, carries `n`, the season
labels, and for each key `{n, mean, median, min, max, p10, p90, seasons_with_any}`.
A counter absent from a season row is left out of that key's sample (`n`
drops), never counted as zero.

Where it appears, and the rules that bind each place:

1. **The outlook strip** — one full-width cell titled *Hard rain, wind and
   wind + rain in past El Niño seasons (11 of the 30), beside all seasons*. Each
   row is `phase mean · median · max` next to `all-season mean · max`, in the
   dataset's own rounding (the render guard compares the cell text with the
   JSON values, so a re-rounded figure fails). The cell states the stations and
   ends with *An observed conditional frequency in a small sample, not a
   forecast for 2026-27*. No rows in the dataset → no cell, and a cell with no
   rows behind it is a smoke failure.
2. **Bottom-line answers 3–6 and cost drivers 2–4** — each gains rows in the
   fixed pattern `<label> in <Phase> seasons on record (<n> of the <N>)` →
   `mean a · median b · max c — all N seasons: mean d`, and one sentence that
   compares the phase mean with the all-season mean and repeats the sample
   size. The ledger check `enso-severity-recompute` rebuilds the whole table
   from the season rows and checks every such row's n, mean, median, max and
   label against it; it also fails when the current phase is in the table but
   the derived rows are absent.
3. **The season-by-season ENSO card** — three added columns (days ≥ 1.00 in,
   gust ≥ 40 kt days, whole-day wind + rain days; mean with the worst season in
   brackets). Same rows, same `n`, same caveat paragraph.

Three rules carried over from §27 and one added:

* **One phase assignment** (the season rows), so the totals, the duration table
  and the severity table cannot disagree about which season is which.
* **No denominator, no number**: every row prints `(n of the N)`.
* **Small samples are labelled, not smoothed**: the strip cell, the answers and
  the card all say *observed, not forecast* and print the `n`.
* **The wind station is a reference, not a bound.** Every wind figure names SFO
  and its distance; the phrase "upper bound for the Sunset" was withdrawn as
  bug 74 (`docs/LIMITATIONS.md` §26) because nothing in the project's sources
  establishes the direction.

Regeneration: `build_calendar.py` writes the block; `landlord_summary.py`
derives the strip cell and the rows; `executive_summary.py` prints the table;
`verify_claims.py` recomputes it. The nightly job re-derives everything from the
fetched sources.

## 29. The ocean-side wind record — NDBC station 46026 (added 20 Sep 2026, session 16)

**Why it exists.** The project's wind record is SFO, a bay-shore airport 11.9 mi from
the ZIP centroid. Adding the nearest official *ocean-side* anemometer does not fix
that — a moored buoy 19.4 mi west is not the Sunset either — but it stops the site
from having exactly one wind vantage point and calling it the city's.

**What is fetched.** `pipeline/ocean_wind.py` reads NDBC's station page (owner, type,
anemometer height, water depth), the station table (coordinates, hull), the measurement
page (the units sentences it quotes), the realtime file (one latest provisional
observation) and the per-year standard-met files for the 1991–2020 seasons — the year
list comes from NDBC's own history page, and each file is fetched as published.

**How it is parsed.** By header *name*, not column position: the archive spans three
layouts (two-digit years with `WD`/`BAR`, four-digit years with `WDIR`/`PRES`, and the
modern file whose month and minutes columns are both named `MM` after uppercasing).
Missing values are NDBC's own sentinels — runs of 9s in the historical files, `MM` in
the realtime file — and a report whose wind, gust and wave height are all missing is
counted as an empty report rather than as an observation. Wind is converted from the
file's own units (m/s) to knots at parse time; a 9.9 m/s gust is 19.2 kt, not 9.9.

**How it is aggregated.** Days are distinct **UTC dates** inside 1 Oct – 31 Jan (the
files carry UTC only, and the window is stated on the page). A threshold day is a date
whose maximum reached the threshold: gusts at 34/40/48 kt — the marine gale and storm
scales plus the 40 kt row the SFO tables use — and sustained wind at 20/30 kt. Each
season also publishes its maximum gust (kt and mph) and its maximum significant wave
height (m and ft), with the timestamps they occurred.

**Two rules that travel with the data.** `coverage_rule.thin_below_pct` names the
coverage below which a season is called thin, and `coverage_rule.counter_rule` states
that every mean, median, minimum and maximum is computed over seasons that observed at
least one Oct–Jan date. A season nobody observed is **not** a zero: averaging outages
in as calm weather turned a gale record into "0.07 gust days per season" (bug 78), and
the ledger re-derives the counters under exactly the declared rule.

**What the ledger checks** (`verify_claims.py` §13h): every counter re-derived from the
season rows; coverage arithmetic and the thin/missing season lists; the station's
coordinates and distance from the ZIP centroid; the three marine statements and the
three boolean flags; each quoted NDBC sentence found verbatim with the units page's
fetch recorded; the latest-observation conversion; and isolation from the scoreboard.
If `data/ocean_wind.json` is not published yet, the ledger says so as a warning instead
of inventing an empty tier.
