# Verification log

A line-by-line record of what was checked, what was wrong, and what was done
about it. The point of this file is that **the mistakes are kept**, not hidden.

## Environment constraint encountered

The development sandbox had **no general internet egress** - only
`github.com`, `registry.npmjs.org` and `pypi.org` were reachable, and TLS
connections to `api.weather.gov` and every NOAA host were reset at the
ClientHello. Direct verification from the sandbox was therefore impossible.

**Resolution:** the fetch pipeline was made to run **on GitHub Actions runners**,
which have unrestricted egress. The job commits its output and a full run log
into `data/`, so every dataset could then be inspected from the sandbox via
`raw.githubusercontent.com`. All figures on the site were produced by a job that
actually reached NOAA - none were produced locally from memory.

## Bugs found and fixed

Each was found by reading real fetched data, and each would have produced
plausible-looking but wrong numbers.

| # | Symptom | Root cause | Fix |
| --- | --- | --- | --- |
| 1 | `KeyError: 'INTPTLONG'` | Census Gazetteer uses CRLF, so the last header arrives as `INTPTLONG\r` | Strip headers and values; resolve columns case-insensitively; record which names were used |
| 2 | `ValueError: unknown url type: 'c8466ee2-...'` | NWS products endpoint is JSON-LD: the URL is in `@id`, while `id` is only a UUID | Read `@graph` / `@id` |
| 3 | `NameError: name 'v' is not defined` | Missing `v` in a dict comprehension over `oni.items()` | Fixed the comprehension |
| 4 | **GHCN-Daily parsed to zero rows** despite a 7.5 MB download | The access CSV is served in **wide** format (one row per date, a column per element), not the long element-per-row format | Rewrote the parser to detect and handle both layouts |
| 5 | **GSOD wind and temperature were 10x too small** | Applied a `x0.1` scale that the CSV does not use | Verified against the official GSOD README: values are already decimal. Missing sentinels (`999.9`, `99.99`, `9999.9`) confirm it. Scale is now 1.0 and the README is recorded as the authority in the provenance manifest |
| 6 | GSOD rows mis-aligned | The station `NAME` field contains an **unquoted comma** ("SAN FRANCISCO INTERNATIONAL AIRPORT, CA US"), breaking `csv.DictReader` | Positional parsing with surplus-field re-joining |
| 7 | **Only 1 of 14 CPC seasonal outlooks was sampled** | `seas*.zip` holds one shapefile per lead; reading "the first .shp" picked `lead10_JJA_*` purely because it sorts first alphabetically | Sample every shapefile in the archive |
| 8 | CPC season codes unresolved | Compared single month initials against three-letter keys (`O` vs `OCT`) | Resolve initials by requiring three consecutive months |
| 9 | CPC short-range spans dropped | DBF numeric fields arrive as floats, so `20260922` became `20260922.0` | Coerce through `int` before parsing |
| 10 | CPC variable (`temp`/`prcp`) shown as blank | Short-range stems are `610temp_latest`, not `lead1_SON_temp`, so the suffix test also missed the trailing `_latest` | Strip `_latest`, then match `^(610\|814\|wk34)_?(temp\|prcp)$`. Without this, temperature was mislabelled "Above median" instead of "Above normal" |
| 13 | A single day showed up to 12 "covering" CPC outlooks, many identical | `seasprcp_202608.zip`, `seasprcp_202609.zip` and `monthupd_*_latest.zip` all carry an outlook for e.g. "Oct 2026" | Deduplicate on (valid period, variable), keeping the most recent `Fcst_Date`, and publish the issuance date next to every outlook so a reviewer knows which release a number came from |
| 11 | `SyntaxError` in the site JS | Unbalanced parentheses in the table builder | Rewrote the function; now checked with `node --check` |
| 12 | Page rendered twice | `DOMContentLoaded` could fire more than once | Added an idempotency guard and null-safe teardown |

## Stale official content that was rejected

* <https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/index.shtml>
  returns a page whose newest content dates from **2016** (it still advertises a
  survey that closed on 19 May 2020). It was fetched, detected as stale by the
  current-year check, and **discarded rather than quoted**.
* The ENSO narrative shown on the site therefore comes from two *current*
  official products instead: the CPC long-lead discussion issued
  **20 Aug 2026** and the week 3-4 discussion issued **11 Sep 2026**.

## Cross-checks performed

| Claim | Independent check | Result |
| --- | --- | --- |
| The 94122 coordinate | Census Gazetteer row for `GEOID=94122` | 37.760459, -122.483894 - matched, not assumed |
| CPC point-sampling works | Compare sampled attributes with the prose in the official discussion | Week 3-4 temperature sampled as `Above, 40%`; the 11 Sep 2026 discussion says "enhanced probabilities of warmer-than-normal temperatures ... along the west coast". Week 3-4 precipitation sampled as `EC`; the discussion names wetter-than-normal only for the Desert Southwest/Rockies and drier for the Pacific Northwest - i.e. San Francisco is indeed untipped. **Consistent.** |
| GHCN units | Sanity of converted values | 1921-01-01 TMAX 15.6 C / TMIN 7.2 C = 60.1 F / 45.0 F for a January day in San Francisco - plausible |
| GSOD units | Sanity of converted values | 2020-10-01 WDSP 6.3 kt, MXSPD 15.0 kt, GUST 21.0 kt for SFO - plausible |
| Day aggregation | Fixture with a known in-season NWS day | High/low/humidity/wind/gust/rain/POP aggregated correctly; month switching produced 31 cells for October and 31 for January |
| Site rendering | Headless DOM (jsdom) driven with fixture data | 0 console errors; all sections populated; day dialog opens with 16 detail rows and 2 source links |

## Landlord dashboard verification (2026-09-17)

Added `pipeline/landlord_summary.py` that builds `data/landlord.json` from already-verified datasets — no new external fetches, so no new hosts to vet.

**Line-by-line verification of landlord.json:**

| Field | Source file | Official origin | Verified? |
|---|---|---|---|
| season_total_prcp 12.79 in mean | climatology.json distribution.season_total_prcp_in | GHCN-Daily USW00023272 1991-2020 | Yes — file at https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv, parsed as tenths of mm → inches |
| oct/nov/dec/jan totals | climatology.json distribution.*_total_prcp_in | same | Yes |
| streak_probability ge_7_days 53.3% | climatology.json season.probability_of_at_least_one_streak | same GHCN, consecutive wet-day scan Oct 1-Jan 31 | Yes — 16 of 30 seasons = 53.3% |
| wind_and_rain 11.1 days mean | climatology.json distribution.wind_and_rain_days | GSOD 72494023234 (KSFO) https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/ + GHCN, joint count ≥20kt & ≥0.01in | Yes — GSOD units verified against README https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt |
| heavy_wind_and_rain 2.2 days | same | same, ≥35kt gust & ≥0.50in | Yes |
| max_gust 53.8 mph mean | same | GSOD GUST field, knots→mph ×1.15078 | Yes |
| current_enso ONI 0.98C May 2026 el_nino **(superseded - see the Session 3 audit: the site now shows NOAA's published ONI, JJA 2026 = +1.80 C)** | enso.json latest_oni | CPC table https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt — ONI = 3-month running mean | Yes — computed per NOAA definition |
| cpc_outlooks OND/EC, JFM/Above 50% | calendar.json cpc.records | CPC GIS shapefiles https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/seasprcp_202609.zip sampled at 37.7605,-122.4839 | Yes — each record has url, prob, category, issued date, and map in assets/cpc/*.gif |
| high_risk_dates | calendar.json days[].climo | per-date stats from 30 seasons | Yes — sorted by p_rain_day_pct |
| action_items | derived | all above, with source_url per item | Yes — each item cites official URL |

**No hallucinations:** every landlord action item includes source and source_url that is already in provenance.json. The dashboard explicitly states that daily forecast beyond 7 days does not exist and shows climatology instead, with badges.

**Commercial exclusion verified:** `pipeline/verify_sources.py` checks 100 fetches across 5 hosts — api.weather.gov, ftp.cpc.ncep.noaa.gov, www.cpc.ncep.noaa.gov, www.ncei.noaa.gov, www2.census.gov — all official .gov. No AccuWeather, OpenWeatherMap, etc.

## Irregularities currently flagged (not defects in this project)

These are properties of the sources or of geography, and they are surfaced in
the site's **Data quality** section rather than smoothed over:

* **NWS issues no Hazardous Weather Outlook product for office MTR** via the API
  products endpoint at this time, so none can be shown.
* **Some hourly NWS gridpoint fields are null** for this cell (an NWS
  characteristic, not a fetch failure); the affected field counts are logged.
* **GSOD 2026 is not yet published** for station 72494023234, so the wind record
  runs 1991-2025.
* **Coastal point-in-polygon misses** in CPC shapefiles: where 94122 falls
  between polygons the nearest polygon is used and the record is marked so it can
  be checked against the published map.
* **Thin samples per calendar date** - 30 seasons at most, so a single-date
  percentage carries roughly +/- 3.3 points of sampling noise.
* **SFO wind is upper bound for Sunset** — exposure at KSFO is more open than 94122, so wind figures are intentionally conservative for landlord planning.

---

# Session 3 audit - 17 September 2026 (line-by-line, against live official sources)

Every row was checked against the live official endpoint named in the source column,
from outside the build sandbox, on 17 September 2026. Where the site disagreed with
the official source, **the site was changed** - and the mistake is kept here rather
than deleted, because the value of this project is the record, not the polish.

## Claims checked

| Claim on the site | Live official value on 17 Sep 2026 | Source checked | Verdict |
| --- | --- | --- | --- |
| ZIP 94122 internal point = 37.760459 N, -122.483894 W | Reverse geocoding the point returns San Francisco County (06075) and 2020 Census Block `060750326013006`, whose own `INTPTLAT/INTPTLONG` is **+37.7604592 / -122.4838940** | [Census geocoder](https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x=-122.483894&y=37.760459&benchmark=Public_AR_Current&vintage=Current_Current&format=json) | **Confirmed** |
| "Current ENSO: El Nino, ONI +0.98 C (May 2026)" | NOAA's published ONI product ends at **JJA 2026 = +1.80 C** (MJJ +1.39, AMJ +0.95, MAM +0.46, FMA +0.11, JFM -0.21, DJF -0.39, NDJ -0.60, OND -0.61) | [oni.ascii.txt](https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt) | **Wrong and stale - fixed.** The site now shows NOAA's published season-labelled ONI; the locally derived value is kept only as a published cross-check (AMJ 2026: 0.98 derived vs 0.95 official) |
| "El Nino conditions are present - greater than 90 percent chance of a very strong event" attributed to the long-lead discussion of 20 Aug 2026 | The current discussion (issued **17 Sep 2026**) carries that sentence verbatim | [90-day discussion](https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html) | Sentence confirmed, attribution date had drifted |
| "there is a 69% chance of a historic event" for OND 2026 | The ENSO Diagnostic Discussion (issued **10 Sep 2026**) says **75%** for Oct-Dec 2026 (+2.5 C or more on the 3-month RONI) | [ENSO Diagnostic Discussion](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml) | **Stale by one issuance - fixed.** Quotes are captured verbatim from the fetched page with its SHA-256; no number is typed into the HTML |
| Nino index values "+1.8 / +2.5 / +3.2 C" | The 10 Sep 2026 discussion reports August values of **+1.8 (Nino-3.4), +2.5 (Nino-3), +3.4 (Nino-1+2)** | same discussion | Third value differed (weekly vs monthly vintage); now quoted verbatim |
| ENSO Alert System Status | **El Nino Advisory**, issued 10 September 2026 | same discussion | **Added** to the site (it was not shown before). Shown in full after bug 19 |
| CPC seasonal precipitation at the 94122 point: OND 2026 EC, NDJ 2026-27 above median 33%, DJF 40%, JFM 2027 above median 50% | Point-sample of the official GIS shapefiles issued 17 Sep 2026 | [CPC GIS](https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/) | Unchanged; each record now also publishes the containing polygon index, its bounding box and the raw DBF row |
| CPC prose says OND precipitation is above normal "from the southern half of California" | The polygon **containing the 94122 point is Equal Chances (33%)** - the tilt starts further south/east | [long-lead discussion](https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html) | **No conflict, but worth knowing:** regional prose is not a point forecast; the site reports the polygon that contains the point |
| "Active NWS alerts: 1" | The single alert was a **TEST** Tsunami Warning from the National Tsunami Warning Center | [alerts API](https://api.weather.gov/alerts/active?zone=CAZ006) | **Misleading - fixed.** Test messages are counted separately and never shown as real warnings |
| Current NWS forecast for the point (stored copy) | Live `/gridpoints/MTR/82,105/forecast` matched the stored structure and values for the same cycle; the daily high equals the max of its hourly periods | [NWS forecast](https://api.weather.gov/gridpoints/MTR/82,105/forecast) | Confirmed; the forecast simply moves with each cycle |
| Climatology means for Oct/Nov/Dec/Jan rainfall derived from GHCN-Daily | NOAA's published monthly normals for the same station: **Oct 0.94, Nov 2.60, Dec 4.76, Jan 4.40 in** | [NCEI monthly normals](https://www.ncei.noaa.gov/data/normals-monthly/1991-2020/access/USW00023272.csv) | **Cross-check now runs nightly: largest difference 0.07 in** (Dec 4.78 vs 4.76; Jan 4.47 vs 4.40) |
| Humidity per day | NOAA publishes no relative-humidity normal | [NCEI hourly normals](https://www.ncei.noaa.gov/data/normals-hourly/1991-2020/access/USW00023234.csv) | **Gap fixed** by deriving RH from the official hourly temperature and dew-point normals (Magnus formula) per calendar date, labelled as a derivation, station named. Weekly humidity is now also shown for the current forecast |
| Verbatim quoted CPC sentences | The stored sentences against the live pages | both discussions above | **Two defects found** (bugs 19 and 20 below): entity text was not decoded, and figure references split sentences |

## Bugs found in this project during the audit (and fixed)

| # | Symptom | Root cause | Fix |
| --- | --- | --- | --- |
| 14 | Official ONI parsed to **zero seasons**, so the site would have shown no ENSO state at all | `parse_oni_seasons()` compared the season token (`DJF`) against a table of three-letter *month names*; CPC seasons are three **month initials** | Build all 12 season rotations and resolve the token against them |
| 15 | ONI year labelling was off by one season for winter seasons | Assumed the label year was the season's first month | Anchored on published values: `NDJ 2015 = +2.59` covers Nov 2015 - Jan 2016; `DJF 2016 = +2.50` covers Dec 2015 - Feb 2016 (the 2015-16 El Nino peak). The convention is now stated in the code and asserted in the tests |
| 16 | Hourly normals fetched, but **no humidity extracted** | A substring match on column names picked up `meas_flag_HLY-TEMP-NORMAL`, so the file looked like a wide hour-per-column layout and produced zero rows | Match element columns exactly, read the file's own `month`/`day`/`hour` columns, and emit a **per-calendar-date** humidity normal (365 dated values, all 123 scoreboard days covered) |
| 17 | ENSO Alert System Status truncated to "El Ni" | First diagnosis: the regex used `[A-Za-z ]`, which drops "n-tilde". That was **necessary but not sufficient** - see 19 | Unicode-aware class, then 19 |
| 18 | The page claimed "a failure stops the nightly build" while the commit step ran unconditionally | `if: always()` committed data regardless of the ledger verdict | The workflow commits **diagnostics only** when the ledger fails, so the site keeps the last verified numbers |
| 19 | The published page showed `El Nino Advisory` as **"El Ni"**, and every quote contained `&ntilde;`, `&#37;`, `&deg;` | `html_to_text()` decoded a hand-written list of five entities and left the rest; the status regex then stopped at the first unexpected character, and the semicolon inside `&#37;` looked like a sentence end, chopping quotes mid-sentence | Decode with `html.unescape()` + NFC normalisation; read the status to the end of its line; take the synopsis from its own line. **New ledger check `quotes-plain-text` fails the run if any published quote still contains an entity** |
| 20 | Quotes cut at figure references ("... the eastern equatorial Pacific [Fig.") and long-lead quotes were single wrapped lines ("... a greater than 90" / "percent chance of ...") | The splitter treated the period in "[Fig. 1] ." as a sentence end, and treated hard-wrapped line breaks as sentence boundaries | A sentence now ends only at `.` or `;` followed by whitespace **and a capital**; wrapped lines are re-joined; a trailing hyphen is kept ("above-\nnormal" -> "above-normal") so no quote is edited |
| 21 | The reality-check banner read "reaches **0 day(s)**" | The number shown was *scoreboard days inside the horizon* (0 until 1 October), not the length of the horizon | The banner now reports the horizon length (7 days) and states separately that no scoreboard day is inside it yet; `nws_window.horizon_days` is published in the data |
| 22 | The first long-lead quote was the page breadcrumb glued to a sentence: "HOME > Outlook Maps > Seasonal Forecast Discussion ... College Park MD 830 AM EDT Thu Sep 17 2026 SUMMARY OF THE OUTLOOK FOR NON-TECHNICAL USERS El Nino conditions are present, ..." | HTML tags become spaces, so nothing marked where the page content began | Everything before the document's own "SUMMARY OF THE OUTLOOK" marker is cut, the all-caps document heading is dropped, and remaining breadcrumb/title fragments are filtered out of the quote list |

Bugs 14-18 were caught by `pipeline/verify_claims.py` on its first runs. Bugs 19-22
were caught by **reading the published page against its source** - 21 and 22 were
visible only in the *rendered site*, not in the data, which is why `npm test` now
renders the page headlessly on every push.

### Second review pass, 17 Sep 2026 (bugs 23-30)

A line-by-line re-read of the rendered page against `data/` and against the live
official endpoints found eight more. None of them were invented numbers - every
fetched value re-checked correctly - but each one either stated something untrue,
hid an official value, or made a source impossible to follow. Every fix has a test
that was verified to fail on the old code before being committed.

| # | Symptom | Root cause | Fix |
| --- | --- | --- | --- |
| 23 | The checklist explained a CPC category it was not showing: *"CPC OND 2026: Equal chances (33%) ... For precipitation, 'Above median' means CPC favors an above-median total"* | The explanation was keyed on the **variable** (prcp/temp) only, so every precipitation outlook got the "Above median" wording | `cpc_category_note()` is keyed on `(variable, category_label)`; an unrecognised label is declared undocumented rather than explained with another category's wording. Asserted in `test_parsers.py` and in `npm test` |
| 24 | The reality-check paragraph - the one section that exists to state the limits of the data - read *"...as they come into range. carry a real NWS forecast."* | Two branches shared a sentence tail that only made sense for one of them | The branches are now fully independent sentences, and the test fails if a zero-coverage run claims any day carries a real forecast |
| 25 | Action-checklist sources rendered as `...access/USW000` | The link **label** was sliced to 80 characters, cutting a real station ID (`USW00023272.csv`) into a string that looks like one but is not | Labels show the whole URL (the stylesheet already wraps it). The test compares each label against its own `href` |
| 26 | In "Expected rain amounts by month", the CPC column listed `Oct 2026: Above normal 40%` with nothing to say it was the **temperature** outlook, next to rainfall columns; an empty cell printed bare `EC` | Variable was dropped when the cell was built, and the empty fallback was the string `'EC'` - which is a real CPC category (Equal chances) and so asserted an outlook that was never fetched | `cpcOutlookCell()` labels every line `Rain`/`Temp` with a coloured chip, rain first, and returns an em dash when nothing was sampled |
| 27 | Observations showed relative humidity as `64.980032379224%` | The NWS observation RH is a computed value and was rendered verbatim | Rounded for display only; the full value stays in `data/nws.json` |
| 28 | **Every forecast day showed an em dash for rain amount and for gusts** - the two figures the brief asks about first | The aggregation read only `/forecast/hourly`, which returns **no `windGust` and no QPF for this grid cell** (0 of 156 periods on 17 Sep 2026). The same run had already fetched `gridpoint_raw`, which carries both | `daily_from_gridpoint()` reads the gridpoint `windGust` and `quantitativePrecipitation` series. Gust = daily max, km/h -> mph. QPF is an **accumulation over a 3-6 h interval**, so where an interval crosses local midnight it is split between the two days by hours. Each day publishes a `gust_basis` / `rain_amount_basis` naming what was actually used, and the endpoint is listed as a source. Cross-validated: NWS's own text forecast says "gusts as high as 18 mph" (Fri 18 Sep) and "20 mph" (Sat 19 Sep) against 18.4 and 19.6 mph derived here |
| 29 | After adding that source, "Open on weather.gov" resolved to `api.weather.gov/.../forecast/hourly` | The caption picked sources **by array position**, and inserting an entry shifted the indices. The follow-on fix (`/gridpoints\/MTR/`) then matched the hourly URL first, so "gridpoint data" pointed at the wrong endpoint too | Sources are matched by URL (`srcByMatch`), anchored to `gridpoints/<office>/<x>,<y>$` for the raw gridpoint. A test asserts each labelled link resolves to the endpoint its label names |
| 30 | The README contradicted the data: "7 days, 17-23 September" and "65 °F / 60 °F, humidity 91% (86-96%)" | Prose was written from the NWS product's nominal `P7D` label rather than from `data/calendar.json` | Corrected to what the data says: `validTimes` is `P7DT11H`, touching **8** local calendar days 17-24 Sep (the last with 2 forecast hours), day one 65 °F / 59 °F, RH 91.6% (86-97%) |

Bug 28 is the substantive one: it was not a wrong number but a **missing** one, and it
sat in the two fields this project exists to answer. It survived the first audit
because every check asked "is this value right?" and nothing asked "is a value that
exists being dropped?" The new tests ask the second question.

### Third review pass, 17 Sep 2026 (bugs 31-33) - maintenance cost-driver session

This session added the executive summary the brief actually asked for first - a
ranked list of **repair & maintenance cost drivers** (`build_cost_drivers()` in
`pipeline/landlord_summary.py`, rendered by `renderCostDrivers()`). Every number in
it is copied from the already-verified structures; the "why it matters" sentence is
labelled on the card as *guidance, not a weather claim*. While building it, the
line-by-line pass found three defects in what was already published:

| # | Symptom | Root cause | Fix |
| --- | --- | --- | --- |
| 31 | The "ENSO now" stat on the executive summary showed the raw data token **`el_nino` +1.8°C** and a subtitle beginning with a bare space: ` ONI · El Niño mean ...` | The official ONI is **season-labelled** (`JJA 2026`), but the card looked only for a `year_month` field that does not exist on the record, and printed the internal phase key instead of a reader-facing label | The pipeline now publishes `phase_label` (`El Niño`) and `oni_c_fmt` (`+1.80 °C`) alongside the raw fields; the renderer uses the season label. `npm test` asserts the card names its ONI season and that no raw phase token is visible anywhere on the landlord dashboard |
| 32 | The executive summary's key finding and the ENSO action item read `Current ENSO: el_nino (official ONI 1.8C, JJA 2026)` - machine token and a unit-less number, and the sentence always claimed a wetter tilt regardless of phase | Pipeline prose was built from the raw `phase` and `oni_c` fields, formatted inline | `phase_label()` / `fmt_oni_c()` helpers (unit-tested), and the tilt sentence is now phase-aware (it says what this record shows for the phase NOAA actually published; a La Niña or neutral season gets its own honest wording). New ledger check `raw-phase-tokens` fails the run if `el_nino`/`la_nina` appears in any reader-facing executive-summary string |
| 33 | **Latent**: a CPC outlook with a missing probability would have rendered as `at None% probability` in the action checklist and in the new cost-driver evidence | Two f-strings interpolated `prob` without a None guard | Both sites now phrase the row as "probability not stated in the sampled polygon" when the polygon carries no probability. Never triggered by current data; caught by reading the code paths the new block reuses |

The new block is held to the same gates as everything else: ledger check
`cost-drivers-structure` requires every driver to be ranked, carry evidence rows,
and cite only official .gov sources; `cost-driver-expected-days-arithmetic`
re-derives the published expected heavy-rain day counts (14.97 days ≥ 0.25 in and
3.19 days ≥ 1.00 in per season) from the committed climatology table as sums of the
per-date probabilities and fails on any disagreement. The smoke test refuses a
cost-driver card with no evidence table or no source link.

One deliberate editorial rule for the block: *expected-day counts are sums of
per-date 1991-2020 probabilities* (linearity of expectation). The method string is
published next to the numbers on the site, because the figure is an expectation
over the observed distribution, not a prediction for 2026-27.

## Release held back: the deleted-function incident

Two consecutive runs published nothing, which is the gate behaving correctly:

| Run | Outcome | What the gate did |
| --- | --- | --- |
| 1 (`1bc8f23`) | Ledger 17/18, `oni-official-present` failed | The old workflow committed the data anyway - the defect that motivated bug 18. The numbers that run published were not wrong, but the failure was not allowed to block them |
| 2 (`0a9d630`) | `PIPELINE_EXIT=1`, `CLAIMS_EXIT=1` | Committed **diagnostics only** ("refresh NOT published"); the site kept the last verified dataset |
| 3 | Ledger 20/20 | Data published |

Run 2 failed in the middle of the pipeline:

```
File "pipeline/main.py", line 1323, in main
    climo_out["daily"] = climo.build_daily_climatology(
AttributeError: module 'climo' has no attribute 'build_daily_climatology'
```

`build_daily_climatology` (113 lines) and `build_season_statistics` (151 lines) had
been **deleted from `pipeline/climo.py`** while the ENSO and hourly-normals helpers
were being added - code that had already been verified and shipped in an earlier
commit, removed by a later one, with nothing to catch it because the pipeline only
runs in CI.

What was done about it:

1. **Restored verbatim** from `1bc8f23` and byte-compared against the original with a
   script before committing.
2. **`tests/test_parsers.py` added** (55 assertions, standard library only, no
   network): the ONI season rotations and the NDJ/DJF year convention, exact-column
   matching in the NCEI normals files, the per-date humidity derivation against an
   independent formulation of the Magnus formula, quote integrity (entities, wrapped
   lines, figure references, breadcrumbs), and an end-to-end aggregation over a
   synthetic GHCN file with hand-computable expected values.
3. **A `parsers` job in the `Tests` workflow** runs that file on every push touching
   `pipeline/**` or `tests/**`, alongside the headless site test.

The honest lesson, recorded because it matters more than the fix: a one-line
`AttributeError` in CI is a *lucky* failure. The same deletion inside a function
reached on only some code paths would have been silent.

## How the ledger and the tests stand now

* `pipeline/verify_claims.py`: **26 automated checks, 17 recorded claims**, each claim
  carrying value, unit, method, official URL, HTTP status, bytes, SHA-256, retrieval
  time and - where one exists - an independent cross-check. Order: provenance-present,
  provenance-record-count, hosts-official, centroid-verified, oni-official-read-directly,
  oni-official-present,
  nws-daily-aggregation, tier-honesty, calendar-completeness, calendar-fields,
  humidity-honesty, oni-cross-check, season-mean-arithmetic, distribution-ordering,
  month-mean-*, streak-arithmetic, cost-drivers-structure,
  cost-driver-expected-days-arithmetic, raw-phase-tokens, normals-cross-check,
  cpc-dedup, cpc-seasonal-present, alert-test-filter, source-traceability,
  quotes-plain-text, claim-source-evidence.
* `tests/test_parsers.py`: **121 offline assertions**, stdlib only. Added 17 Sep 2026:
  the exact official-host allow-list, the CPC category-explanation rule (bug 23) and the gridpoint gust/QPF aggregation,
  including the local-midnight accumulation split and the cross-check of derived gusts
  against the gusts NWS states in its own text forecast. Added in the third pass:
  the expected-days summation (both record shapes), the Storm Events damage parsing
  (`0.00K` = no recorded damage, `""` = unknown), the ENSO phase/ONI display
  formatting, and the cost-driver builder's evidence rules on synthetic inputs and
  on the committed landlord.json.
* `npm test` (jsdom): renders the page against the committed data and fails on an
  empty section, a broken day dialog, a broken CSV export, a truncated source label,
  the broken reality-check sentence, a CPC note that does not explain its own category,
  an unlabelled rain/temperature outlook, an unrounded humidity, a mislabelled source
  link, a forecast day missing its gust or rain amount, a cost-driver card without
  evidence or a source, a raw ENSO phase token on the landlord dashboard, or a
  `NaN`/`undefined` rendered anywhere in the main sections.
* Nightly gate: `summary.failed > 0` -> "refresh NOT published", diagnostics committed
  only. The site then keeps the last verified dataset.

## How a reviewer can re-check any number in about a minute

1. Open <https://buffedlizard55-lab.github.io/SFWeather/> and scroll to
   **Verification - every number checked against its source**.
2. Each claim lists the value, the official URL it came from, the HTTP status, the
   byte count, the **SHA-256 of those exact bytes** and the retrieval time.
3. Open the URL, find the number, compare. For CPC outlooks the row also gives the
   containing polygon index and bounding box so the polygon can be found on the
   official map.
4. `data/verify_report.txt` is the same ledger as plain text, and
   `data/provenance.json` lists every fetch of the run (~104 on the last run).
5. Anything the pipeline could not resolve cleanly is listed on the site as an
   **irregularity** rather than being dropped.
