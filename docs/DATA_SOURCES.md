# Data sources

Every value on the site comes from one of the endpoints below. All are
**public, free, require no API key**, and are operated by a government agency.
`pipeline/verify_sources.py` fails the build if a request ever goes to a host
that is not on this list.

## 1. U.S. Census Bureau &mdash; where "94122" actually is

| | |
| --- | --- |
| Product | 2024 Gazetteer Files &mdash; ZIP Code Tabulation Areas |
| URL | <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip> |
| Used for | The latitude/longitude of ZIP 94122 (`INTPTLAT` / `INTPTLONG` internal point) |
| Result | **37.760459 N, -122.483894 W**, land area 3.257 sq mi |
| Browser check | <https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html> |

The coordinate is downloaded and matched in the build; it is not typed in. If the
download fails the pipeline falls back to a hard-coded value **and raises a
data-quality error**, so a stale coordinate can never pass silently.

## 2. NOAA / National Weather Service &mdash; everything inside 7 days

Base: <https://api.weather.gov> (the official NWS public API).

| Product | Endpoint | Provides |
| --- | --- | --- |
| Point metadata | `/points/{lat},{lon}` | grid `MTR/82,105`, zone `CAZ006`, county `CAC075`, radar `KMUX`, time zone, nearby stations |
| Hourly forecast | `/gridpoints/MTR/82,105/forecast/hourly` | hourly temperature, dewpoint, relative humidity, wind speed, gust, probability of precipitation, QPF |
| Daily forecast | `/gridpoints/MTR/82,105/forecast` | 14 narrative periods with numeric temperature / wind / POP |
| Raw gridpoint | `/gridpoints/MTR/82,105` | the underlying gridded element arrays |
| Observations | `/stations/{id}/observations/latest` | current conditions from official stations |
| Active alerts | `/alerts/active?zone=CAZ006` | warnings, watches, advisories in force |
| Area Forecast Discussion | `/products/types/AFD/locations/MTR` | the forecasters' own reasoning, verbatim |

Human-readable equivalents:
<https://forecast.weather.gov/MapClick.php?lat=37.7605&lon=-122.4839> and
<https://www.weather.gov/mtr>. NWS asks automated clients to identify
themselves; the pipeline sends a `User-Agent` naming this project.

## 3. NOAA Climate Prediction Center (CPC) &mdash; beyond 7 days

CPC publishes its outlooks as **GIS shapefiles**, which is what makes
point-sampling at 94122 possible without reading numbers off a picture.

| Outlook | Source |
| --- | --- |
| 6-10 day temp / precip | [`610temp_latest.zip`](https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/610temp_latest.zip), [`610prcp_latest.zip`](https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/610prcp_latest.zip) &mdash; <https://www.cpc.ncep.noaa.gov/products/predictions/610day/> |
| 8-14 day temp / precip | [`814temp_latest.zip`](https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/814temp_latest.zip), [`814prcp_latest.zip`](https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/814prcp_latest.zip) &mdash; <https://www.cpc.ncep.noaa.gov/products/predictions/814day/> |
| Weeks 3-4 temp / precip | [`wk34temp_latest.zip`](https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/wk34temp_latest.zip), [`wk34prcp_latest.zip`](https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/wk34prcp_latest.zip) &mdash; <https://www.cpc.ncep.noaa.gov/products/predictions/WK34/> |
| Monthly & seasonal | `seastemp_YYYYMM.zip` / `seasprcp_YYYYMM.zip` under <https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/> &mdash; [index](https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/seasonal.php) |
| End-of-month update | <https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/monthlyupdate/> &mdash; <https://www.cpc.ncep.noaa.gov/products/predictions/30day/> |

Each archive's polygons are tested for point-in-polygon containment at
37.7605 N, -122.4839 W, and the attributes of the containing polygon
(`Fcst_Date`, `Valid_Seas`, `Start_Date`, `End_Date`, `Prob`, `Cat`) are read
straight from the DBF. The matching official GIF map is archived into
`assets/cpc/` and shown beside a link to the live CPC page, so the sampled value
can be checked against the published map by eye.

**Important:** the seasonal archives hold **one shapefile per lead**
(`lead1_SON_temp`, `lead2_OND_temp`, `lead3_NDJ_temp`, `lead4_DJF_temp`, ...).
Sampling only the first would silently discard 13 of the 14 official outlooks,
so every shapefile in the archive is sampled.

### ENSO

| Product | URL |
| --- | --- |
| Nino 3.4 monthly anomaly table (ERSSTv5) | <https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt> |
| ENSO evolution / status / forecast (PDF) | <https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/lanina/enso_evolution-status-fcsts-web.pdf> |
| Long-lead seasonal discussion (quoted on the site) | <https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html> |
| Week 3-4 discussion (quoted on the site) | <https://www.cpc.ncep.noaa.gov/products/predictions/WK34/texts/week34fcst.txt> |

The **ONI** is computed from the official table as the 3-month running mean of
the Nino 3.4 anomaly - NOAA's own definition (El Nino >= +0.5 C,
La Nina <= -0.5 C).

> **Stale-page guard.** Several URLs under CPC's `enso_advisory/` path still
> serve long-dead pages (one is unchanged since November 2016). The pipeline
> rejects any scraped page that does not mention the current year, so a stale
> page can never be quoted as current.

## 4. NOAA NCEI &mdash; the historical record behind the calendar

| Product | URL | Used for |
| --- | --- | --- |
| GHCN-Daily, `USW00023272` | <https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv> | daily precipitation, high and low temperature back to **1921-01-01** |
| GSOD, `72494023234` (KSFO), 1991-2025 | <https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/> | daily mean wind, max sustained wind, max gust, precipitation |
| Storm Events (SF County FIPS 06075) | <https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/> | recorded storm events, magnitudes, damage |
| 1991-2020 Daily Climate Normals, `USW00023272` | <https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/USW00023272.csv> | cross-check on the computed normals |
| **GSOD README** | <https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt> | the authority for GSOD units and missing-value flags |

Station `USW00023272` is **SAN FRANCISCO DOWNTOWN, CA US**, at
37.7705 N, -122.4269 W, elevation 45.7 m - the closest long-record
precipitation gauge with a continuous daily series.

## Explicitly excluded

| Provider | Why |
| --- | --- |
| AccuWeather, The Weather Company / IBM, Tomorrow.io, OpenWeatherMap, WeatherAPI, Visual Crossing, meteoblue | Commercial. Require a paid key or registered account, license redistribution, and their numbers cannot be checked line by line against a public endpoint. |
| Scraped pages (weather.com, wunderground, accuweather.com HTML) | Not an authorised interface, unstable, and unverifiable. |
| CW3E / Scripps atmospheric-river products | Valuable research, but not an official NOAA operational product. |
| Anything behind a login, paywall or CAPTCHA | Cannot be verified or reproduced. |
