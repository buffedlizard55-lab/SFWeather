# SFWeather — rainy-season outlook for San Francisco 94122

A **source-verified, no-hallucination** rain, rain-duration, wind and storm outlook
for San Francisco ZIP code **94122**, covering **1 October 2026 – 31 January 2027**,
built only from free, public, official sources: **NOAA / National Weather Service,
NCEI, the Climate Prediction Center and the U.S. Census Bureau**.

**Live site:** <https://buffedlizard55-lab.github.io/SFWeather/>

Every number on the site is produced by the nightly pipeline, is re-checked
against its source by an automated claim ledger, and carries the official URL,
HTTP status, byte count, SHA-256 and retrieval time of the exact bytes it came
from. **Nothing on the page is typed in by hand**, and no daily forecast is ever
invented for a date beyond the official NWS horizon.

---

## The honest headline (read this before anything else)

> **No organisation on Earth publishes a forecast for a specific day in January 2027.**
> The NWS daily forecast reaches about 7 days. Beyond that, official products are
> *probabilities for a period* — 6-10 days, 8-14 days, weeks 3-4, whole months and
> 3-month seasons.

The site therefore has exactly two tiers, and every day is stamped with one:

| Badge | Meaning |
| --- | --- |
| **`NWS FORECAST`** | The day is inside the official NWS gridded forecast horizon. Every number is the actual NWS forecast. |
| **`CLIMATOLOGY`** | The day is beyond it. Every number is the **1991-2020 observed record for that calendar date** at a named NOAA station. **Not a forecast.** |

CPC outlooks are attached to the days they validly cover, but only as probability
statements for the whole period — they are never converted into invented daily
numbers.

---

## What the site answers for a landlord

**1. Current forecast (the only real forecast).** A "Today's real forecast" panel
shows the official NWS daily window for 94122 — high/low, humidity, chance of
rain, rain amount, max wind and max gust for every day in range, plus the raw
human forecast text, the latest official observations, active warnings and the
verbatim NWS Area Forecast Discussion.

**2. Expected rain amounts** — 1991-2020 observed October, November, December and
January totals from the San Francisco downtown gauge `USW00023272`, with mean,
median, min, max and percentiles, and the same months from NOAA's *published*
1991-2020 monthly normals as an independent cross-check.

**3. Long rain duration ("days or weeks of straight rain")** — the share of the
last 30 seasons that contained at least one run of ≥3, ≥5, ≥7 and ≥10 consecutive
wet days inside 1 Oct – 31 Jan, the longest run in each season, and the
distribution of season totals.

**4. Wind, and wind together with rain** — from SFO ASOS `72494023234`: mean daily
max sustained wind, mean daily max gust, days per season with rain *and*
≥20 kt wind, days per season with ≥0.50 in *and* a ≥35 kt gust, and the strongest
gust of the season. SFO is more exposed than the Sunset, so these are an
**upper bound** for 94122 — stated on the site, not hidden.

**5. Storm severity history** — NCEI Storm Events records for San Francisco
County (FIPS 06075), with the standing caveat that it is a reported-events
database, not a census.

**6. Day-by-day scoreboard** — click any day from 1 Oct 2026 to 31 Jan 2027 for
high/low, humidity, chance of rain, rain amount, max wind, max gust, the 1991-2020
record for that date (how often it rained, wettest on record, strongest gust), and
the CPC outlooks covering it. The whole scoreboard and the current forecast can be
downloaded as CSV, or printed to PDF.

---

## Where every number comes from

| Need | Official source | Endpoint |
| --- | --- | --- |
| Location of "94122" | U.S. Census Bureau | [2024 Gazetteer ZCTA file](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip) |
| Daily forecast (temp, humidity, wind, gust, rain chance, rain amount) | NOAA / NWS | [`api.weather.gov/points/37.7605,-122.4839`](https://api.weather.gov/points/37.7605,-122.4839) → [`gridpoints/MTR/82,105/forecast/hourly`](https://api.weather.gov/gridpoints/MTR/82,105/forecast/hourly) |
| Forecaster narrative, warnings, observations | NOAA / NWS | [Area Forecast Discussion](https://api.weather.gov/products/types/AFD/locations/MTR), [active alerts](https://api.weather.gov/alerts/active?zone=CAZ006), [station observations](https://api.weather.gov/stations/SFOC1/observations/latest) |
| Sub-seasonal outlooks (6-10 d, 8-14 d, weeks 3-4) | NOAA CPC | [GIS shapefiles](https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/) + [discussions](https://www.cpc.ncep.noaa.gov/products/predictions/610day/fxus06.html) |
| Monthly & seasonal outlooks (OND, NDJ, DJF, JFM…) | NOAA CPC | [`seasprcp_YYYYMM.zip` / `seastemp_YYYYMM.zip`](https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/seasonal.php) |
| ENSO state — **NOAA's published ONI product** | NOAA CPC | [`data/indices/oni.ascii.txt`](https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt) |
| ENSO status + seasonal discussion (quoted verbatim) | NOAA CPC | [ENSO Diagnostic Discussion](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml), [90-day discussion](https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html) |
| Daily rain & temperature history | NOAA NCEI | [GHCN-Daily `USW00023272`](https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv) |
| Daily wind & gust history | NOAA NCEI | [GSOD `72494023234`](https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/) |
| Independent monthly normals cross-check | NOAA NCEI | [1991-2020 monthly normals `USW00023272`](https://www.ncei.noaa.gov/data/normals-monthly/1991-2020/access/USW00023272.csv) |
| Humidity on climatology days | NOAA NCEI | [1991-2020 hourly normals](https://www.ncei.noaa.gov/data/normals-hourly/1991-2020/access/USW00023234.csv) — RH derived from the official hourly temperature and dew-point normals (Magnus formula) |
| Storm severity history | NOAA NCEI | [Storm Events Database](https://www.ncdc.noaa.gov/stormevents/) |
| Units & caveats | NOAA NCEI | [GSOD README](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt) |

**Commercial providers such as AccuWeather are deliberately excluded.** They are
not open data: they need a paid key, their terms do not allow redistribution, and
their numbers cannot be checked line by line against a public endpoint the way a
NOAA file can. If you want them as a second opinion, read them at the source —
this project will not republish numbers it cannot verify.

---

## Line-by-line verification (the point of this project)

`pipeline/verify_claims.py` re-reads the produced datasets every night and runs
**20 automated checks over 17 recorded claims**: that the number shown is the number
in the official file, that the file was really retrieved (HTTP status, byte count and
SHA-256 of those exact bytes recorded), and that the project's rules were respected:

* no day labelled an NWS forecast outside the official horizon;
* no invented daily value beyond that horizon;
* no humidity value presented as an observation when it is a derivation;
* no NOAA **test** message shown as a real warning;
* published means, medians, percentiles and streak percentages recomputed from the
  same file and compared;
* the project's GHCN-derived monthly rainfall means compared against NOAA's
  published monthly normals for the same station;
* every source URL printed on the site traced to a recorded official fetch;
* every quoted official sentence decoded to plain text, exactly as a browser shows
  it, with no HTML entity text left in it.

The result is published as `data/verify.json`, `data/verify_report.txt` and the
**Verification** section of the site. **A failing check stops the data being
published** — the workflow then commits the diagnostics only, so the site keeps the
last verified numbers rather than showing unverified ones.

The mistakes found this way are kept in [`docs/VERIFICATION.md`](docs/VERIFICATION.md),
not deleted. The third-session audit (17 Sep 2026), checking every headline number
against the live product, found and fixed: **a stale ENSO value** (the site showed a
locally derived +0.98 °C from May 2026 while NOAA's published ONI already stood at
**+1.80 °C for JJA 2026**), **hard-coded quotes** from a superseded CPC issuance
(69% where the live discussion says 75%), a NOAA **test** tsunami warning counted as
a real alert, missing humidity on climatology days, and four defects in newly written
code — including function deletion and HTML-entity corruption of every quote — that
the ledger and the offline tests caught before they could ship.

Two further layers run on every push:

* `tests/test_parsers.py` — 52 offline assertions (standard library only, no network)
  over the parsing and derivation code, including the ONI season convention and a
  hand-computable end-to-end aggregation;
* `npm test` — renders the page in jsdom against the committed data and fails if a
  section is empty, the day dialog breaks or the CSV export throws.

---

## How it is built

```
.github/workflows/update-data.yml   nightly at 07:15 UTC (00:15 Pacific) and on push
        │
        ▼
pipeline/main.py                    fetches every official source, records provenance
pipeline/climo.py                   computes the 1991-2020 climatology, ONI, humidity normals
pipeline/build_calendar.py          assembles data/calendar.json + the current forecast block
pipeline/landlord_summary.py        builds data/landlord.json (landlord dashboard)
pipeline/verify_sources.py          rejects any non-official host
pipeline/verify_claims.py           re-derives every headline number; fails the build on error
tests/test_parsers.py               52 offline assertions on the parsing/derivation code
tests/smoke.js                      renders the page headlessly and checks it
        │
        ▼
data/*.json + assets/cpc/*.gif      committed back to the repo (only when verification passes)
        │
        ▼
index.html + assets/js/app.js       static GitHub Pages site, no server, no tracking
```

Because the datasets refresh nightly, days convert from `CLIMATOLOGY` to
`NWS FORECAST` automatically as they come into range, and the ENSO/CPC statements
update with each official issuance — nobody edits a number by hand.

Run it yourself (standard library only):

```bash
python3 pipeline/main.py --outdir data
python3 pipeline/build_calendar.py
python3 pipeline/landlord_summary.py
python3 pipeline/verify_claims.py
python3 tests/test_parsers.py   # offline unit tests, no network needed
npm install && npm test         # headless render of the page
python3 -m http.server 8000     # then open http://localhost:8000
```

---

## Limitations

Summarised here; the full list, with what it would take to fix each one, is in
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) and
[`docs/NEXT_SESSION.md`](docs/NEXT_SESSION.md).

1. **No daily forecast exists beyond the NWS horizon** (~7 days). Days beyond it
   show observed climatology, badged as such.
2. **Two different stations, ~10 miles apart.** Rain/temperature from San Francisco
   downtown `USW00023272`; wind from SFO `72494023234` (more exposed, so an upper
   bound); humidity normals from SFO hourly normals. San Francisco microclimates
   mean the Sunset differs from all of them.
3. **GSOD days are UTC days** (00-24Z ≈ 16:00-16:00 Pacific) while GHCN rain days
   are local days, so the joint wind-and-rain statistic mixes the two day
   definitions. Documented and flagged.
4. **Small samples.** Single-date percentages come from 30 seasons; one season moves
   a date by ~3.3 points. ENSO-stratified samples are 7-12 seasons.
5. **Coastal point-in-polygon.** CPC polygons occasionally miss the coastline; where
   that happens the nearest polygon is used, flagged, and its bounding box is
   published so you can check the map.
6. **Storm Events is a reported-events database**, not a census of storms.
7. **No bias correction or downscaling.** Numbers are used exactly as published.

---

## Repository layout

```
index.html                     the site (landlord dashboard, current forecast, scoreboard, verification)
assets/css/style.css
assets/js/app.js               renders data/*.json; invents nothing
assets/cpc/*.gif               archived copies of official CPC outlook maps
data/*.json                    pipeline output (nightly) + verify.json claim ledger
pipeline/                      fetch + analysis + verification code (stdlib only)
docs/                          sources, methods, verification log, limitations, landlord guide
.github/workflows/             nightly refresh and verification gate
```

## Disclaimer

Independent hobby project. Not affiliated with or endorsed by NOAA, NWS, NCEI, CPC
or the U.S. Census Bureau. **For life-safety decisions use
[weather.gov](https://www.weather.gov) or [weather.gov/mtr](https://www.weather.gov/mtr)
directly.**
