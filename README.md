# SFWeather &mdash; San Francisco 94122 rainy-season outlook

A **source-verified** rain, wind and storm outlook for San Francisco ZIP code
**94122**, covering **1 October 2026 &ndash; 31 January 2027**, built exclusively
from free, public, official sources: **NOAA / National Weather Service, NCEI,
the Climate Prediction Center and the U.S. Census Bureau**.

**Live site:** <https://buffedlizard55-lab.github.io/SFWeather/>

---

## The honest headline

> **No organisation on Earth publishes a forecast for a specific day in
> January 2027.** The NWS daily forecast reaches about 7 days. Beyond that, the
> official products are *probabilities for a period* &mdash; 6&ndash;10 days,
> 8&ndash;14 days, weeks 3&ndash;4, calendar months and 3-month seasons.

This project never blurs that line. Every day on the scoreboard is stamped with
one of two badges:

| Badge | Meaning |
| --- | --- |
| **`NWS FORECAST`** | The day is inside the official NWS gridded forecast horizon. High, low, humidity, wind, gusts, rain chance and rain amount are the **actual NWS forecast**. |
| **`CLIMATOLOGY`** | The day is beyond it. Every number is the **1991&ndash;2020 observed record for that calendar date** at a named NOAA station. **Not a forecast.** |

CPC outlooks are attached to the days they validly cover, but only as
probability statements for the whole period &mdash; they are never converted
into invented daily numbers.

---

## What is actually known about the 2026&ndash;27 rainy season

From the **NOAA Climate Prediction Center long-lead seasonal outlook issued
20 August 2026** ([discussion](https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html),
[map index](https://www.cpc.ncep.noaa.gov/products/predictions/90day/)):

* &ldquo;**El Ni&ntilde;o conditions are present &hellip; El Ni&ntilde;o is strengthening, with a
  greater than 90 percent chance of a very strong event this fall and winter.**&rdquo;
* &ldquo;During the **October-November-December (OND) 2026** season, there is a **69%
  chance of a historic event** that would exceed the strength of previous
  El Ni&ntilde;o events dating back to 1950.&rdquo;
* Latest weekly Ni&ntilde;o index values at the time of that issuance: **+1.8&nbsp;&deg;C in
  Ni&ntilde;o-3.4**, +2.5&nbsp;&deg;C in Ni&ntilde;o-3, +3.2&nbsp;&deg;C in Ni&ntilde;o-1+2.

The CPC week 3&ndash;4 discussion of **11 September 2026**
([source](https://www.cpc.ncep.noaa.gov/products/predictions/WK34/)) confirms the
trend: &ldquo;Relative SST anomalies in the equatorial Pacific are **nearing +2.0&nbsp;&deg;C,
as the El Ni&ntilde;o heads into strong territory**.&rdquo;

The **ONI** (Oceanic Ni&ntilde;o Index, 3-month running mean of ERSSTv5 Ni&ntilde;o 3.4
anomalies &mdash; [CPC table](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt))
rose from **&minus;0.54 in December 2025** to **+0.98 in May 2026**, i.e. from weak
La Ni&ntilde;a to El Ni&ntilde;o within a single year.

That is the strongest single signal available for a San Francisco winter &mdash; and
the site shows what the last 30 seasons actually delivered in each ENSO phase,
rather than asserting an outcome.

---

## What the 1991&ndash;2020 observed record says

These are **observed statistics, not a forecast for 2026&ndash;27** &mdash; the baseline
that every day on the scoreboard is measured against. Computed from GHCN-Daily
`USW00023272` (rain, temperature) and GSOD `72494023234` (wind), 30 seasons,
1 Oct &ndash; 31 Jan.

**Rainfall**

| | Mean | Median | Min | Max |
| --- | --- | --- | --- | ---: |
| October | 0.94&nbsp;in | 0.57 | 0.00 | 3.11 |
| November | 2.60&nbsp;in | 2.21 | 0.09 | 10.50 |
| December | 4.78&nbsp;in | 3.78 | 0.14 | 12.03 |
| January | 4.47&nbsp;in | 3.65 | 0.00 | 12.07 |
| **Oct&ndash;Jan total** | **12.79&nbsp;in** | 13.26 | 1.71 | 22.82 |

* **34.5 wet days** (&ge;&nbsp;0.01&nbsp;in) per season on average.

**How long the rain lasts when it starts** (consecutive wet days, Oct 1 &ndash; Jan 31)

| At least one run of | Share of the 30 seasons |
| --- | --- |
| &ge;&nbsp;3 days | **96.7&nbsp;%** |
| &ge;&nbsp;5 days | **80.0&nbsp;%** |
| &ge;&nbsp;7 days | **53.3&nbsp;%** |
| &ge;&nbsp;10 days | **23.3&nbsp;%** |

So a week-long wet spell is close to a coin flip in any given year, and a
10-day spell happens roughly one year in four.

**Wind, and wind together with rain**

* Average daily max sustained wind at SFO: **17.2&nbsp;mph**; average daily max gust: **30.7&nbsp;mph**.
* **11.1 days per season** with both rain (&ge;&nbsp;0.01&nbsp;in) and sustained wind &ge;&nbsp;20&nbsp;kt (median 10, max 24).
* **2.2 days per season** with heavy rain (&ge;&nbsp;0.50&nbsp;in) *and* a gust &ge;&nbsp;35&nbsp;kt (median 2, max 8).
* Strongest gust of the season: mean **53.8&nbsp;mph**, record **70&nbsp;mph**.

**Does ENSO matter here?** Yes, but it is a tilt, not a verdict (Oct&ndash;Jan totals):

| Phase | Seasons | Mean | Median | Range |
| --- | --- | --- | --- | --- |
| El Ni&ntilde;o | 11 | **14.23&nbsp;in** | 13.56 | 7.27 &ndash; 22.82 |
| Neutral | 7 | 13.31&nbsp;in | 13.58 | 1.71 &ndash; 20.99 |
| La Ni&ntilde;a | 12 | **11.16&nbsp;in** | 10.39 | 5.39 &ndash; 18.47 |

Wettest Oct&ndash;Jan on record: **1997&ndash;98, 22.82&nbsp;in** (the strongest El Ni&ntilde;o in the
record). Driest: **2013&ndash;14, 1.71&nbsp;in**. Note that the wettest El Ni&ntilde;o and the
driest season in the record show how wide the spread stays even in a strong
signal year.

---

## Where every number comes from

Nothing is typed in by hand. Each value traces to a recorded HTTP request with
its URL, status, byte count, SHA-256 and retrieval timestamp, all listed in the
**Sources** section of the site and in [`data/provenance.json`](data/provenance.json).

| Need | Source | Endpoint |
| --- | --- | --- |
| ZIP-code location | U.S. Census Bureau | [2024 Gazetteer ZCTA file](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip) |
| Daily forecast (temp, humidity, wind, gusts, rain chance, rain amount) | NOAA/NWS | [`api.weather.gov/points` &rarr; `gridpoints/&hellip;/forecast/hourly`](https://api.weather.gov/points/37.7605,-122.4839) |
| Forecast narrative | NOAA/NWS | [Area Forecast Discussion (MTR)](https://www.weather.gov/mtr), [`api.weather.gov` products](https://www.weather.gov/documentation/services-web-api) |
| Active warnings | NOAA/NWS | [`api.weather.gov/alerts/active`](https://api.weather.gov/alerts/active?zone=CAZ006) |
| Observations | NOAA/NWS | [`api.weather.gov/stations/&hellip;/observations/latest`](https://api.weather.gov/) |
| Sub-seasonal outlooks (6&ndash;10 d, 8&ndash;14 d, weeks 3&ndash;4) | NOAA CPC | [GIS shapefiles](https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/) + [discussions](https://www.cpc.ncep.noaa.gov/products/predictions/610day/fxus06.html) |
| Monthly &amp; seasonal outlooks (SON, OND, NDJ, DJF&hellip;) | NOAA CPC | [`seastemp_YYYYMM.zip` / `seasprcp_YYYYMM.zip`](https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/seasonal.php) |
| ENSO state | NOAA CPC | [Ni&ntilde;o 3.4 anomaly table](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt) |
| Daily rain &amp; temperature history | NOAA NCEI | [GHCN-Daily `USW00023272`](https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv) |
| Daily wind &amp; gust history | NOAA NCEI | [GSOD `72494023234` (KSFO)](https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/) |
| Storm severity history | NOAA NCEI | [Storm Events Database](https://www.ncdc.noaa.gov/stormevents/) |
| GSOD units &amp; caveats | NOAA NCEI | [GSOD README](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt) |

Commercial providers such as **AccuWeather are deliberately excluded**: they
require a paid key, their data is not open, and their output cannot be verified
line by line the way a NOAA endpoint can.

Full detail: [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) &middot;
[`docs/METHODS.md`](docs/METHODS.md) &middot;
[`docs/VERIFICATION.md`](docs/VERIFICATION.md)

---

## How it is built

```
.github/workflows/update-data.yml   nightly at 07:15 UTC (00:15 Pacific)
        │                           and on every push
        ▼
pipeline/main.py                    fetches every source, records provenance
pipeline/climo.py                   computes the 1991-2020 climatology
pipeline/build_calendar.py          assembles data/calendar.json
pipeline/verify_sources.py          rejects any non-official host
        │
        ▼
data/*.json + assets/cpc/*.gif      committed back to the repo
        │
        ▼
index.html + assets/js/app.js       static GitHub Pages site
```

Because the datasets are refreshed nightly, days convert from
`CLIMATOLOGY` to `NWS FORECAST` automatically as they come into range &mdash; the
scoreboard gets more precise as the season approaches, without anyone editing
anything.

Run it yourself:

```bash
pip install nothing   # standard library only
python3 pipeline/main.py --outdir data
python3 pipeline/build_calendar.py
python3 -m http.server 8000     # then open http://localhost:8000
```

---

## Reading the day cards

| Field | `NWS FORECAST` day | `CLIMATOLOGY` day |
| --- | --- | --- |
| High / low | max / min of hourly NWS temperature | 1991&ndash;2020 normal for that date |
| Humidity | mean of hourly NWS relative humidity | not climatologically derived &mdash; shown as &mdash; |
| Chance of rain | max hourly NWS probability of precipitation | share of the 30 years it rained on that date |
| Rain amount | sum of hourly NWS QPF | 30-year mean for that date |
| Wind / gusts | max hourly NWS wind and gust | 1991&ndash;2020 normal daily max at SFO |

Definitions: a **wet day** is &ge; 0.01&nbsp;in of liquid precipitation; a
**streak** is consecutive wet days; a **wind+rain day** is a day with
&ge;&nbsp;0.01&nbsp;in *and* max sustained wind &ge;&nbsp;20&nbsp;kt at SFO; a
**heavy wind+rain day** is &ge;&nbsp;0.50&nbsp;in *and* a gust &ge;&nbsp;35&nbsp;kt.

---

## Known limitations

Summarised here, discussed fully in [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md):

1. **No daily forecast exists beyond the NWS 7-day horizon** &mdash; by design, the
   remaining days show climatology, not guesses.
2. **Two different stations.** Rain and temperature come from the San Francisco
   downtown gauge (USW00023272, ~1.5&nbsp;mi away); wind from SFO
   (KSFO, ~10&nbsp;mi south-east). San Francisco microclimates mean neither is
   exactly the Sunset.
3. **GSOD days are UTC days** (00&ndash;24Z &asymp; 16:00&ndash;16:00 local) while GHCN rain
   days are local days, so the joint wind-and-rain statistic mixes the two.
4. **Small samples.** Single-date percentages come from 30 seasons; one season
   moves a date by ~3.3 percentage points.
5. **Coastal point-in-polygon.** CPC outlook polygons occasionally miss the
   coastline; where that happens the nearest polygon is used and the record is
   flagged in the **Data quality** section.
6. **Storm Events is a reported-events database**, not a census of storms.
7. **No bias correction or downscaling.** The numbers are used exactly as
   published.

---

## Repository layout

```
index.html                     the site
assets/css/style.css
assets/js/app.js               renders data/*.json; invents nothing
assets/cpc/*.gif               archived copies of official CPC outlook maps
data/*.json                    pipeline output (nightly)
pipeline/                      fetch + analysis code (stdlib only)
docs/                          sources, methods, verification, limitations
.github/workflows/             nightly refresh and GitHub Pages deploy
```

## Disclaimer

Independent hobby project. Not affiliated with or endorsed by NOAA, NWS, NCEI,
CPC or the U.S. Census Bureau. **For life-safety decisions use
[weather.gov](https://www.weather.gov) or
[weather.gov/mtr](https://www.weather.gov/mtr) directly.**
