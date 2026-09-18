# data/

This directory is **generated**, not hand-written. Every file here is produced by
`.github/workflows/update-data.yml`, which runs nightly at 07:15 UTC and on
every push to the repository. Every number traces to a URL in `provenance.json` — no hallucinations, no manual input.

| File | Contents | Official source |
| --- | --- | --- |
| `run.json` | run metadata, the verified 94122 centroid, season bounds, fetch counts (`successful_fetches` / `failed_fetches` / `expected_absences` — the last are fetches that are supposed to 404, each naming a checkable reason), **`record_coverage`**: the newest row fetched from each NCEI archive, its age in days and its URL, plus `stale_archives` for anything more than 180 days behind | U.S. Census Bureau Gazetteer https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip |
| `nws.json` | NWS point metadata, hourly and daily forecasts, observations, alerts, forecast discussion | NOAA/NWS api.weather.gov https://api.weather.gov/points/37.7605,-122.4839 |
| `cpc.json` | CPC shapefile outlooks point-sampled at 94122 (6-10 d, 8-14 d, weeks 3-4, monthly/seasonal) | CPC GIS https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/ |
| `enso.json` | **NOAA's official ONI product** (season-labelled), the locally derived 3-month mean as a cross-check, and the verbatim ENSO Diagnostic Discussion / long-lead discussion sentences with their SHA-256 | CPC https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt and https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml |
| `monthly_normals.json` | NOAA's published 1991-2020 monthly normals — independent cross-check on the GHCN-derived monthly means | NCEI https://www.ncei.noaa.gov/data/normals-monthly/1991-2020/access/USW00023272.csv |
| `humidity_normals.json` | Per-calendar-date humidity normal derived from the official hourly temperature and dew-point normals (Magnus formula), plus the column layout the file actually had | NCEI https://www.ncei.noaa.gov/data/normals-hourly/1991-2020/access/USW00023234.csv |
| `verify.json` + `verify_report.txt` | **Claim ledger**: every headline number, its value, its official source URL with HTTP status, bytes, SHA-256 and retrieval time, plus the automated checks and irregularities. A failing check blocks publication of the data. | produced by `pipeline/verify_claims.py` from the datasets above |
| `isd_hourly_summary.json` | **Hour-by-hour wind and rain** for the same wind station: per local date and per season, the hours where one observation carries both `wind >= 20 kt` and precipitation > 0, plus the day counts, the per-season coverage against the 123 Oct 1 - Jan 31 dates, and the units/thresholds/timezone the aggregation used. Raw hourly files are not kept | NCEI ISD global-hourly https://www.ncei.noaa.gov/data/global-hourly/access/ |
| `climatology.json` | 1991-2020 per-calendar-date normals, wet streaks, wind statistics, ENSO stratification | NCEI GHCN-Daily USW00023272 https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv and GSOD 72494023234 https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/ |
| `calendar.json` | the assembled Oct 1 - Jan 31 scoreboard, one record per day (temp, humidity, rain chance, rain amount, wind, gusts) | Derived from NWS hourly + climatology + CPC — see build_calendar.py |
| `landlord.json` | **Landlord-focused executive summary**: expected rain amounts, duration risk, wind+rain, action checklist — all source-verified | Derived from calendar.json + climatology + CPC, no new external fetches |
| `storm_events.json` | NCEI Storm Events records for San Francisco County (FIPS 06075) | NCEI https://www.ncdc.noaa.gov/stormevents/ |
| `provenance.json` | every HTTP fetch: URL, status, bytes, SHA-256, retrieval timestamp — **manual review links** | All .gov hosts verified by pipeline/verify_sources.py |
| `quality_report.json` | irregularities detected during the run (flagged for review, not hidden) | — |
| `pipeline.log` | human-readable copy of the run log (reviewable without Actions logs) | — |

If this directory looks empty, the last run failed or has not completed yet; the
site shows an explicit error banner rather than rendering blanks.

Do not edit these files by hand. Change `pipeline/` and let the workflow rebuild them.

## Landlord use

- **Rain amounts**: see `landlord.json` executive_summary.season_total_prcp, oct/nov/dec/jan totals — 1991-2020 baseline from GHCN-Daily
- **Rain duration**: streak_probability ge_3/5/7/10_days — share of seasons with that long a wet streak
- **Wind+rain at the same time**: `landlord.json` executive_summary.wind_and_rain_hourly — the hour-by-hour count (`days_with_a_simultaneous_hour`, `simultaneous_hours_per_season`), the same-station whole-day pairing for comparison, and the seasons excluded with their coverage. The older whole-day figures (`wind_and_rain_days`, `heavy_wind_and_rain_days`, `max_gust_mph`) are still published and labelled — from GSOD 72494023234 (SFO ASOS, upper bound for Sunset)
- **How current the sources are**: `run.json` record_coverage — newest row fetched from each NCEI archive, its age in days and its URL; an archive more than 180 days behind is listed in `stale_archives` and flagged in `quality_report.json`
- **Day-by-day**: `calendar.json` days[] — each day has high_f, low_f, humidity_pct, rain_chance_pct, rain_amount_in, wind_max_mph, gust_max_mph, plus climo{} and cpc[] with source URLs
- **Official outlooks**: `calendar.json` cpc.records[] and `landlord.json` cpc_outlooks_relevant[] — probabilities for period, never daily values

All hosts verified: api.weather.gov, ftp.cpc.ncep.noaa.gov, www.cpc.ncep.noaa.gov, www.ncei.noaa.gov, www2.census.gov — no AccuWeather/commercial.

