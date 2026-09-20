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

### Reverse geocode &mdash; what the Census says that point is

The site calls the forecast point the Sunset District. That is a *naming* claim,
so it is read from the Census rather than written by hand.

| | |
| --- | --- |
| Product | Census Geocoder &mdash; reverse lookup by coordinate |
| URL | <https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x=-122.483894&y=37.760459&benchmark=Public_AR_Current&vintage=Current_Current&format=json> |
| Used for | Which official Census geographies contain the published centroid |
| Result | County subdivision **Sunset CCD** (GEOID `0607593267`), **San Francisco County** (`06075`), place **San Francisco city**, Census tract **326.01** (`06075032601`), block GEOID `060750326013006`, Congressional District 11, urban area San Francisco&ndash;Oakland |
| Browser check | <https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress?address=&benchmark=Public_AR_Current> &mdash; or paste the URL above into a browser |
| Offline fixture | `tests/fixtures/census_geocoder_94122.json` (real response, trimmed; provenance in `tests/fixtures/README.md`) |

The pipeline publishes the lookup URL, its SHA-256, the geography types the
Census actually returned, and a `naming_note` stating that "Sunset CCD" is the
Census county subdivision containing the centroid &mdash; not a city-defined
neighbourhood boundary. The GEOIDs must nest (county &rarr; subdivision/tract
&rarr; block) or the claim ledger fails the run.

Note: the Census street-level endpoint
(`/geocoder/locations/coordinates`) returns **404** for this coordinate, so no
matched street address is published; the geographies endpoint is the evidence.

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
| Area Forecast Discussion | `/products/types/AFD/locations/MTR` | the forecasters' own reasoning, verbatim; scanned for storm language (see `docs/METHODS.md`) |

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

### CPC back-test archives (used by `pipeline/cpc_backtest.py`)

| Source | URL | Note |
| --- | --- | --- |
| Live GIS (recent months only) | <https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/> | keeps ~8 recent `seasprcp_YYYYMM.zip` / `seastemp_YYYYMM.zip` issuances; older ones 404 |
| **Official long-lead archive (Oct 1995 →)** | <https://www.cpc.ncep.noaa.gov/products/archives/long_lead/llarc.ind.php> | the only accepted source for historical issuances |
| CPC's own seasonal verifications | <https://www.cpc.ncep.noaa.gov/products/predictions/long_range/tools/briefing/seas_veri.grid.php> | CONUS-wide skill, not a 94122 score — linked for manual review only |

When no historical archive is retrievable the back-test writes
`status: pending-backfill` rather than a hit-rate, and each missing issuance is
recorded in the provenance manifest under the expected-absence rule
`historical-archive-not-retained` (a 404 on the live server is routine, not an
outage). **The IRI Data Library was considered and rejected:** it is a Columbia
academic mirror, not an official NOAA operational product; it serves HTTP (this
project requires HTTPS); and its `SOURCES/.NOAA/.NCEP/.CPC/` tree holds
monitoring datasets, not the outlook polygons. It stays off `ALLOWED_HOSTS`.

### ENSO

| Product | URL | Used for |
| --- | --- | --- |
| **Official ONI product** (season-labelled 3-month means) | <https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt> | **The ENSO number shown on the site.** Read directly from NOAA's published product — not re-derived. |
| **ENSO Diagnostic Discussion** | <https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml> | The Alert System Status (e.g. "El Nino Advisory"), the synopsis and the key sentences, all stored verbatim with the page SHA-256 |
| Nino 3.4 monthly anomaly table (ERSSTv5) | <https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt> | Cross-check only: the project recomputes a 3-month mean and publishes any difference from the official ONI |
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
| GSOD, `72494023234` (KSFO), 1991-2026 | <https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/> | daily mean wind, max sustained wind, max gust, precipitation |
| **ISD hourly (global-hourly), `72494023234` (KSFO), 1991-2026** | <https://www.ncei.noaa.gov/data/global-hourly/access/{year}/72494023234.csv> | hour-by-hour wind speed and liquid precipitation, used to count hours when rain and ≥20 kt wind **actually coincide** (the landlord's "at the same time" question). Raw hourly files are **not** committed - only the aggregated summary in `data/isd_hourly_summary.json` |
| Storm Events (SF County FIPS 06075) | <https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/> | recorded storm events, magnitudes, damage |
| 1991-2020 Daily Climate Normals, `USW00023272` | <https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/USW00023272.csv> | cross-check on the computed normals |
| **1991-2020 Monthly Climate Normals**, `USW00023272` | <https://www.ncei.noaa.gov/data/normals-monthly/1991-2020/access/USW00023272.csv> | **Independent cross-check** on this project's GHCN-derived monthly rainfall means; the nightly job publishes the difference (largest 0.07 in on the first run) |
| **1991-2020 Hourly Climate Normals**, `USW00023234` | <https://www.ncei.noaa.gov/data/normals-hourly/1991-2020/access/USW00023234.csv> | **Source of the humidity normal** used on climatology days: relative humidity derived from the official hourly temperature and dew-point normals with the Magnus formula |
| **GSOD README** | <https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt> | the authority for GSOD units and missing-value flags |

Station `USW00023272` is **SAN FRANCISCO DOWNTOWN, CA US**, at
37.7705 N, -122.4269 W, elevation 45.7 m - the closest long-record
precipitation gauge with a continuous daily series.

### GSOD/ISD retirement (August 2025) and their official successors

NCEI retired both archives on **2025-08-29** (final HadISD release
`v342_202508p`; the GSODR docs record the same end date). The KSFO series used
here end at **2025-08-27** — that is the provider's end-of-service, not a gap
in this project, and the coverage notes and stale-archive flag say so. The
official successors, already probed by every pipeline run
(`data/isd_history.json`, `data/ghcnh_probe.json`) and to be stitched in once
their coverage is confirmed:

| Successor | Replaces | Bulk access |
| --- | --- | --- |
| **GHCNh** (Global Historical Climatology Network hourly) | ISD / global-hourly | PSV and Parquet by year: `https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/access/by-year/{YYYY}/{psv,parquet}/GHCNh_{ID}_{YYYY}.*` — [station list](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-station-list.csv) — DOI `10.25921/jp3d-3v19` |
| **SSODv2** (Synoptic Summary of the Day, from GHCNh) | GSOD | daily summaries 00–23 UTC; GHCNd remains the recommended source for daily precipitation and max/min temperature |

### ISD hourly — the unit conventions used, and why

The ISD hourly files are fixed-width-in-CSV: `WND` is
`direction, direction quality, type, speed in tenths of m/s, speed quality` and
`AA1` is `period in hours, depth in tenths of mm, condition, quality`. This project
converts the speed with 1 m/s = 1.943844 kt and the depth with /25.4 in per mm, and
publishes the conversion in `data/isd_hourly_summary.json` under `units` so a
reviewer does not have to trust the code. Two conventions matter:

* **AA1 field 1 is the number of hours the reported depth covers.** A report with a
  period longer than one hour is an accumulation, not an hour-by-hour measurement.
  Those hours are still counted has having rain, but the count of them is published
  separately (`simultaneous_hours_from_multi_hour_reports`) rather than being
  presented as if every hour were measured on its own.
* **Local days, not UTC days.** ISD timestamps are UTC; the season window and the
  daily counts are `America/Los_Angeles` (the same convention the GHCN rain days
  use), which is why the hour-by-hour statistic does not inherit the GSOD
  UTC-day caveat.

The per-season coverage is published too (`dates_with_data` against the 123 dates of
Oct 1 - Jan 31), and a season that reported on fewer than 95% of those dates is
**excluded and named** rather than averaged in.

### Humidity — what is official and what is derived

NOAA does not publish a relative-humidity normal. The `HLY-TEMP-NORMAL` and
`HLY-DEWP-NORMAL` columns of the hourly normals file are official; the relative
humidity shown on the site is computed from those two by the standard Magnus
formula, per calendar date, and is labelled as a derivation everywhere it appears
(the day dialog states the station and the method). Where the file is unavailable,
the field is left empty — the pipeline never estimates a missing number.

## 5. NOAA CPC NMME &mdash; model guidance, **not an official forecast**

Retrieved by `pipeline/model_guidance.py` into `data/model_guidance.json`, with its
own manifest (`data/model_guidance_provenance.json`) and its own site section.

| What | Where | How it is used |
| --- | --- | --- |
| NMME probability forecast index | <https://www.cpc.ncep.noaa.gov/products/NMME/probindex.shtml> | The page states the period the maps cover ("For: &hellip;"). That string is quoted verbatim; this project never derives a month range from a filename. |
| How to read the maps | <https://www.cpc.ncep.noaa.gov/products/NMME/NMME_PROB_descr.html> | Definition sentences (ensemble size and weighting, terciles, the &gt;38 % / &lt;33 % contour rule, hindcast-derived tercile limits) are copied verbatim and re-checked as substrings of the fetched text on every run. **The page is CP1252**, so it is decoded with the publisher's own encoding; decoding it as UTF-8-with-replacement would turn its typographic quotes into U+FFFD and break the substring check. |
| Seasonal probability maps (precipitation rate, 2 m temperature) | <https://www.cpc.ncep.noaa.gov/products/NMME/prob/usPROBprate.S.html>, <https://www.cpc.ncep.noaa.gov/products/NMME/prob/usPROBtmp2m.S.html> | The full-size PNGs are downloaded to `assets/model_guidance/` and stored with their byte count and SHA-256, so the picture a reader sees cannot change afterwards. Thumbnails are skipped. **No value is read out of an image.** |
| Skill (RPSS) and real-time verification | <https://www.cpc.ncep.noaa.gov/products/NMME/prob/rpss.probindex.html>, <https://www.cpc.ncep.noaa.gov/products/NMME/verif/index.html> | Linked next to the maps so they are not read as more skilful than NOAA's own verification says they are. |
| Raw real-time archive | <https://ftp.cpc.ncep.noaa.gov/NMME/archive/> | Monthly run directories back to 2019, each labelled by CPC with the period it covers. The newest directory is recorded with NOAA's own label. **The GRIB2/netCDF inside is not decoded** (see LIMITATIONS §17). |
| CFSv2 production output (NOMADS) | <https://nomads.ncep.noaa.gov/pub/data/nccf/com/cfs/prod/> | Probed for availability only. If it does not answer, the location is reported as not reachable and is not published as a working link. |

All six hosts are on the vetted allow-list. The tier carries a warning that renders
before any content and again on every item, and `model-guidance-isolation` fails the
build if a model-guidance field ever reaches `calendar.json` or `landlord.json`.

## 6. The official-product feed &mdash; derived, no new sources

`data/feed.json` (built by `pipeline/build_feed.py`) makes **no network request at
all**. It is a chronological re-presentation of the datasets above: NWS forecast
issuances and periods, NWS alerts, the Area Forecast Discussion quotations, CPC
outlook issue dates and archived shapefiles/maps, the CPC back-test, the ISD
successor search, the storm-watch digest and every recorded fetch with its status
and SHA-256.

Two distinctions keep it honest:

* **`url` vs `evidence_url`.** `url` is the link the reader gets; `evidence_url` is
  the URL whose recorded fetch justifies the row's content. They differ for NWS's
  human-facing pages (`forecast.weather.gov/MapClick.php`, an alert object's
  `@id`), which are linked for convenience but were never fetched themselves. Each
  row publishes `link_verified` and `provenance_verified`; a row with neither is
  labelled a pointer for manual review and raises a warning.
* **Dates the publisher did not give are not invented.** A CPC issue date printed as
  `18 Sep 2026` becomes a **date with no clock time** (`time_known: false`, the
  publisher's own wording kept beside it); a product with no issue date is listed
  undated; a timestamp that will not parse is dropped with a warning rather than
  guessed at.

Model-guidance rows carry `official: false` and the tier's warning into the same
list, so the difference is visible where a reader might otherwise blur it.

## 7. NOAA NDBC — the ocean-side wind record (added 20 Sep 2026, session 16)

Every other wind figure on this site is measured at SFO, on the bay shore, 11.9 mi
from the ZIP centroid. The nearest official anemometer on the *ocean* side is a
moored buoy, and it is a genuinely different environment, so it is published as its
own tier with its own dataset and provenance manifest.

| | |
| --- | --- |
| Product | Standard meteorological data, station **46026** ("SAN FRANCISCO - 18NM West of San Francisco, CA") |
| Station page | <https://www.ndbc.noaa.gov/station_page.php?station=46026> |
| Annual files | <https://www.ndbc.noaa.gov/data/historical/stdmet/46026hYYYY.txt.gz> (the list of years is read from the [station history page](https://www.ndbc.noaa.gov/station_history.php?station=46026), never typed in) |
| Realtime file | <https://www.ndbc.noaa.gov/data/realtime2/46026.txt> (latest provisional observation; never enters the scoreboard) |
| Station metadata | <https://www.ndbc.noaa.gov/data/stations/station_table.txt> |
| Units / conventions | <https://www.ndbc.noaa.gov/faq/measdes.shtml> — quoted verbatim in `data/ocean_wind.json` |
| Used for | Seasonal counts of gale-force gust days (≥ 34 kt), ≥ 40 kt gust days, ≥ 48 kt days, sustained-wind days, season-maximum gust and significant wave height, over the same 1 Oct – 31 Jan window the SFO tables use |
| Result | 30 seasons 1991-1992 → 2020-2021; each season publishes the share of the 123 dates it covers; a season with no data is published as no data, never as a calm season |

Three rules make it safe to show beside the SFO numbers. **It is marine** — the file
states, and the page repeats, that the buoy is *not a land station*, *not a
measurement inside ZIP 94122*, and *not a bound* on what the neighbourhood
experiences in either direction. **Every counter prints its n** — how many of the 30
seasons actually observed the window, with thin and missing seasons named beside the
means. **Nothing is inferred** — the tier is kept out of `data/calendar.json` and the
day-by-day scoreboard by a ledger check, and NDBC's own warning that a station ID can
be reassigned to a future deployment is quoted with the record.

## Explicitly excluded

| Provider | Why |
| --- | --- |
| AccuWeather, The Weather Company / IBM, Tomorrow.io, OpenWeatherMap, WeatherAPI, Visual Crossing, meteoblue | Commercial. Require a paid key or registered account, license redistribution, and their numbers cannot be checked line by line against a public endpoint. |
| Scraped pages (weather.com, wunderground, accuweather.com HTML) | Not an authorised interface, unstable, and unverifiable. |
| CW3E / Scripps atmospheric-river products | Valuable research, but not an official NOAA operational product. |
| IRI Data Library (`iridl.ldeo.columbia.edu`) | Academic mirror, HTTP only, and its CPC tree holds monitoring datasets rather than outlook polygons. Considered 18 Sep 2026 and rejected — see §3. |
| Anything behind a login, paywall or CAPTCHA | Cannot be verified or reproduced. |

## Why the source list is US-federal (and what that leaves out)

The pipeline draws only on **NOAA / NWS / NCEI / CPC** products plus the **U.S.
Census Bureau** for geography. That is a deliberate scope decision, and it answers
the fair question "why not the global and other national weather agencies?":

* **NWS is the official public forecaster for this location.** The product that
  exists for ZIP 94122 — the gridded forecast this site reads at
  `api.weather.gov/points/37.7605,-122.4839` — is NWS's. No other agency issues an
  official point forecast for a US ZIP, so nothing else can serve as the primary
  forecast source here.
* **Foreign national agencies and ECMWF publish global model fields and their own
  regions' products, not point products for California.** They are genuinely
  useful, but reading a 0.25°-ish model grid and calling it "the forecast for
  94122" would be this project's own derivation, not an official statement — and
  under this project's rules that belongs in the separate, clearly-labelled
  *model guidance* tier (which already carries NOAA's own NMME ensemble output and
  never touches the scoreboard), not in the day-by-day data.
* **Every published number has to be re-derivable from a fetched file.** The
  pipeline records the URL, HTTP status, byte count and SHA-256 of each fetch in
  `data/provenance.json`, and the ledger re-reads those bytes. A source that
  cannot be pointed at, fetched and re-read that way cannot be published here,
  however good it is.
* **Commercial resellers (AccuWeather and similar) stay excluded** for the reasons
  in the table above: paid keys, redistribution terms, and no public endpoint a
  reviewer can check line by line. If you want their second opinion, read it at the
  source — this project cannot vouch for it.
