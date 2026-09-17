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
