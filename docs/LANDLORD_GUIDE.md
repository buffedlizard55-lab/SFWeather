# Landlord guide — San Francisco 94122 rainy season

This is the **actionable, source-verified** companion to the dashboard. Every number here comes from the same pipeline that feeds the site, and every source URL is listed in `data/provenance.json` for manual review. No commercial providers (AccuWeather etc.) are used.

## What you asked for

As a landlord in 94122 (Inner Sunset / Outer Sunset) you said you care most about:

- **Rain** — how much, how likely
- **Rain duration** — days or weeks of straight rain
- **Amounts of rain** — totals, extremes
- **Wind** — sustained and gusts
- **Simultaneous wind and rain** — the combo that damages property
- **Severity of storms** — historical record

The dashboard at <https://buffedlizard55-lab.github.io/SFWeather/> answers each of those with official data only. The numerical snapshot documented below was generated on **17 September 2026 UTC**; use the dashboard's freshness banner, `data/provenance.json`, and the linked official endpoints for the latest refresh.

## The honest headline (no hallucinations)

> **No organization on Earth publishes a forecast for a specific day in January 2027.** 
> The NWS daily forecast reaches about 7 days. Beyond that, official products are probabilities for a period (6-10 days, 8-14 days, weeks 3-4, calendar months, 3-month seasons).

So for Oct 1 2026 – Jan 31 2027 (123 days) the site shows:

- `NWS FORECAST` badge: inside the 7-day horizon, real NWS gridded forecast for grid MTR/82,105 (temp, humidity, wind, gusts, POP, QPF)
- `CLIMATOLOGY` badge: beyond it, 1991-2020 observed record for that calendar date at NOAA stations USW00023272 (rain/temp) and 72494023234 / KSFO (wind). **Not a forecast.**

CPC outlooks are attached to days they cover, but only as probabilities for the whole period — they are never turned into invented daily numbers.

This is the anti-hallucination rule of the project, documented in `docs/METHODS.md` and enforced by the pipeline.

## Current official outlook for 94122

### Where 94122 is (verified)

- **37.760459 N, -122.483894 W** — Census Bureau 2024 Gazetteer ZCTA internal point (centroid), land area 3.257 sq mi
- Source: https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip
- Browser check: https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html
- Verified: the pipeline downloads the ZIP, finds GEOID=94122, reads INTPTLAT/INTPTLONG, records which columns were used

### What the official CPC outlooks say

**This file deliberately contains no CPC numbers.** An earlier version carried a
hand-typed table of them, and it drifted: two temperature rows were written as
"EC 33%" when the sampled shapefiles said *Above normal* at 33.0% — a named
category sitting on the three-way baseline, which the site is required to label
as such everywhere it appears. A Markdown file cannot be re-derived by the claim
ledger, so any number typed into one will eventually contradict the verified
dataset. The rule now is that prose points at the data and the data carries the
numbers.

Read the current values here, in this order of authority:

1. **On the site** — the card *"Official CPC outlooks that cover this rainy
   season"* (landlord dashboard) and the table *"What the official CPC outlooks
   say for this window"* (season outlook). Every row shows the period, the
   variable (Rain / Temp), the category, the probability, the issuance date and
   whether the probability sits on the 33.3% baseline.
2. **In the dataset** — `data/landlord.json` → `cpc_outlooks_relevant` (one
   record per sampled outlook, including the containing polygon index, its
   bounding box and the raw DBF attribute row) and `data/cpc.json` for every
   bundle fetched.
3. **At the source** — the NOAA CPC GIS archives below, sampled at the published
   centroid. The exact files used by the current run, with their HTTP status,
   byte count and SHA-256, are listed in `data/provenance.json` and on the site
   under *Sources*.

**Maps**: archived in `assets/cpc/*.gif`, each linked to live CPC page:

- 6-10 day: https://www.cpc.ncep.noaa.gov/products/predictions/610day/
- 8-14 day: https://www.cpc.ncep.noaa.gov/products/predictions/814day/
- Week 3-4: https://www.cpc.ncep.noaa.gov/products/predictions/WK34/
- 30-day: https://www.cpc.ncep.noaa.gov/products/predictions/30day/
- Seasonal: https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/seasonal.php

**Discussion text**: pulled from CPC, stale-page guard rejects pages that don't mention current year:

- 90-day discussion: https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html
- Week 3-4 discussion: https://www.cpc.ncep.noaa.gov/products/predictions/WK34/texts/week34fcst.txt
- 6-10 & 8-14 discussion: https://www.cpc.ncep.noaa.gov/products/predictions/610day/fxus06.html

From **CPC long-lead seasonal outlook issued 17 Sep 2026** (quoted verbatim on site):

> “El Niño conditions are present, as represented in current oceanic and atmospheric observations.”
> “El Niño is strengthening, with a greater than 90 percent chance of a very strong event this fall and winter.”
> “The OND 2026 Precipitation Outlook depicts enhanced probabilities of above normal precipitation amounts from the southern half of California east-northeastward across most of the Four Corners region…”

The separate **CPC ENSO Diagnostic Discussion issued 10 Sep 2026** says there is a **75% chance** of a historic October–December 2026 event. The older 69% value from the August issuance is not used as current evidence.

Weekly Niño values in the 10 Sep diagnostic discussion: +1.8°C in Niño-3.4, +2.5°C in Niño-3, and +3.4°C in Niño-1+2. Source: CPC discussion.

Week 3-4 discussion **11 Sep 2026**: “Relative SST anomalies in the equatorial Pacific are nearing +2.0°C, as the El Niño heads into strong territory.” Source: https://www.cpc.ncep.noaa.gov/products/predictions/WK34/

**ONI** (Oceanic Niño Index, the official season-labelled 3-month running mean of ERSSTv5 Niño 3.4 anomalies — product: https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt) was **JJA 2026: +1.80°C, El Niño, strong** at the time this guide was written. That is a snapshot: NOAA republishes the ONI monthly, so the authoritative current value is the one the site renders from `data/enso.json` (which records the URL, SHA-256 and retrieval time of the file it read). The project's raw monthly Niño 3.4 table is a cross-check only; it is not the headline ONI value.

**Why this matters for 94122**: El Niño tilts California winter toward wetter. In 1991-2020 record (Oct-Jan totals):

- El Niño (n=11): mean 14.23 in, median 13.56, range 7.27–22.82
- Neutral (n=7): mean 13.31 in, median 13.58, range 1.71–20.99
- La Niña (n=12): mean 11.16 in, median 10.39, range 5.39–18.47

Wettest Oct-Jan: 1997-98 22.82 in (strongest El Niño in record). Driest: 2013-14 1.71 in. So even in strong El Niño, spread is wide — this is a tilt, not a verdict.

### Expected rain amounts (baseline before ENSO tilt)

From **NCEI GHCN-Daily USW00023272** (San Francisco Downtown), 1991-2020, Oct 1 – Jan 31:

| | Mean | Median | Min | Max | P10 | P90 |
|---|---|---|---|---|---|---|
| October | 0.94 in | 0.57 | 0.00 | 3.11 | 0.01 | 2.38 |
| November | 2.60 in | 2.21 | 0.09 | 10.50 | 0.49 | 4.73 |
| December | 4.78 in | 3.78 | 0.14 | 12.03 | 0.62 | 10.75 |
| January | 4.47 in | 3.65 | 0.00 | 12.07 | 0.72 | 8.98 |
| **Oct-Jan total** | **12.79 in** | 13.26 | 1.71 | 22.82 | 6.38 | 18.59 |

- **34.5 wet days** (≥0.01 in) per season on average
- Expected wet days per month: Oct 3.5, Nov 7.9, Dec 11.7, Jan 11.4 (sum of daily rain probabilities)

Source: https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv

### Rain duration — days or weeks of straight rain

Definition: wet day = ≥0.01 in. Streak = consecutive wet days inside Oct 1 – Jan 31, from same GHCN record.

| At least one run of | Share of 30 seasons |
|---|---|
| ≥3 days | **96.7%** (29 seasons) |
| ≥5 days | **80.0%** (24 seasons) |
| ≥7 days | **53.3%** (16 seasons) |
| ≥10 days | **23.3%** (7 seasons) |

- Longest run per season: mean 7.3 days, median 7.0, min 2.0, max 17.0

So a week-long wet spell is close to coin flip in any given year, and a 10-day spell happens roughly 1 year in 4. Plan roof, gutters, drainage, and tenant comms for week-long rain.

Source: same GHCN-Daily file.

### Wind, gusts, and wind+rain together

Wind from **NCEI GSOD 72494023234 (KSFO)**, 11.9 miles SE of 94122 (great-circle distance from the 94122 centroid, published as `climatology.meta.station_distance_mi.wind_ksfo` and recomputed every run), more open/exposed than Sunset — so treat as **upper bound** for 94122. Units: knots in CSV, converted mph ×1.15078 per GSOD README: https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt (README is authority, also notes GSOD days are UTC 00-24Z ≈ 16:00-16:00 local, so joint stat is approximation).

- Average daily max sustained wind at SFO: **17.2 mph**; average daily max gust: **30.7 mph**
- **2.2 days/season** with heavy rain (≥0.50 in) AND gust ≥35 kt (median 2, max 8)
- Strongest gust of season: mean **53.8 mph**, record **70 mph**

**Wind and rain at the same time** is answered two ways, and the site publishes
both rather than one:

- **hour by hour** from **NCEI ISD global-hourly 72494023234 (KSFO)**: a local
  date counts when at least one observation has both `wind ≥ 20 kt` and
  precipitation > 0. This is the headline on the site's *Wind + rain together*
  card, with its per-season coverage and the seasons excluded from it.
- **whole day at a time** from GSOD + GHCN-Daily: a date counts when the day's
  rain total and the day's wind maximum each cross the threshold — a looser
  test that cannot tell rain in the morning from wind at night.

The figures themselves are **not** repeated here (they are recomputed nightly and
a number typed into this file would contradict them within a month — see the
`readme-figures-traceable` guard). Read them from the site card or from
`data/landlord.json` → `executive_summary.wind_and_rain_hourly`.

Definitions used:
- wet_day: calendar day ≥0.01 in
- wind_and_rain_hour: one ISD observation with sustained wind ≥20 kt and precipitation > 0
- wind_and_rain_day: SFO max sustained ≥20 kt AND precip ≥0.01 in (whole-day pairing)
- heavy_wind_and_rain_day: SFO max gust ≥35 kt AND precip ≥0.50 in (whole-day pairing)

Sources:
- Hourly: https://www.ncei.noaa.gov/data/global-hourly/access/ (per-year station files)
- Daily: https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/

### Storm severity

From **NCEI Storm Events Database** for San Francisco County FIPS 06075: https://www.ncdc.noaa.gov/stormevents/ and CSV directory https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/

- The database holds what someone reported to an NWS office — under-reporting is likely, not a census
- Events on record for county in last 12 years are listed on site, with type, magnitude, property damage, narrative
- Most damaging events sorted by damage_property field

### Daily scoreboard — how to use it

For each day Oct 1 2026 – Jan 31 2027, the calendar shows:

- **High / low** — max/min of hourly NWS temp if inside horizon, else 1991-2020 normal for that date
- **Humidity** — mean of hourly NWS RH if forecast; otherwise a labelled derivation from NCEI 1991–2020 hourly temperature and dew-point normals (Magnus formula), when available
- **Chance of rain** — maximum hourly NWS probability of precipitation (POP) if forecast, else share of 30 years it rained on that date
- **Rain amount** — sum of hourly NWS QPF (mm→in) if forecast, else 30-year mean for that date
- **Wind / gusts** — max hourly NWS wind/gust if forecast, else 1991-2020 normal daily max at SFO

Click any day → dialog with full breakdown + sources for that day (NWS hourly URL, GHCN, GSOD, CPC outlooks covering that day).

Sources for forecast days:
- Hourly: https://api.weather.gov/gridpoints/MTR/82,105/forecast/hourly
- Daily narrative: https://api.weather.gov/gridpoints/MTR/82,105/forecast
- Human: https://forecast.weather.gov/MapClick.php?lat=37.760459&lon=-122.483894

Sources for climatology days:
- Rain/temp: https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv
- Wind: https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/
- Units: https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt

## Action checklist (source-verified)

1. **Gutters, downspouts, roof drains** — Expect 12.79 in mean seasonal total, but up to 22.82 in in wettest El Niño year (1997-98). December mean 4.78 in, January 4.47 in. Clean before Oct 1.
2. **Week-long rain plan** — 53.3% of seasons have ≥7-day wet streak, 23.3% have ≥10 days. Longest recorded 17 days. Tenant communication for extended wet periods, check for leaks.
3. **Wind+rain combo** — the site's *Wind + rain together* card gives the hour-by-hour count (rain and ≥20 kt in the same hour) and, beside it, the whole-day count this guide used to quote. All of it is measured at SFO, an upper bound for the Sunset. Secure loose items, check trees and fences.
4. **Gusts** — Season max gust mean 53.8 mph, record 70 mph at SFO. Sunset less, but use as upper bound for insurance/planning.
5. **ENSO tilt** — Read the current ENSO state and the current CPC probabilities on the site (*ENSO — the single biggest driver of a San Francisco winter* and *What the official CPC outlooks say for this window*); they are republished nightly from NOAA's own products and this file does not duplicate them, because a number typed here would contradict the verified dataset within a month. What is stable and safe to plan from is the observed record: in 1991-2020, El Niño seasons averaged 14.23 in and La Niña seasons 11.16 in over Oct-Jan, with substantial min/max overlap — a tilt, not a verdict.
6. **No daily forecast beyond 7 days** — Don't trust any site showing specific rain amount for Jan 15 2027 today. Use climatology as planning baseline, and watch NWS 7-day as season approaches — dashboard auto-promotes days to real forecast nightly.
7. **Use official sources for life-safety** — For warnings, use https://www.weather.gov/mtr and https://api.weather.gov/alerts/active?zone=CAZ006 directly.

## Where every number comes from (manual review links)

| Need | Official source | URL |
|---|---|---|
| ZIP location | U.S. Census Bureau Gazetteer | https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip |
| Daily forecast | NOAA/NWS api.weather.gov | https://api.weather.gov/points/37.7605,-122.4839 → https://api.weather.gov/gridpoints/MTR/82,105/forecast/hourly |
| Human forecast | NWS | https://forecast.weather.gov/MapClick.php?lat=37.7605&lon=-122.4839 |
| Alerts | NWS | https://api.weather.gov/alerts/active?zone=CAZ006 |
| Observations | NWS | https://api.weather.gov/stations/ |
| Sub-seasonal outlooks | CPC GIS | https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/ |
| Monthly/seasonal | CPC GIS | https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/seasonal.php |
| ENSO table | CPC | https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt |
| Daily rain/temp history | NCEI GHCN-Daily | https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv |
| Daily wind/gust | NCEI GSOD | https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/ |
| GSOD units | NCEI | https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt |
| Storm events | NCEI | https://www.ncdc.noaa.gov/stormevents/ |
| Normals | NCEI | https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/USW00023272.csv |

Provenance manifest with every HTTP request (URL, status, bytes, SHA-256, timestamp): `data/provenance.json` — rendered in Sources section.

Quality report with irregularities: `data/quality_report.json` — rendered in Data quality section.

## Why AccuWeather etc. are excluded

Commercial providers require paid key, license redistribution, and their numbers cannot be checked line by line against a public endpoint. The pipeline has a guardrail `pipeline/verify_sources.py` that fails build if any host outside vetted official list (noaa.gov, weather.gov, ncei.noaa.gov, cpc.ncep.noaa.gov, census.gov) is fetched. This is deliberate to keep the project verifiable and free.

If you want a second opinion from AccuWeather, you must read it directly — this project cannot vouch for it.

## Limitations

See `docs/LIMITATIONS.md` for full list. Key ones:

- Two stations 11.9 miles apart, microclimates
- GSOD days are UTC days, GHCN local days — joint wind+rain is approximation
- Small samples: single-date percentages from 30 seasons, one season moves date by ~3.3 points
- Storm Events is reported-events, not census
- No bias correction/downscaling

Next work: hourly ISD wind for true local day, CPC back-testing, AR awareness from AFD text, forecast verification, CSV export — see LIMITATIONS.md.

## Disclaimer

Independent hobby project. Not affiliated with NOAA/NWS/NCEI/CPC/Census. For life-safety use weather.gov and weather.gov/mtr directly.
