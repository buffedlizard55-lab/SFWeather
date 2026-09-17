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

## 4. ENSO (updated 17 September 2026)

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

## 5. Humidity on climatology days

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

## 6. Verification (why a number cannot silently be wrong)

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
