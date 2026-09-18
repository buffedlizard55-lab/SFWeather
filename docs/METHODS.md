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

