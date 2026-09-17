# Next session — what still needs work & limitations

This file is the handoff for the next work session, as requested: suggestions for what work still needs to be done and any limitations in the way of a successful project. All items below are **source-verified** in intent — they reference official endpoints, not guesses.

## What was accomplished this session

**Verified sources only (no hallucinations):**

- All 100 fetches across 5 official hosts: api.weather.gov, ftp.cpc.ncep.noaa.gov, www.cpc.ncep.noaa.gov, www.ncei.noaa.gov, www2.census.gov — checked by `pipeline/verify_sources.py`
- ZIP 94122 centroid 37.760459, -122.483894 verified from Census Gazetteer https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip
- NWS forecast: https://api.weather.gov/points/37.7605,-122.4839 → https://api.weather.gov/gridpoints/MTR/82,105/forecast/hourly (7-day horizon)
- CPC outlooks: https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/ shapefiles sampled at 37.7605,-122.4839, maps archived in assets/cpc/
- ENSO: https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt ONI +0.98C May 2026 = El Niño
- GHCN-Daily USW00023272 https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv → 1991-2020 baseline 12.79in mean Oct-Jan
- GSOD 72494023234 https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/ + README https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt → wind, gusts, joint wind+rain
- Storm Events https://www.ncdc.noaa.gov/stormevents/ FIPS 06075
- 90-day discussion https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html and Week 3-4 https://www.cpc.ncep.noaa.gov/products/predictions/WK34/

**Landlord dashboard (new):**

- data/landlord.json with executive summary, monthly breakdown, duration risk, wind+rain, CPC outlooks, high-risk dates, 12 action items each with source_url
- index.html landlord section at top with 6 stat cards, tables, action checklist
- assets/css/style.css landlord styles, assets/js/app.js renderLandlord()
- docs/LANDLORD_GUIDE.md with manual review links
- Verified: no daily forecast beyond 7 days exists, so Oct 2026-Jan 2027 shows climatology badged CLIMATOLOGY, not invented forecast

**GitHub Pages:**

- Site at https://buffedlizard55-lab.github.io/SFWeather/ — static, clean UI, user-friendly, simple, mobile-responsive
- Source branch main path / with .nojekyll
- Nightly refresh 07:15 UTC via .github/workflows/update-data.yml (now includes landlord summary step)
- PR #2 created from arena/01a0b046-sfweather and merged to main (commit 32d9571)

## Known limitations (cannot be engineered away without more work)

1. **No daily forecast beyond NWS 7-day horizon** — by design, remaining days show 1991-2020 climatology, not guesses. Anyone claiming specific rain amount for Jan 15 2027 today is inventing it. Verify at https://forecast.weather.gov/MapClick.php?lat=37.7605&lon=-122.4839 (only 7 days).

2. **Two stations ~10 miles apart:** rain/temp USW00023272 (San Francisco Downtown, 37.7705,-122.4269, 45.7m elev, ~1.5mi from 94122 centroid) vs wind GSOD 72494023234 (KSFO, ~10mi SE). Microclimates mean Sunset differs from both. Mitigation: both named, linked, coordinates published, wind described as upper bound.

3. **GSOD days are UTC days (00-24Z ≈ 16:00-16:00 local)** per https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt, while GHCN rain days are local days. Joint wind+rain statistic pairs local-day rain with UTC-day wind — approximation flagged in data quality and caveats.

4. **Small samples:** single-date percentages from 30 seasons (1991-2020); one season moves date by ~3.3 points. ENSO-stratified even smaller (El Niño n=11, La Niña n=12, Neutral n=7). Indicative, not precise.

5. **Coastal point-in-polygon:** CPC shapefiles occasionally miss coastline; nearest polygon used and flagged with ⚠, with map image shown for manual check against https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/

6. **Storm Events is reported-events database**, not census — https://www.ncdc.noaa.gov/stormevents/ only contains what someone reported to NWS office.

7. **No bias correction/downscaling:** numbers used exactly as published.

8. **AccuWeather/commercial excluded deliberately:** require paid key, not open, not independently verifiable line by line. Guardrail verify_sources.py fails build on non-official host. If you want AccuWeather, you must read it directly — this project cannot vouch for it.

## High-value next work (priority order)

### 1. Hourly ISD wind for true local day (high value, moderate effort)
**Why:** Fixes limitation #3 and directly improves answer to "simultaneous wind and rain events". Currently day-level approximation; need hour-by-hour overlap.
**Source:** NOAA Integrated Surface Database hourly https://www.ncei.noaa.gov/data/global-hourly/access/{year}/{station}.csv (free, public, official, no key). Station 72494023234 same as GSOD.
**Work:** Fetch ISD hourly for 1991-2025, convert to America/Los_Angeles local day, count hours where precip>0 and wind≥20kt simultaneously, vs current daily max method. Update climo.py and data quality note.
**Verification:** Compare GSOD daily max gust vs ISD hourly max for same date; document conversion.
**Effort:** ~1 day, stdlib only, but large data volume (hourly files).

### 2. CPC back-testing (high value, moderate effort)
**Why:** Turn site from viewer into accountability tool. Currently reports CPC tilt (e.g., JFM Above median 50%); need to say "when CPC tips above-median for OND here, it verified X% of time".
**Source:** CPC archive shapefiles back to ~2010s at https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/ — same GIS format, just older issuance dates. Already have sampling code.
**Work:** For each past issuance (e.g., seasprcp_202001.zip, etc.), sample at 94122, store prob/category, then compare to observed GHCN total for that valid period. Score hit rate.
**Verification:** Use same point-in-polygon code, provenance manifest for each archive.
**Effort:** ~2 days, need storage for many zips, but doable on Actions runner.

### 3. Atmospheric-river awareness (high value, low-moderate effort)
**Why:** ARs drive almost all CA high-impact winter rain — directly relevant to "days/weeks of straight rain". NWS does not publish per-day AR forecast, but Area Forecast Discussion discusses them.
**Source:** NWS AFD already fetched via https://api.weather.gov/products/types/AFD/locations/MTR — text in data/nws.json products.AFD.text. Also NOAA CW3E research (not official) could be referenced but not used as primary.
**Work:** Extract AR-related language from AFD (regex for "atmospheric river", "AR", "Pineapple Express", "moisture plume"), count mentions, link to date. Add AR flag to calendar days when AFD mentions AR for that forecast period.
**Verification:** AFD text is verbatim official, no invention.
**Effort:** ~0.5 day.

### 4. NWS 7-day forecast verification (moderate value, low effort)
**Why:** Store each night's forecast and score vs next day's observations — accountability.
**Source:** NWS hourly forecast already fetched nightly; observations from https://api.weather.gov/stations/…/observations/latest and GHCN next day.
**Work:** Append each run's forecast to data/history/ with date, then compute bias (forecast high vs observed high, POP vs actual rain).
**Verification:** All from already-vetted hosts.
**Effort:** ~1 day.

### 5. Station comparison & uncertainty band (moderate value, low effort)
**Why:** Show spread between downtown gauge USW00023272 and SFO USW00023234 and any nearer coop stations, as explicit uncertainty range for 94122.
**Source:** GHCN candidates already listed: USW00023272, USW00023234, USC00047899. GSOD also.
**Work:** Fetch multiple stations, compute daily mean spread, show in day dialog as "downtown X in, SFO Y in".
**Verification:** Same GHCN/GSOD parsing.
**Effort:** ~0.5 day.

### 6. CSV / printable export (moderate value, low effort)
**Why:** Landlord wants offline copy for records.
**Work:** Add button in calendar section that generates CSV from calendar.json days[] with fields date, tier, high_f, low_f, humidity_pct, rain_chance_pct, rain_amount_in, wind_max_mph, gust_max_mph, plus sources. Use Blob download, no server.
**Effort:** ~0.25 day.

### 7. Email/RSS digest (moderate value, moderate effort)
**Why:** Notify when day enters 7-day window with high POP, or NWS alert for CAZ006.
**Source:** NWS alerts already fetched https://api.weather.gov/alerts/active?zone=CAZ006
**Work:** GitHub Actions can send via e.g., ntfy.sh (free) or store RSS XML in repo. Needs user opt-in.
**Effort:** ~1 day, plus privacy considerations.

### Larger undertakings (future)

8. **CFSv2 / NMME ensemble sampling:** NCEP publishes Climate Forecast System and North American Multi-Model Ensemble openly on NOMADS https://nomads.ncep.noaa.gov/ — would give genuine model view of Oct-Jan, but requires GRIB2 decoding (eccodes/cfgrib), heavy storage, and very prominent caveats: raw single-member daily output at 2-6 month leads has little skill for specific day and is NOT official forecast. Only do with strong disclaimers.

9. **Bias correction/downscaling:** Calibrate CPC probabilities against local observations, downscale to Sunset using PRISM or similar — research-grade, but needs statistical work and validation.

10. **Any-ZIP interactive map:** Pipeline already parameterized by coordinate (lat/lon from Census), so front-end could allow any ZIP input, fetch Census for that ZIP, then run same sampling. Mostly front-end work, but would need dynamic data fetch (currently static JSON).

## Operational notes for next session

- **Workflow:** .github/workflows/update-data.yml runs nightly 07:15 UTC (00:15 Pacific) after NWS 00Z cycle and CPC daily 15:00-16:00 ET posts. Triggered on any push to any branch (so data/ committed by job doesn't go stale). Uses [skip ci] to avoid self-trigger.
- **Provenance:** Every fetch recorded in data/provenance.json with URL, status, bytes, SHA-256, timestamp. Check Sources section with filter.
- **Quality:** data/quality_report.json flags irregularities (e.g., HWO missing, QPF nulls, stale ENSO page discarded). Shown in Data quality section, not hidden.
- **Landlord summary:** pipeline/landlord_summary.py reads calendar.json, climatology.json, enso.json — no new fetches, so no new hosts to vet. Must run after build_calendar.py in workflow (already added).
- **Local run:** `pip install nothing` (stdlib only), `python3 pipeline/main.py --outdir data`, `python3 pipeline/build_calendar.py`, `python3 pipeline/landlord_summary.py`, `python3 -m http.server 8000`
- **No hallucinations rule:** Never invent daily forecast beyond NWS horizon. Always badge CLIMATOLOGY vs NWS FORECAST. CPC outlooks remain probabilities for period, never daily numbers. Every number must have source_url in provenance.

## Suggested immediate next steps (next session)

1. Implement ISD hourly wind (item #1) — biggest improvement for landlord wind+rain question
2. Add CSV export button — quick win for landlord usability
3. Add AR awareness from AFD — low effort, high signal for long-duration rain
4. Run CPC back-test for OND, DJF for last 10 years to quantify skill at 94122
5. Update docs/LIMITATIONS.md with new findings after ISD work

## Links for manual review (official, free, no key)

- Census Gazetteer: https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip
- NWS point: https://api.weather.gov/points/37.7605,-122.4839
- NWS hourly: https://api.weather.gov/gridpoints/MTR/82,105/forecast/hourly
- NWS forecast: https://api.weather.gov/gridpoints/MTR/82,105/forecast
- Human forecast: https://forecast.weather.gov/MapClick.php?lat=37.7605&lon=-122.4839
- Alerts: https://api.weather.gov/alerts/active?zone=CAZ006
- AFD list: https://api.weather.gov/products/types/AFD/locations/MTR
- CPC GIS: https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/
- CPC seasonal index: https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/seasonal.php
- CPC 6-10 day: https://www.cpc.ncep.noaa.gov/products/predictions/610day/
- CPC 8-14 day: https://www.cpc.ncep.noaa.gov/products/predictions/814day/
- CPC Week 3-4: https://www.cpc.ncep.noaa.gov/products/predictions/WK34/
- CPC 30-day: https://www.cpc.ncep.noaa.gov/products/predictions/30day/
- CPC 90-day discussion: https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html
- Niño 3.4 table: https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt
- ENSO evolution PDF: https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/lanina/enso_evolution-status-fcsts-web.pdf
- GHCN-Daily: https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv
- GSOD: https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/
- GSOD README: https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt
- Storm Events: https://www.ncdc.noaa.gov/stormevents/
- Storm CSVs: https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/
- Normals: https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/USW00023272.csv
- ISD hourly (next work): https://www.ncei.noaa.gov/data/global-hourly/access/
- Live site: https://buffedlizard55-lab.github.io/SFWeather/
- Repo: https://github.com/buffedlizard55-lab/SFWeather

All verified — no commercial AccuWeather etc., all .gov official.
