# SFWeather — San Francisco 94122, Oct 2026 → Jan 2027

A **source-verified** rainy-season outlook for ZIP **94122** (Sunset / Inner Sunset,
San Francisco), built for the questions a landlord actually asks: *will it rain, for
how many days in a row, how much, how hard will the wind blow, and will wind and rain
arrive together?*

Everything is produced by an automated nightly pipeline from **free, public,
official** sources — NOAA / National Weather Service, NCEI, the Climate Prediction
Center and the U.S. Census Bureau — and every published number is re-derived from its
source file and re-checked before it is allowed onto the page.

**Live site:** <https://buffedlizard55-lab.github.io/SFWeather/>

---

## What does the honest answer look like?

**Nobody can tell you today whether it will rain on 14 January 2027.** No official
product forecasts a specific day that far out. The NWS publishes a daily forecast
whose official `validTimes` is **7 days 11 hours** (`P7DT11H`) — as of this run,
17 Sep 2026 14:00 UTC through 25 Sep 2026 01:00 UTC, which touches **8 local
calendar days, 17–24 September 2026**, the last of them with only 2 forecast
hours. Beyond that, the official products are *probabilities for a period*
(6–10 days, 8–14 days, weeks 3–4, a month, a 3-month season), never a number for
one named day.

So the site does not invent one. Each of the 123 days from 1 Oct 2026 to 31 Jan 2027
carries one of two honest badges:

| Badge | What it means |
| --- | --- |
| `NWS FORECAST` | The day is inside the official NWS forecast horizon. High, low, humidity, wind, gusts, rain chance and rain amount are the actual NWS gridded forecast for this ZIP's grid cell. |
| `CLIMATOLOGY` | The day is beyond the horizon. Every figure is the **observed 1991–2020 record for that calendar date** at a named NOAA station — how often it rained, how much, how windy — and is labelled as such. Not a forecast. |

CPC outlooks are attached to the days they validly cover, as *probabilities for the
period*, and are never converted into daily numbers.

---

## The landlord summary (all values from the current dataset)

**Typical rainy season, 1 Oct – 31 Jan, San Francisco downtown gauge `USW00023272`
(1991–2020, n = 30 seasons)**

| Question | Answer |
| --- | --- |
| How much rain in the season? | mean **12.79 in**, median **13.26 in**; wettest 22.82 in (1997–98), driest 1.71 in (2013–14); 10th–90th percentile 6.38–18.59 in |
| How many wet days? | mean **34.5** days (range 7–55) |
| Will we get a long wet spell? | **96.7%** of seasons had a run of ≥3 consecutive wet days, **80.0%** ≥5 days, **53.3%** ≥7 days, **23.3%** ≥10 days. The longest run averaged 7.3 days (max 17) |
| Rain *and* strong wind together? | mean **11.1 days per season** with rain and ≥20 kt wind at SFO, **2.2 days** with ≥0.50 in and a ≥35 kt gust; strongest gust of the season averages 53.8 mph (max 70 mph) |
| Does El Niño matter? | In this record, El Niño seasons averaged **14.23 in** (n=11), neutral 13.31 in (n=7), La Niña 11.16 in (n=12) — wetter on average, with huge spread |

**Current ENSO state (NOAA's own product, not a re-derivation)**

| | |
| --- | --- |
| Latest published ONI | **JJA 2026: +1.80 °C** — El Niño, *strong* |
| Official Alert System Status | **El Niño Advisory** (CPC ENSO Diagnostic Discussion, issued 10 September 2026) |
| CPC statement, verbatim | "El Niño is strengthening, with a greater than 90% chance of a very strong event during the Northern Hemisphere fall and winter 2026-27." |
| CPC historic-event probability | "During the October-December 2026 season, there is a 75% chance of a historic event…" (verbatim, same page) |
| Independent cross-check | The project's own 3-month mean from the raw Niño-3.4 table gives 0.98 °C for AMJ 2026 against NOAA's published 0.95 °C — a 0.03 °C difference, published on the site |

**Today's actual forecast** (the only real day-by-day forecast that exists): the
8 local calendar days the NWS hourly grid reaches, with day/night values aggregated
to local days — e.g. 17 Sep 2026: **65 °F / 59 °F**, humidity 91.6% (86–97%), rain
chance 0%, max wind 8 mph, from 10 hourly grid values. These are the values on the
site; they are re-derived from the same NWS grid file on every run.

**Where the numbers come from** — every one: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md),
and on the site under *Verification*, with the URL, HTTP status, byte count, SHA-256 and
retrieval time of the exact file.

---

## How "no hallucination" is enforced

| Layer | What it does |
| --- | --- |
| `pipeline/verify_sources.py` | Fails the build if any host outside the official list is used. There is no path to a commercial or unofficial source. |
| `pipeline/verify_claims.py` | Re-derives every headline number from the same file and checks the project's rules: no `NWS FORECAST` badge outside the official horizon, no invented daily value, no humidity presented as an observation when it is a derivation, no NOAA *test* message shown as a real alert, quotes are plain text with no HTML entities left in them, and every source URL printed on the site is traced to a recorded fetch. |
| Workflow gate | `summary.failed > 0` → **the run publishes nothing**. It commits diagnostics only ("refresh NOT published") and the site keeps the last verified dataset. |
| `data/provenance.json` | The full fetch log: every URL, status, size, SHA-256, timestamp. |
| `data/verify.json` + `verify_report.txt` | The claim ledger as machine-readable JSON and as plain text. |
| `tests/test_parsers.py` | 85 offline assertions (stdlib only, no network) on the parsing/derivation code — the ONI season convention against the published file, exact column matching in the NCEI normals, the humidity derivation against an independent Magnus formulation, quote integrity, an end-to-end aggregation over a synthetic file with hand-computable expected values, the rule that a CPC explanation must describe the category actually displayed, and the NWS gridpoint gust/QPF aggregation including the local-midnight accumulation split. |
| `tests/smoke.js` (`npm test`) | Renders the whole page in jsdom against the committed data and fails on an empty section, a broken day dialog or CSV export, a truncated source label, a mislabelled source link, a CPC note that does not explain its own category, an unlabelled rain/temperature outlook, an unrounded humidity, or a forecast day missing its gust or rain amount. |

**Every forecast day can be checked by hand:** open the day's dialog, follow the
source link, and compare. The site's *Verification* section lists all 17 recorded
claims (21 checks) with their evidence, and *Irregularities* lists anything the
pipeline flagged rather than smoothed over.

---

## Sources (all free, all official, no API key)

| What | Where |
| --- | --- |
| ZIP boundary / centroid | [U.S. Census Gazetteer 2024](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip) → ZCTA 94122 internal point 37.760459, −122.483894 (cross-checked with the [Census geocoder](https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x=-122.483894&y=37.760459&benchmark=Public_AR_Current&vintage=Current_Current&format=json)) |
| Daily/hourly forecast | NWS [gridpoints MTR 82,105](https://api.weather.gov/gridpoints/MTR/82,105/forecast/hourly) and [human-readable version](https://forecast.weather.gov/MapClick.php?lat=37.760459&lon=-122.483894&unit=0&lg=english&FcstType=text&TextType=1) |
| Wind gusts and rain amounts in the forecast | NWS [raw gridpoint data](https://api.weather.gov/gridpoints/MTR/82,105) — the `windGust` and `quantitativePrecipitation` series. The hourly forecast product carries **neither** for this grid cell (0 of 156 periods on 17 Sep 2026), so these two fields come from here, and each day publishes the basis it actually used. |
| Alerts, observations, forecaster discussion | NWS [alerts for CAZ006](https://api.weather.gov/alerts/active?zone=CAZ006), [station observations](https://api.weather.gov/stations/SFOC1/observations/latest), [Area Forecast Discussion](https://api.weather.gov/products/types/AFD/locations/MTR) |
| 6–10 day, 8–14 day, weeks 3–4, monthly, seasonal outlooks | CPC [GIS shapefiles](https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/) (the containing polygon is sampled at the 94122 point and its index, bounding box and raw DBF row are published) |
| ENSO number | CPC **official ONI product** — [oni.ascii.txt](https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt), read directly |
| ENSO status and seasonal thinking | [ENSO Diagnostic Discussion](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml), [8–14 day](https://www.cpc.ncep.noaa.gov/products/predictions/814day/), [weeks 3–4](https://www.cpc.ncep.noaa.gov/products/predictions/WK34/), [long-lead discussion](https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html), [30-day](https://www.cpc.ncep.noaa.gov/products/predictions/30day/) |
| Rain and temperature history | NCEI [GHCN-Daily `USW00023272`](https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv) (San Francisco downtown, 1921→present) |
| Wind and gust history | NCEI [GSOD `72494023234`](https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/) (SFO) — read the [units README](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt) |
| Independent climatology cross-check | NCEI [1991–2020 monthly normals `USW00023272`](https://www.ncei.noaa.gov/data/normals-monthly/1991-2020/access/USW00023272.csv) |
| Humidity normals | NCEI [1991–2020 hourly normals `USW00023234`](https://www.ncei.noaa.gov/data/normals-hourly/1991-2020/access/USW00023234.csv) — relative humidity is **derived** by the Magnus formula from the official hourly temperature and dew-point normals and labelled as a derivation |
| Storm severity history | NCEI [Storm Events](https://www.ncdc.noaa.gov/stormevents/) for San Francisco County |

### Why AccuWeather is not used

The brief listed AccuWeather as an acceptable source. It is deliberately **excluded**
here, and the exclusion is a documented deviation: it requires a paid API key, its
terms do not allow redistributing its data, and — most importantly for this project —
its output cannot be re-derived and checked line by line against a public file the way
a NOAA product can. Including it would create numbers on the page that a reviewer can
only *trust*, not *verify*. Anyone who wants it as a second opinion should read it at
the source; this site will not republish what it cannot check.

---

## Caveats (full list: [docs/LIMITATIONS.md](docs/LIMITATIONS.md))

* Climatology is **not a forecast** for a specific day — it is the observed
  distribution for that date over 30 seasons.
* Wind is measured at **SFO, ~10 mi away and more exposed** than the Sunset, so the
  wind figures are an upper bound for 94122. Rain/temperature come from the downtown
  gauge, ~1.5 mi away.
* GSOD wind days are **UTC days** (≈16:00–16:00 Pacific) while GHCN rain days are
  local days, so the joint wind-and-rain statistic pairs a local-day rain total with a
  UTC-day wind figure.
* CPC outlooks are **regional**. The site reports the polygon that actually contains
  the 94122 point and publishes its geometry, so the reader can see whether the tilt
  covers the coast or starts inland.
* ENSO-stratified means rest on 7–12 seasons — indicative, not precise.
* No downscaling, no bias correction: numbers are used exactly as published.

---

## Repository layout and how to run it

```
pipeline/main.py            fetch every official source, record provenance, dump data/*.json
pipeline/climo.py           parsing + climatology, ENSO helpers, humidity derivation
pipeline/build_calendar.py  builds data/calendar.json (scoreboard + current forecast)
pipeline/landlord_summary.py builds data/landlord.json (landlord dashboard)
pipeline/verify_sources.py  rejects non-official hosts
pipeline/verify_claims.py   re-derives every headline number; writes verify.json/report
pipeline/lib_*.py           shared fetch/shapefile helpers
assets/js/app.js            renders the data (invariant: it never invents a number)
assets/css/style.css        styles
index.html                  the page
data/                       committed datasets + provenance + verification ledger
docs/                       VERIFICATION.md (claims audit), DATA_SOURCES.md, LIMITATIONS.md, NEXT_SESSION.md
tests/                      test_parsers.py (offline), smoke.js (jsdom render)
.github/workflows/          update-data.yml (nightly), site-test.yml (on push)
```

Run the whole thing locally (Python 3.11+, standard library only):

```bash
python3 pipeline/main.py --outdir data
python3 pipeline/build_calendar.py
python3 pipeline/landlord_summary.py
python3 pipeline/verify_claims.py
python3 tests/test_parsers.py       # offline unit tests
python3 -m http.server 8000         # open http://localhost:8000
```

The nightly job runs at **07:15 UTC (00:15 Pacific)**, after the NWS 00Z cycle, and
commits the refreshed datasets. A push to any branch also triggers it.

---

## Documentation

* [docs/VERIFICATION.md](docs/VERIFICATION.md) — the claim-by-claim audit, including
  every bug this process has caught and how it was fixed.
* [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) — every endpoint, with what it is used
  for and the licence/attribution position.
* [docs/LIMITATIONS.md](docs/LIMITATIONS.md) — what cannot be answered with official
  data, and what it would take to fix each one.
* [docs/NEXT_SESSION.md](docs/NEXT_SESSION.md) — handoff for the next working session.
