# SFWeather — Landlord-focused rainy-season outlook for San Francisco 94122

A **source-verified, no-hallucination** rain, wind and storm outlook for San Francisco ZIP code **94122**, covering **1 October 2026 – 31 January 2027**, built exclusively from free, public, official sources: **NOAA / National Weather Service, NCEI, the Climate Prediction Center and the U.S. Census Bureau**.

**Live site:** <https://buffedlizard55-lab.github.io/SFWeather/>

**For landlords:** the site now opens with a **Landlord dashboard** that directly answers: expected rain amounts, long rain-duration events (days/weeks of straight rain), wind, simultaneous wind+rain, and storm severity — all verified line by line with official links.

---

## Landlord dashboard — what you actually need to know

**Location verified:** 37.760459 N, -122.483894 W — U.S. Census Bureau 2024 Gazetteer ZCTA internal point (centroid), land area 3.257 sq mi. Source: [2024 Gazetteer ZCTA file](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip) — [browser check](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html)

**Current ENSO:** From [CPC Niño 3.4 table](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt), ONI rose from -0.54 in Dec 2025 to +0.98 in May 2026 = El Niño. El Niño tilts California winter wetter, but spread is wide.

**Seasonal totals 1991-2020 baseline (GHCN-Daily USW00023272 — [file](https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv)):**

| | Mean | Median | Min | Max |
|---|---|---|---|---|
| October | 0.94 in | 0.57 | 0.00 | 3.11 |
| November | 2.60 in | 2.21 | 0.09 | 10.50 |
| December | 4.78 in | 3.78 | 0.14 | 12.03 |
| January | 4.47 in | 3.65 | 0.00 | 12.07 |
| **Oct-Jan total** | **12.79 in** | 13.26 | 1.71 | 22.82 |

- 34.5 wet days (≥0.01 in) per season average. Expected wet days: Oct 3.5, Nov 7.9, Dec 11.7, Jan 11.4

**Rain duration (consecutive wet days, Oct 1 – Jan 31, same station):**

| At least one run of | Share of 30 seasons |
|---|---|
| ≥3 days | **96.7%** |
| ≥5 days | **80.0%** |
| ≥7 days | **53.3%** — close to coin flip |
| ≥10 days | **23.3%** — ~1 year in 4 |

Longest run per season: mean 7.3 days, median 7.0, min 2.0, max 17.0 days. For landlord: plan gutters, roof drains, tenant comms for week-long rain.

**Wind, and wind together with rain (SFO ASOS 72494023234 — [archive](https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/), [README](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt) — SFO is more open than Sunset, so upper bound):**

- Average daily max sustained wind at SFO: 17.2 mph; average daily max gust: 30.7 mph
- **11.1 days/season** with both rain (≥0.01 in) and sustained wind ≥20 kt (median 10, max 24)
- **2.2 days/season** with heavy rain (≥0.50 in) AND gust ≥35 kt (median 2, max 8)
- Strongest gust of season: mean 53.8 mph, record 70 mph

**ENSO stratification (Oct-Jan totals):**

| Phase | Seasons | Mean | Median | Range |
|---|---|---|---|---|
| El Niño | 11 | **14.23 in** | 13.56 | 7.27 – 22.82 |
| Neutral | 7 | 13.31 in | 13.58 | 1.71 – 20.99 |
| La Niña | 12 | **11.16 in** | 10.39 | 5.39 – 18.47 |

Wettest: 1997-98 22.82 in (strongest El Niño). Driest: 2013-14 1.71 in. Tilt, not verdict.

**Official CPC outlooks for this window (GIS shapefiles sampled at 37.7605,-122.4839 — [GIS index](https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/)):**

From Sep 2026 issuance (https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/seasprcp_202609.zip):

- Oct 2026: EC 33% precip, Above normal 40% temp (monthly update)
- OND 2026: EC 33% precip, Above normal 33% temp
- NDJ 2026-27: Above median 33% precip
- DJF 2026-27: Above median 40% precip
- JFM 2027: Above median 50% precip — strongest wet tilt in window

Maps archived in `assets/cpc/*.gif` and linked to live CPC pages. Discussions: [90-day fxus05](https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html), [Week 3-4](https://www.cpc.ncep.noaa.gov/products/predictions/WK34/), [6-10 day](https://www.cpc.ncep.noaa.gov/products/predictions/610day/).

**Current NWS 7-day forecast:** https://forecast.weather.gov/MapClick.php?lat=37.7605&lon=-122.4839 and https://api.weather.gov/points/37.7605,-122.4839 → https://api.weather.gov/gridpoints/MTR/82,105/forecast/hourly — rendered in “Current official forecast” section with observations and alerts (https://api.weather.gov/alerts/active?zone=CAZ006).

Full landlord guide: [`docs/LANDLORD_GUIDE.md`](docs/LANDLORD_GUIDE.md)

---

## The honest headline

> **No organisation on Earth publishes a forecast for a specific day in January 2027.** The NWS daily forecast reaches about 7 days. Beyond that, the official products are *probabilities for a period* — 6-10 days, 8-14 days, weeks 3-4, calendar months and 3-month seasons.

This project never blurs that line. Every day on the scoreboard is stamped with one of two badges:

| Badge | Meaning |
|---|---|
| **`NWS FORECAST`** | The day is inside the official NWS gridded forecast horizon. High, low, humidity, wind, gusts, rain chance and rain amount are the **actual NWS forecast**. |
| **`CLIMATOLOGY`** | The day is beyond it. Every number is the **1991-2020 observed record for that calendar date** at a named NOAA station. **Not a forecast.** |

CPC outlooks are attached to the days they validly cover, but only as probability statements for the whole period — they are never converted into invented daily numbers.

---

## What is actually known about the 2026-27 rainy season

From the **NOAA Climate Prediction Center long-lead seasonal outlook issued 20 August 2026** ([discussion](https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html), [map index](https://www.cpc.ncep.noaa.gov/products/predictions/90day/)):

* “**El Niño conditions are present … El Niño is strengthening, with a greater than 90 percent chance of a very strong event this fall and winter.**”
* “During the **October-November-December (OND) 2026** season, there is a **69% chance of a historic event** that would exceed the strength of previous El Niño events dating back to 1950.”
* Latest weekly Niño index values at the time of that issuance: **+1.8 °C in Niño-3.4**, +2.5 °C in Niño-3, +3.2 °C in Niño-1+2.

The CPC week 3-4 discussion of **11 September 2026** ([source](https://www.cpc.ncep.noaa.gov/products/predictions/WK34/)) confirms the trend: “Relative SST anomalies in the equatorial Pacific are **nearing +2.0 °C, as the El Niño heads into strong territory**.”

The **ONI** (Oceanic Niño Index, 3-month running mean of ERSSTv5 Niño 3.4 anomalies — [CPC table](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt)) rose from **-0.54 in December 2025** to **+0.98 in May 2026**, i.e. from weak La Niña to El Niño within a single year.

That is the strongest single signal available for a San Francisco winter — and the site shows what the last 30 seasons actually delivered in each ENSO phase, rather than asserting an outcome.

---

## Day-by-day scoreboard — how to read

For each day Oct 1 2026 – Jan 31 2027, the calendar shows temperature, humidity, rain chance, rain amount, wind and wind gusts. Click any day for full breakdown.

| Field | `NWS FORECAST` day | `CLIMATOLOGY` day |
|---|---|---|
| High / low | max / min of hourly NWS temperature | 1991-2020 normal for that date |
| Humidity | mean of hourly NWS relative humidity | not climatologically derived — shown as — |
| Chance of rain | max hourly NWS probability of precipitation | share of the 30 years it rained on that date |
| Rain amount | sum of hourly NWS QPF | 30-year mean for that date |
| Wind / gusts | max hourly NWS wind and gust | 1991-2020 normal daily max at SFO |

Definitions: a **wet day** is ≥0.01 in of liquid precipitation; a **streak** is consecutive wet days; a **wind+rain day** is a day with ≥0.01 in *and* max sustained wind ≥20 kt at SFO; a **heavy wind+rain day** is ≥0.50 in *and* a gust ≥35 kt.

---

## Where every number comes from

Nothing is typed in by hand. Each value traces to a recorded HTTP request with its URL, status, byte count, SHA-256 and retrieval timestamp, all listed in the **Sources** section of the site and in [`data/provenance.json`](data/provenance.json).

| Need | Source | Endpoint |
|---|---|---|
| ZIP-code location | U.S. Census Bureau | [2024 Gazetteer ZCTA file](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip) |
| Daily forecast (temp, humidity, wind, gusts, rain chance, rain amount) | NOAA/NWS | [`api.weather.gov/points` → `gridpoints/…/forecast/hourly`](https://api.weather.gov/points/37.7605,-122.4839) |
| Forecast narrative | NOAA/NWS | [Area Forecast Discussion (MTR)](https://www.weather.gov/mtr), [`api.weather.gov` products](https://www.weather.gov/documentation/services-web-api) |
| Active warnings | NOAA/NWS | [`api.weather.gov/alerts/active`](https://api.weather.gov/alerts/active?zone=CAZ006) |
| Observations | NOAA/NWS | [`api.weather.gov/stations/…/observations/latest`](https://api.weather.gov/) |
| Sub-seasonal outlooks (6-10 d, 8-14 d, weeks 3-4) | NOAA CPC | [GIS shapefiles](https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/) + [discussions](https://www.cpc.ncep.noaa.gov/products/predictions/610day/fxus06.html) |
| Monthly & seasonal outlooks (SON, OND, NDJ, DJF…) | NOAA CPC | [`seastemp_YYYYMM.zip` / `seasprcp_YYYYMM.zip`](https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/seasonal.php) |
| ENSO state | NOAA CPC | [Niño 3.4 anomaly table](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt) |
| Daily rain & temperature history | NOAA NCEI | [GHCN-Daily `USW00023272`](https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv) |
| Daily wind & gust history | NOAA NCEI | [GSOD `72494023234` (KSFO)](https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/) |
| Storm severity history | NOAA NCEI | [Storm Events Database](https://www.ncdc.noaa.gov/stormevents/) |
| GSOD units & caveats | NOAA NCEI | [GSOD README](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt) |

Commercial providers such as **AccuWeather are deliberately excluded**: they require a paid key, their data is not open, and their output cannot be verified line by line the way a NOAA endpoint can.

Full detail: [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) · [`docs/METHODS.md`](docs/METHODS.md) · [`docs/VERIFICATION.md`](docs/VERIFICATION.md) · [`docs/LANDLORD_GUIDE.md`](docs/LANDLORD_GUIDE.md) · [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)

---

## How it is built

```
.github/workflows/update-data.yml   nightly at 07:15 UTC (00:15 Pacific)
        │                           and on every push
        ▼
pipeline/main.py                    fetches every source, records provenance
pipeline/climo.py                   computes the 1991-2020 climatology
pipeline/build_calendar.py          assembles data/calendar.json
pipeline/landlord_summary.py        builds data/landlord.json (landlord dashboard)
pipeline/verify_sources.py          rejects any non-official host
        │
        ▼
data/*.json + assets/cpc/*.gif      committed back to the repo
        │
        ▼
index.html + assets/js/app.js       static GitHub Pages site
```

Because the datasets are refreshed nightly, days convert from `CLIMATOLOGY` to `NWS FORECAST` automatically as they come into range — the scoreboard gets more precise as the season approaches, without anyone editing anything.

Run it yourself:

```bash
pip install nothing   # standard library only
python3 pipeline/main.py --outdir data
python3 pipeline/build_calendar.py
python3 pipeline/landlord_summary.py
python3 -m http.server 8000     # then open http://localhost:8000
```

---

## Known limitations

Summarised here, discussed fully in [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md):

1. **No daily forecast exists beyond the NWS 7-day horizon** — by design, the remaining days show climatology, not guesses.
2. **Two different stations.** Rain and temperature come from the San Francisco downtown gauge (USW00023272, ~1.5 mi away); wind from SFO (KSFO, ~10 mi south-east). San Francisco microclimates mean neither is exactly the Sunset.
3. **GSOD days are UTC days** (00-24Z ≈ 16:00-16:00 local) while GHCN rain days are local days, so the joint wind-and-rain statistic mixes the two.
4. **Small samples.** Single-date percentages come from 30 seasons; one season moves a date by ~3.3 percentage points.
5. **Coastal point-in-polygon.** CPC outlook polygons occasionally miss the coastline; where that happens the nearest polygon is used and the record is flagged in the **Data quality** section.
6. **Storm Events is a reported-events database**, not a census of storms.
7. **No bias correction or downscaling.** The numbers are used exactly as published.

---

## Repository layout

```
index.html                     the site (landlord dashboard + calendar)
assets/css/style.css
assets/js/app.js               renders data/*.json; invents nothing
assets/cpc/*.gif               archived copies of official CPC outlook maps
data/*.json                    pipeline output (nightly) — includes landlord.json
pipeline/                      fetch + analysis code (stdlib only)
docs/                          sources, methods, verification, limitations, landlord guide
.github/workflows/             nightly refresh and GitHub Pages deploy
```

## Disclaimer

Independent hobby project. Not affiliated with or endorsed by NOAA, NWS, NCEI, CPC or the U.S. Census Bureau. **For life-safety decisions use [weather.gov](https://www.weather.gov) or [weather.gov/mtr](https://www.weather.gov/mtr) directly.**
