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
* **SFO wind is an SFO reference value, not a bound for the Sunset** — earlier passes wrote "upper bound" here; no official source in this project establishes the direction, so the claim was withdrawn as bug 74 (session 14, below).

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

### Fourth review pass, 17 Sep 2026 (bugs 34-39) - published normals session

This pass added the site's second, independent answer to the landlord's rain
questions: NOAA NCEI's **published** 1991-2020 daily normals for the same station,
shown date by date next to this project's own count. It also produced the sharpest
defect of the session - and then produced a second defect in the guard written to
catch the first one, which is the more useful thing to record.

| # | Symptom | Root cause | Fix |
| --- | --- | --- | --- |
| 34 | The limitations prose said wind is measured "about 10 miles" from 94122 while the pipeline's own recorded great-circle distance is **11.9 mi** | The number was typed into the sentence; the pipeline had started computing it but the prose was never switched over | The caveat is now built from `climatology.meta.station_distance_mi.wind_ksfo` (computed from the station coordinates the NWS returns), so it prints 11.9. All static copies of "~10 miles" in `index.html`, `landlord_summary.py` and `docs/LANDLORD_GUIDE.md` updated to the published value |
| 35 | The published-vs-derived comparison produced **no pairs at all** (silently), so the page's cross-check section was empty | `pipeline/build_calendar.py` had its own copy of the aggregation, keyed on `p_pcp_ge_001in_pct` / `_010in_` / `_100in_`. Those keys were also being read by the renderer. The official columns are `GE001HI` = >= **0.01** in, so the real keys are `..._0p01in_pct`, `..._0p25in_pct`, `..._1p00in_pct` - the duplicate aggregator had drifted from the parser and matched nothing | One implementation, in `climo.compare_daily_normals`, called by `build_calendar.py`. The renderer's labels are generated from the file's own `layout.thresholds_in` rather than typed, so a column and its label cannot drift apart again |
| 36 | `AttributeError: 'dict' object has no attribute 'compare_daily_normals'` | `import climo` at module scope was **shadowed inside `main()`** by a local `climo = load("climatology.json")` - the same trap that had already bitten once | The module is imported as `climo_lib` in both `build_calendar.py` and `verify_claims.py`, with the reason in a comment |
| 37 | **123 dates published `-9999.00 in` as a precipitation percentile.** The site would have shown NOAA's missing-value sentinel as a reading | NCEI writes `-9999` for a percentile it cannot compute (a calendar date too dry to have a wet-day percentile). `_DLY_MISSING` listed the positive GHCN/GSOD sentinels (``9999.9``, ``99999``, ...) and ``M`` only | The guard is now a literal list **plus a numeric floor**: any value <= -900 is a sentinel. New ledger check `official-daily-normals-no-sentinels` re-checks every published value against ranges stated from outside the data (a share of years is 0-100 %, a percentile cannot be negative, a normal temperature is -50..130 F) |
| 38 | **The check written for bug 37 could not fire.** With `-9999` injected back into the dataset the ledger still passed it | The rule was written as `key.endswith("_pctl_in")`, but the published key is `pcp_50pctl_in` - there is **no underscore before `pctl`**, so the test matched nothing | The rule moved to `climo.implausible_normals_value()` and is unit-tested in `tests/test_parsers.py`. The failure was reproduced by injecting a sentinel into a scratch copy of the dataset and confirming the check flips to FAIL, before the fix was kept |
| 39 | Every climatology day cell labelled its amount `rain 0.01"`, which reads as a **forecast** for a date 30 years of record cannot forecast | One template served both tiers; only the probability was worded per tier | A climatology tile now says `mean`, a forecast tile says `rain`, and `tests/smoke.js` fails if a climatology cell uses the word `rain` (verified to fail on the old wording before being committed) |

Bug 37 is the one to keep in mind: it was invisible in every offline fixture, and
only appeared when the **first real dataset produced by CI** was read line by line.
Fixture data cannot prove a parser is right about a publisher's conventions - only
the publisher's own file can.

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

* `pipeline/verify_claims.py`: **47 automated checks, 18 recorded claims**, each claim
  carrying value, unit, method, official URL, HTTP status, bytes, SHA-256, retrieval
  time and - where one exists - an independent cross-check. Order: provenance-present,
  provenance-record-count, hosts-official, centroid-verified, oni-official-read-directly,
  oni-official-present,
  nws-daily-aggregation, tier-honesty, calendar-completeness, calendar-fields,
  humidity-honesty, oni-cross-check, season-mean-arithmetic, distribution-ordering,
  month-mean-*, streak-arithmetic, cost-drivers-structure,
  cost-driver-expected-days-arithmetic, raw-phase-tokens, normals-cross-check,
  cpc-dedup, cpc-seasonal-present, alert-test-filter, source-traceability,
  quotes-plain-text, claim-source-evidence, official-daily-normals-present,
  official-daily-normals-no-sentinels, official-daily-normals-traceable,
  official-daily-normals-cross-check, official-daily-normals-expected-days,
  phase-label-present.
* `tests/test_parsers.py`: **167 offline assertions**, stdlib only. Added 17 Sep 2026:
  the exact official-host allow-list, the CPC category-explanation rule (bug 23) and the gridpoint gust/QPF aggregation,
  including the local-midnight accumulation split and the cross-check of derived gusts
  against the gusts NWS states in its own text forecast. Added in the third pass:
  the expected-days summation (both record shapes), the Storm Events damage parsing
  (`0.00K` = no recorded damage, `""` = unknown), the ENSO phase/ONI display
  formatting, and the cost-driver builder's evidence rules on synthetic inputs and
  on the committed landlord.json. Added in the fourth pass: a 366-date NCEI-shaped
  daily-normals fixture with hand-computable values (per-threshold semantics,
  monotonicity, blank != zero, an unknown layout degrading to ``usable: false``,
  the comparison's signs and its >10-point flag rule), the sentinel rules
  (**-9999** and the numeric floor, keyed on the real ``pcp_50pctl_in`` shape) and
  the published-vs-derived blocks on the committed scoreboard.
* `npm test` (jsdom): renders the page against the committed data and fails on an
  empty section, a broken day dialog, a broken CSV export, a truncated source label,
  the broken reality-check sentence, a CPC note that does not explain its own category,
  an unlabelled rain/temperature outlook, an unrounded humidity, a mislabelled source
  link, a forecast day missing its gust or rain amount, a cost-driver card without
  evidence or a source, a raw ENSO phase token on the landlord dashboard, or a
  `NaN`/`undefined` rendered anywhere in the main sections, or a climatology day
  tile that labels a 30-year mean as `rain`.
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

## Bugs found in the 18 Sep 2026 session (pass 5)

These were found by auditing the rendering and the verification layer rather
than the fetching layer — the theme of this pass is *guards that cannot fail*.

| # | Symptom | Root cause | Fix |
| --- | --- | --- | --- |
| 40 | The new `no-replacement-characters` ledger check was written and immediately failed on the committed data | It was right: `storm_events.json` carried `5.46\ufffd\ufffd\ufffd in` in the 31 Dec 2022 narrative. NCEI's Storm Events CSVs are CP1252 and were being decoded with `errors="replace"` | `lib_fetch.decode_text()` tries strict UTF-8 first and falls back to the publisher's legacy encoding, recording which was used as an irregularity. The check now stays in the ledger so an encoding regression cannot be committed again |
| 41 | `bottom-line-numbers-traceable` passed when a quoted figure was deliberately corrupted from 12.79 in to 19.42 in | The candidate set included `f"{v:.0f}"` and the test was a plain substring search, so 12.79 "matched" the **13** inside an unrelated 13.26 | Candidates are now matched as standalone numbers with `(?<![\d.])…(?![\d.])`. The same defect was in the U+FFFD sweep, which used `json.dumps` without `ensure_ascii=False` and so searched for a character that was always escaped |
| 42 | `no-replacement-characters` still passed after the `ensure_ascii` fix, and the mutation harness reported every broken fixture as "pass" | The verifier had crashed (a function removed by an earlier edit was still being called), so the harness was reading the **previous** run's `verify.json` — a stale all-pass file | The harness deletes `verify.json` from each fixture and now raises if the verifier did not write a new one |
| 43 | A blanked-out figure in the executive summary simply **disappeared** from the page, leaving the answer looking complete | `renderBottomLine` filtered out any number row whose value was null | Rows are kept and render as an em dash; a smoke guard compares the rendered row count against the data, so a vanished row is now a test failure |
| 44 | The smoke guards for "CPC baseline is labelled" and "severity counters are rendered" never fired on any mutation | Both derived their expectation from the very field under test (the baseline flag; a non-null mean), so removing the flag also removed the reason to check it | The CPC guard now derives the expectation from CPC's raw `Cat`/`Prob` fields; the wind guard keys on the *presence* of the counter and asserts the em-dash behaviour for a null mean, plus an `app.js` mutation that removes the row entirely |
| 45 | A stale `days_covered` key would have read as `undefined` and printed "0 day(s)" with no test catching it | `nws_window.days_covered` was renamed to `scoreboard_days_in_horizon` but nothing pinned the rename | A smoke guard fails if the old key is present without the new one; a ledger check fails if *either* file publishes a bare `days_covered` again |
| 46 | `Days ≥ 0.01 in per season` read **"not derived"** in the expected-days table although the wet-day count was already published | Two names for one quantity (`wet_days.mean` and a missing `ge_010in_days`), and the table only looked for one of them | The row now reads the published wet-day mean; `published_expected` was renamed from `days_covered` to `dates_compared` so the two meanings cannot collide again |
| 47 | The day dialog's CPC table printed `Above median (33%)` with no baseline caveat, although both CPC tables on the same page flagged it | The dialog had its own copy of the category formatting | The dialog now uses the same `cpcCategoryCell()` helper as the other two tables |

### What the new guards found by themselves

Writing the guards first and then trying to defeat them is what produced bugs 41,
43, 44 and 45. Each guard was falsified by mutating a fixture copy of `data/`
(or of `app.js`) and confirming the test **fails**; a guard that could not be
made to fail was treated as a bug in the guard, not as evidence of correctness.
`severity-counters-arithmetic` is the one guard still in its deferred branch: the
committed datasets predate the severity counters, so it reports "not yet
produced" and will start comparing real values on the next pipeline run.

## Independent re-check of the official claims (18 Sep 2026)

The sandbox cannot reach NOAA directly (see the environment note at the top), so
the re-check below was done by retrieving the official pages through a separate
read-only web client, independent of the pipeline that produced the datasets.
This is the manual-review path the brief asks for: open the link, find the text.

| Claim on the site | Official page | What it says now | Verdict |
| --- | --- | --- | --- |
| ENSO Alert System Status is **El Niño Advisory** | [CPC ENSO Diagnostic Discussion](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml) | "ENSO Alert System Status: **El Niño Advisory**", issued **10 September 2026** | matches |
| The discussion says "El Niño is strengthening, with a greater than 90% chance of a very strong event during the Northern Hemisphere fall and winter 2026-27" | same page, Synopsis | verbatim, including the closing summary sentence | matches (quote is exact) |
| "During the October-December 2026 season, there is a 75% chance of a historic event" | same page | verbatim: "…a 75% chance of a historic event that would exceed the strength of previous El Niño events dating back to 1950 (+2.5°C or more for a 3-month RONI value)" | matches (quote is exact) |
| Niño-3.4 / Niño-3 / Niño-1+2 anomalies are +1.8 / +2.5 / +3.4 °C | same page | "+1.8°C in Niño-3.4, +2.5°C in Niño-3, and +3.4°C in Niño-1+2" | matches |
| The next discussion is due 8 October 2026 | same page | "The next ENSO Diagnostics Discussion is scheduled for 8 October 2026." | matches |
| The CPC long-lead shapefiles the site samples are the current issuance | [CPC GIS data page](https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/) | the 6-10 day index lists `610prcp_20260917.zip` / `610temp_20260917.zip` as the latest, i.e. the 17 Sep issuance the site records | matches |

### What this does and does not establish

It establishes that the *official text* the site quotes and links is the text the
agency is publishing today, and that the issuance dates the site records are the
current ones. It does **not** re-fetch and re-parse the GHCN/GSOD/NCEI files —
those are large binary/CSV products and the pipeline's own SHA-256, byte count and
retrieval time for each one are recorded in `data/provenance.json` and listed on
the page, which is the mechanism for that half of the review. Any figure traced to
a raw file is checkable there in one step: open the URL in the ledger row, download
the file, and compare against the value the row prints.

## Follow-up: the U+FFFD in NCEI's Storm Events file is NCEI's

The first attempt at bug 40 assumed this project's decoder was at fault (the
pipeline had been using `errors="replace"`). It was not, or not only:

* `lib_fetch.decode_text()` prefers strict UTF-8 and reports which encoding it
  used. The 18 Sep run recorded **no encoding fallback** for any Storm Events
  file, i.e. the bytes NCEI serves are valid UTF-8.
* Valid UTF-8 that contains U+FFFD means the replacement character is *in the
  published file* — NCEI's own conversion from CP1252 already destroyed the
  glyph. No decoder can recover it.

The character cannot be restored without guessing, and this project does not
guess. So the pipeline now:

1. removes U+FFFD and NUL from the narrative fields
   (`lib_fetch.strip_unrepresentable`, unit-tested against the exact sentence
   from the real file);
2. publishes `storm_events.json` → `text_integrity` with the count, the affected
   fields and event ids, up to five verbatim snippets around each removal, and
   the reason;
3. records an `info` irregularity saying the same thing, so it appears on the
   site rather than only in the JSON;
4. keeps the hard ledger check that **no U+FFFD may be published at all**, plus a
   new one (`publisher-text-loss-disclosed`) requiring that any removal is
   counted, located, attributed to the publisher, and reported — and that the
   attribution is backed by `encoding_fallback_used == False`. A disclosure that
   blames the publisher while this project's decoder was the cause fails the
   check.

The sentence a reader sees is therefore
`…hit 5.46 in the 24 hours of December 31st, just 0.08 less than 1st place
(11/5/1994) with 5.54.` — verbatim minus the three glyphs NCEI had already lost.

## Validation result: two independent NOAA products agree on storm severity

The severity work was built so that every claim could be checked against a second
official product rather than against this project's own arithmetic. The 18 Sep
2026 run produced the first real comparison, and it is the strongest piece of
evidence on the site:

| Threshold | Method A: this project counting days in `USW00023272` | Method B: sum of NOAA's published per-date percent-of-years (`DLY-PRCP-PCTALL-GE***HI`) | Difference |
| --- | --- | --- | --- |
| ≥ 0.50 in | 8.40 days/season (peak 17) | 8.39 days/season | **+0.01** |
| ≥ 1.00 in | 3.20 (peak 7, 1996-97) | 3.26 | **−0.06** |
| ≥ 2.00 in | 0.50 (peak 2) | 0.51 | **−0.01** |
| ≥ 4.00 in | 0.00 (peak 1) | 0.02 | **−0.02** |

Two different files, two different derivations, same station — within 0.06 days
per season everywhere. The site prints this table and quotes the verdict, and the
`two-method-verdict-recomputable` ledger check re-derives the verdict from the
differences, so the sentence cannot outlive the numbers that justified it.

### A second, independent cross-check

NCEI's Storm Events narrative for 31 December 2022 records "5.46 in in the
24 hours … just 0.08 less than 1st place (11/5/1994) with 5.54". The GHCN-derived
severity record reports `max_daily_prcp_in = 5.54 in`, season **1994-1995** —
i.e. the GHCN file's own wettest day in the window is the 5 November 1994 event,
0.08 in above the 2022 event, exactly as NCEI's storm narrative says. Two
different NCEI products, fetched separately, agree on both the value and the gap.


---

# Session 6 — 18 September 2026 (pass 6): forecaster language, named geography, per-field basis

Two features were added and then reviewed line by line: a scan of the NWS Area
Forecast Discussion for storm language, and a Census reverse geocode that names
the forecast point from evidence instead of by assertion. Both are documented in
`docs/METHODS.md` §14–15 and `docs/LIMITATIONS.md` §15–16.

## Bugs found in this project during this pass (and fixed)

| # | Symptom | Cause | Fix / guard |
| --- | --- | --- | --- |
| 40 | **`docs/LANDLORD_GUIDE.md` rendered two CPC categories as "EC 33%" when the sampled shapefiles said *Above normal* at 33.0%** — the exact baseline-honesty violation the site is required to avoid, and hand-typed numbers in a file the ledger cannot re-derive | The guide carried a hand-written table of CPC outlook values (manual input, which the brief forbids) and drifted from `data/landlord.json` | The table was **removed**, not corrected: prose now points at the site card, `cpc_outlooks_relevant` and the CPC archives, because a Markdown number cannot be re-derived by the ledger and will contradict the dataset within a month. New warning guard `readme-figures-traceable` and `docs-current-dates-traceable` police this class. The same pass removed the volatile ONI value and the CPC JFM probability from the action checklist, labelling the ONI line explicitly as a snapshot |
| 41 | **README stated the forecast horizon as "17 Sep 2026 14:00 UTC through 25 Sep 2026 01:00 UTC, 8 local calendar days" and quoted a day's temperatures** | A snapshot of one run typed into prose; the horizon moves every few hours | Replaced with non-volatile wording that points at `calendar.json` → `nws_window` and the *Today's real forecast* panel. Found by `docs-current-dates-traceable` |
| 42 | **README and `docs/LIMITATIONS.md` quoted "0 of 156 periods on 17 Sep 2026"** for the null `windGust`/QPF count | Same snapshot-in-prose class | Both now say the pipeline counts null periods each run and reports the count in `quality_report.json` |
| 43 | **Climatology days published a gust, a wind speed, a temperature and a rain amount with no stated basis** (at HEAD: `gust_basis`, `wind_basis`, `temp_basis` empty on all 123 days; `gust_max_mph = 26.6`) | Only `humidity_basis` and `rain_amount_basis` were carried through to the climatology tier | Every one of the six headline fields plus temperature now carries a per-field basis on **both** tiers, naming the station, the variable, the season count and the unit conversion (GSOD knots → mph, GHCN-Daily tenths of mm). New ledger check `day-field-basis-complete` fails the run if any published value lacks its basis; render guard 20 fails if the day dialog shows a value with no basis line |
| 44 | **A pre-existing tier guard had become stale**: `test_parsers.py` asserted "no climatology day carries an NWS gust basis" by testing `gust_basis` truthiness, so it failed the moment climatology days correctly gained a *climatological* basis | The guard tested a proxy for its intent, not the intent | Rewritten to test the intent: no climatology day's basis may mention `api.weather.gov`, `gridpoint`, `NWS forecast` …, and every climatology day's gust basis must name the observed record (`GSOD`/`GHCN`) |
| 45 | **`climo.py` raised `NameError: name 're' is not defined`** on the first AFD run | The new scanner used `re` in a module that never imported it | `import re` added; the scanner is now covered by 19 offline unit assertions |
| 46 | **The first AFD scanner quoted product furniture as forecast prose** — all-caps transmission headers, a forecaster-initials footer, URLs, "Issued at" lines — scanned the AWIPS preamble, listed duplicate section names, and merged `KEY MESSAGES` bullets so two unrelated hazards appeared as one quotation | Naive `.`-split over the raw text with no section or furniture handling | Section parser keeping `(preamble)` separate; `MARINE`/`AVIATION`/`FIRE WEATHER` excluded and published as excluded; furniture filter with a published drop count; duplicate sections deduped; bullets split. Result on the current discussion: 5 sections, 43 sentences, 7 furniture dropped, 1 `strong_wind` match, 0 verbatim violations |
| 48 | **Two falsification cases silently stopped testing their guard after the data refresh** — "census geography with no recorded fetch" passed when it must fail, because the refreshed `provenance.json` now contains the *real* geocoder entry and the case only declined to add a fixture one; "absent but flagged as an irregularity" passed via the evidence branch instead of the degradation branch, because the refreshed `run.json` really does carry the geography | The harness was written against a dataset that lacked the feature, so its mutations became no-ops | Both cases now **remove** the real evidence, and each raises `AssertionError` if the thing it expects to mutate is not there — so a future refresh that changes the shape fails the harness loudly instead of quietly weakening it. This is the harness doing its job on itself: a mutation test that cannot mutate is worse than no test, because it reports confidence |
| 47 | **Two of my own new render guards were wrong on the first falsification run**: the quotation-key check counted *sentences* instead of *keys* (always failing), the basis guard read a third table cell that does not exist (the basis renders inline in a `.fine` span), and the scope check was keyword-based so it still passed with the caveat stripped | Guards written against an assumed DOM shape and an unflattened `flatMap` | All three rewritten; the scope guard now asserts the published `scope_caveat`, `usage_note` and `verbatim_rule` strings appear on the page, so a renderer reading the wrong key cannot pass |

## Session 7 — 18 September 2026 (pass 7): hour-by-hour wind+rain, fetch accounting, one definition per quantity

### Bugs found in this pass

| # | What was wrong | Root cause | Fix |
| --- | --- | --- | --- |
| 49 | The page published **98** "flood-type" storm reports in the executive bottom line and **99** in the cost drivers, for the same quantity | Two functions each defined the set of event types (`{"Flood","Flash Flood","Heavy Rain"}` in one, plus `"Debris Flow"` in the other) and both labels said "flood-type" | One definition (`landlord_summary.RAIN_RELATED_EVENT_TYPES`), both labels name the types, and a new ledger check (`storm-events-counts-recompute`) re-derives every published count from `storm_events.json` and fails the run if the two cards disagree |
| 50 | A normal run reported **4 failed fetches** on the status line; all four are supposed to 404 (the current year's GSOD/ISD annual files, a station with no `observations/latest` product, a candidate station without hourly normals) | Every non-2xx was counted as a failure, so a real outage would have been indistinguishable from the routine 404s | Failures are now counted separately from `expected_absences`; each absence must name a reason from a closed set that the ledger re-checks against the fetch's own URL, the three counts are re-derived from the manifest, and the status line names any real failure by URL |
| 51 | `data/summary.txt` and `docs/LANDLORD_GUIDE.md` still described the whole-day wind+rain figure as the only method | The hourly statistic was published on the site but not in the text digest or the guide | Both now lead with the hour-by-hour count and keep the whole-day figure labelled; the guide's numbers were removed in favour of pointers, because a number typed into Markdown cannot be re-derived |

## What the falsification harnesses established

`tests/falsify_guards.py` (15 cases, ledger) and `tests/falsify_smoke.py`
(8 cases, render) both run in CI. Every new guard was mutated into failing before
it was kept: broken GEOID nesting, an unrecorded Census fetch, a geography naming
nothing, an edited quotation, a count smaller than its own list, a deleted AFD
block, a scan claiming to have run on empty text, a date or an amount attached to
a quotation, a value with no basis on either tier, a README figure the dataset
does not publish, and a README horizon date this run never published. Two cases
are recorded as expected **passes** on purpose: a geography absent *but flagged as
an irregularity* (the honest degradation), and a quotation edited in the data —
which the renderer must faithfully display and which `afd-language-verbatim`
catches. That boundary is written in the harness so it is not rediscovered.

## Independent source re-checks performed for this feature

| Claim | Source checked | Verdict |
| --- | --- | --- |
| The 94122 centroid lies in the Census county subdivision "Sunset CCD" | Census geocoder reverse lookup at `x=-122.483894&y=37.760459` | Confirmed: `Sunset CCD`, GEOID `0607593267`, tract `326.01`, block `060750326013006`, county `06075`. Response excerpted to `tests/fixtures/census_geocoder_94122.json` with provenance in `tests/fixtures/README.md` |
| A street address for the centroid | Census `/geocoder/locations/coordinates` | **Not available** — returns HTTP 404 for this coordinate, so no address is published. Recorded in `docs/DATA_SOURCES.md` |
| The quoted AFD sentences are NWS's words | The fetched text in `data/nws.json` (product `AFD`, issued `2026-09-18T14:34Z`) | All 43 scanned sentences verified as whitespace-collapsed substrings; 0 violations. A synthetic discussion exercising all six categories was also scanned: all six fired, no MARINE/AVIATION leak, 0 violations |
| No nearer official station offers both precipitation and wind | `/stations/.../observations/latest` distances in `data/nws.json` | Confirmed: SFOC1 (3.67 mi) carries no precipitation or wind; DW7094 (11.07), KSFO (11.88), MDEC1 (12.75), OAMC1 (12.8), DW3169 (14.17) are all farther than the GHCN downtown (3.2 mi) and GSOD SFO (11.9 mi) pair already used |

## Standings after this pass

* `pipeline/verify_claims.py`: **47 checks** (41 at the start of the session, +6),
  18 recorded claims. Six new: `census-geographies-traceable`,
  `afd-language-verbatim`, `afd-language-quotations-only`,
  `day-field-basis-complete` (errors) and `readme-figures-traceable`,
  `docs-current-dates-traceable` (warnings).
* `tests/test_parsers.py`: **316 assertions** (+19), stdlib only, offline.
* `tests/smoke.js`: guards **19** and **20** added (AFD card fidelity; per-field
  basis in the day dialog).
* Known expected failure on the committed dataset: `census-geographies-traceable`
  fails against `data/run.json` as committed, because that file predates the
  geocode step. The first CI run that repopulates `run.json` (or records a
  `geography` irregularity) resolves it; the check is written to accept either
  outcome and reject only the silent one.

---

## Session 8 — 18 September 2026 (pass 8): CPC back-test pipeline, GSOD/ISD retirement, deep links, AFD history, digest

This pass implemented five of the six open items from `docs/NEXT_SESSION.md` §2
(the sixth, CFSv2/NMME model guidance, stays explicitly unbuilt per its own
heavy-caveat rule — and a new ledger check, `model-guidance-separated`, now
fails the run if model guidance ever leaks into the scoreboard tiers). Six new
ledger checks cover the new artefacts (see standings).

### Bugs found in this pass (and fixed)

| # | What was wrong | Root cause | Fix |
| --- | --- | --- | --- |
| 52 | `data/afd_history.json` recorded every category with a null key, and the last-mention table could never resolve | `afd_language_scan()` names the field `id`, but `update_afd_history()`, `afd_last_mention()`, the calendar builder and the ledger check all read `key` | All four read `id` with a `key` fallback; the bad history file was deleted and rebuilt; a regression test pins a scan using `id` and a legacy entry using `key` |
| 53 | The CPC back-test card expected `summary` to be an array of rows; the writer produces `{status, rows, summary}` | Card and writer were written against different imagined schemas and never run together | The renderer was rewritten for the real schema (hit-rate + by-category table + per-row table, pending-backfill callout with attempt table); smoke guard 27 pins card/file consistency |
| 54 | The digest renderer read `it.url` / `it.summary` / `nws_alert` | Item schema is `link` / `description` / `nws-alert` (RSS vocabulary) | Renderer corrected to the real keys before first render |

### Decisions with evidence

| Decision | Evidence |
| --- | --- |
| GSOD/ISD stop at 2025-08-27 because NCEI **retired** both archives on 2025-08-29 — not a station-ID change, not a lag | HadISD final release `v342_202508p`; GSODR retirement docs; NOAA community notice that SSOD replaces GSOD and GHCNh replaces ISD. Coverage notes now say "retired"; each run probes GHCNh/SSODv2 |
| IRI Data Library **rejected** as a CPC archive source | Serves HTTP only (project requires HTTPS); a Columbia academic mirror, not an official NOAA operational product; its `SOURCES/.NOAA/.NCEP/.CPC/` tree holds monitoring datasets, not outlook polygons. Documented in `docs/DATA_SOURCES.md` §3, kept off `ALLOWED_HOSTS` |
| Email digest **not offered** | Requires storing addresses and running a sender; a static site cannot do either honestly. RSS + JSON only, opt-in, no tracking |

### Standings after this pass

* `pipeline/verify_claims.py`: **59 checks** (53 at the start of the pass, +6:
  `cpc-backtest-sampling-method`, `deep-links-traceable`, `afd-history-consistent`,
  `digest-rss-traceable`, `model-guidance-separated`, `successor-probe-present`),
  19 claims.
* `tests/test_parsers.py`: **360 assertions** (+24: CPC scoring incl. EC-unscored,
  AFD history append/dedupe/cap, digest triggers + RSS well-formedness/escaping,
  deep-link key sets + official-host rule).
* `tests/smoke.js`: guards **24**–**27** added (digest card vs `digest.json`;
  AFD last-mention rendering; day-dialog deep links on official hosts;
  back-test card vs `cpc_backtest.json`).
* New workflow steps: `cpc_backtest.py` (after the calendar build) and
  `build_digest.py` (after the landlord summary), both before the claim ledger
  so their outputs are verified before publication.

### Pass 2 (same session): bug/edge-case review of the Pass 1 diff

| # | What was wrong | Root cause | Fix |
| --- | --- | --- | --- |
| 55 | `main.fetch_isd_history()` called `climo.search_isd_history_for_station`, which does not exist — the nightly run would have crashed with `AttributeError` | The fetch path needs the network, so it never executed locally | Call `climo.search_isd_history`; new tests execute both fetch functions end to end with a stubbed transport |
| 56 | The successor search reported a still-open buoy (operating since 2020) as KSFO's successor id | A "still open" fallback ignored BEGIN dates | Successor must BEGIN after the stop; the fallback is gone, with a comment recording why |
| 57 | The back-test's fetches (GHCN re-fetch + archive attempts) and sampling warnings died with its process: scored rows would have had no recorded fetch and the run counts would no longer recount | `cpc_backtest.py` runs after `main.py` wrote the run files, in a fresh process with an empty manifest | `merge_run_manifests()` folds the step's manifest + irregularities back into `provenance.json`, `run.json`, `quality_report.json` and `summary.txt`, on both exit paths; tested against a miniature run directory |
| 58 | The ledger hard-coded the 50% POP threshold the builder publishes as a constant | Copy-paste of the value instead of the import | The ledger imports `POP_THRESHOLD_PCT` from `build_digest` |
| 59 | JFM outlooks were scored against the *following* year's observed rain | A fixed "Jan/Feb/Mar belong to year+1" rule, wrong for a season that starts in January | Months at/after the season's first month belong to the named year; year-boundary tests pin OND/NDJ/JFM |
| 60 | NWS days' human-forecast deep link was silently dropped from the day dialog | The dialog's link list had no `human` row | Row added (NWS days show 7 links, climatology days 7) |
| 61 | Stripping one day's deep links still passed `deep-links-traceable` | The legacy-dataset leniency tested `days[0]` only | Leniency now requires *no* day to carry links; 10 new falsification cases pin all six new checks (33 total) |
| 62 | If a mid-pipeline step crashed, the commit step read the *stale* `verify.json` (usually a pass) and published unverified data | The gate checked the verdict but not whether every step ran | The gate additionally requires all seven `*_EXIT=0` lines in `run_diagnostics.txt`; verified against full and crashed runs |
| 63 | The GHCNh probe fetched `ghcnh-station-list.txt` (404) and searched only the first 200 KB, where no US id can appear | Unverified URL guess; a truncation that assumed alphabetical irrelevance | Probed the live host: the list is `.csv` (pinned by test); the SFO check searches the full text |
| 64 | A non-string DBF `Cat` value would have crashed the back-test on `.strip()` | Unchecked type from the shapefile row | `str(...)` coercion before stripping |

Minor hardening in the same pass: removed a dead variable, validated
`normals_period` before unpacking, made the digest refuse a non-numeric POP
rather than guessing, required the tier-appropriate 7th deep link and a
recorded fetch behind an ok GHCNh probe, and de-literalised the threshold in
the site's static prose.

Standings after Pass 2: `tests/test_parsers.py` **377 assertions** (+17),
`tests/falsify_guards.py` **33 cases** (+10), ledger still **59/59**.


---

## Session 9 — 18 September 2026 (pass 9): model guidance, official-product feed, and the merge with pass 8

This pass was developed in parallel with pass 8 (PR #17) from the same base commit
`c648b68`, so the two met as a merge rather than as a sequence. What follows records
both what this pass built and how the collision was resolved, because a merge that
silently deletes another session's verification work is itself a defect.

### What this pass added

Two tiers that pass 8 deliberately left unbuilt, plus one bug fix that pass 8's own
committed data proves was live:

* **Model guidance** (`pipeline/model_guidance.py`, 25 offline self-checks): NOAA's
  NMME seasonal probability maps archived locally with their SHA-256, NOAA's own
  definition sentences quoted verbatim, the coverage period read from NOAA's index
  page rather than derived from a filename, and the raw archive / NOMADS locations
  recorded with `decoded: false`. Its own manifest, its own site section, a warning
  that renders before any content and again on every item.
* **The official-product feed** (`pipeline/build_feed.py`, 36 offline self-checks):
  one chronological list of what NOAA published and what this project fetched,
  distinguishing `url` from `evidence_url`, never inventing a clock time a publisher
  did not give, and carrying model-guidance rows into the same list labelled
  `NOT OFFICIAL`. No network access at all.
* **`pipeline/lib_provenance.py`**: the auxiliary-manifest convention and an
  idempotent quality-report merge (findings tagged by `source`, counts recomputed
  from the entries).

### Bugs found in this pass

| # | Bug | Evidence | Fix |
| --- | --- | --- | --- |
| 65 | **The two rainy-season CPC outlooks were attached to no day at all.** `parse_season_key` did `int("2026-2027")` on a cross-New-Year label, hit `ValueError` and returned `(None, None)`, so `NDJ 2026-2027` and `DJF 2026-2027` were sampled, printed in the season table, and attached to nothing | Pass 8's own committed `data/calendar.json`: records labelled `NDJ 2026-2027` / `DJF 2026-2027` exist, yet 2026-12-15 carried only `lead1_OND_prcp` / `lead1_OND_temp`. Per-month attachment counts were Oct 4, Nov 2, **Dec 1, Jan 1** | `parse_season_year` accepts `YYYY-YYYY` / `YYYY/YYYY` for consecutive years only; a declared end year must agree with the season's shape (`OND 2026-2027` is rejected, `NDJ 2026` keeps its historical Nov-Jan reading); a single month never spans two years. After the fix, 2026-12-15 carries DJF + NDJ + OND and per-month counts are Oct 4, Nov 3, Dec 3, Jan 3. Ledger: `cpc-record-coverage-declared`, `cpc-season-covers-complete`, `cpc-record-reach` |
| 66 | Six renderer strings in `assets/js/app.js` contained double escapes (`\\u2014`, `\\u00b0`, `\\u2265`) that print a literal `\u2014` on the page instead of an em dash, a degree sign or `≥` | `grep -c '\\\\u' assets/js/app.js` → 6 on the merged tree (the same class of defect this pass had already fixed 13 of on its own branch) | Replaced with the real characters; `node --check` and `npm test` re-run |
| 67 | A ledger check written on this pass's branch (`auxiliary-manifests-separate`) was tautological — it compared a manifest to itself, so it could never fail | Read of the check's source before the merge | Rewritten against the real schemas: every fetch recorded in exactly one manifest, and `run.json`'s totals re-derived from the nightly manifest alone |

### What the first live CI run of these tiers found (bug 68)

The nightly workflow ran on this branch at `3941ac6` before the merge, with real
network access — the first time the new tiers had ever touched NOAA's live servers.
Every step exited 0 (`PIPELINE`, `CALENDAR`, `LANDLORD`, `CPC_BACKTEST`,
`NCEI_PROBE`, `MODEL_GUIDANCE`, `AFD_HISTORY`, `FEED`, `VERIFY`) and the ledger
then failed the run, so the gate correctly refused to publish:

> `[FAIL] model-guidance-links-fetched` — *1 guidance item(s) that failed to fetch
> publish no error, so a reader cannot tell they are missing*

| # | Bug | Root cause | Fix |
| --- | --- | --- | --- |
| 68 | A model-guidance probe that could not run was published with `ok: false` and **no `error` field** | The raw-archive probe resolves its URL from the newest run directory listed on CPC's archive page. When that page lists no runs, the code appended `{ok: false, skipped: "..."}` and moved on — a `skipped` note is not an error, and the ledger requires every failed item to say why | The probe now publishes the cause and distinguishes the two: *"the archive page was retrieved but listed no run directories … if NOAA changed the layout of that page, `ARCHIVE_ROW_RE` needs updating"* versus *"the archive page could not be retrieved (HTTP …)"*. It also raises a `model_guidance` irregularity, so the failure surfaces in *Data quality* and not only in the ledger. Six new self-checks reproduce both paths (31/31) |

This is the guard working as designed rather than a false alarm: a silent
`ok: false` is exactly how a missing dataset starts looking like an empty one, and
the check that stopped the publish was written before the tier had ever run live.
The run's diagnostics were committed by the workflow as
`chore(data): refresh NOT published`, and are merged here for the record; the
regenerated diagnostics in this tree describe the merged code instead.

### What the second live CI run found (bug 69)

The next nightly run, at `7290d32`, passed the ledger and **published**
(`data: refresh NOAA/NWS/NCEI/CPC sources`) with both previously dormant
model-guidance checks running for the first time: 69 checks passed, 0 failed,
0 warnings. The published tier was nevertheless nearly empty.

| Published by that run | Value |
| --- | --- |
| `pages_retrieved` | 7 of 7 requested, all HTTP 200 |
| `images_archived` | **0** |
| `nmme_archive_latest` probe | **skipped** — *"the archive page was retrieved but listed no run directories"* |
| the archive page itself | 32,319 bytes, HTTP 200, hashed like every other fetch |

| # | Bug | Root cause | Fix |
| --- | --- | --- | --- |
| 69 | Every NMME page was fetched successfully and **nothing was extracted from any of them** — no map URLs, no archived run directories — so the tier published an empty list while looking healthy | Both patterns were matched against raw markup and each assumed one shape. `IMAGE_RE` required an absolute href in double quotes with `/` immediately before `images/`; `ARCHIVE_ROW_RE` required the same and additionally required the coverage label to sit between `>` and `<` with no tag in between. CPC's pages use relative hrefs, single-quoted and unquoted attributes, wrap their archive labels in their own markup (`<font>`), and link run directories with a trailing slash — none of which this project controls | `extract_links()` pulls every `href`/`src` in any quoting style and resolves it with `urljoin` against the page's own URL, so `IMAGE_URL_RE` / `ARCHIVE_RUN_RE` match a **resolved URL** instead of markup; `extract_anchors()` returns `(url, label)` per anchor in document order with nested tags stripped, preserving the newest-first order the archive listing uses; the probe fetches the directory URL exactly as NOAA links it rather than a normalised guess. When a page is retrieved but parses to nothing the run now publishes `markup_excerpt` (≤700 chars from the first anchor) plus a warning irregularity naming the byte count, and every page records `n_links_seen`. Without that, "HTTP 200 and understood nothing" is undiagnosable from the committed data — which is why this took a second live run to find. Self-checks 31 → **53** (four markup shapes × four assertions, plus two diagnosability checks) |

Confirmed by the run after the fix (`3f89643`, published as `561544d`): **10 maps
archived** under `assets/model_guidance/` — five precipitation-rate and five
2m-temperature seasons, 30,357–31,998 bytes each, every one re-hashed by the
ledger against `data/model_guidance.json` — `nmme_archive_latest` resolving to
`https://ftp.cpc.ncep.noaa.gov/NMME/archive/2026080800` at HTTP 200 with its own
SHA-256, `probes_ok: 2`, `irregularities: []`, coverage still published verbatim
as NOAA prints it (`October 2026 - April 2027`), and the ledger at **69 passed /
0 failed / 0 warnings**. That commit is what PR #18 merged to main (`2d62c3d`).

The lesson is recorded rather than buried: a tier can be *honest* and still be
*empty*. Bug 68's disclosure fix made such a failure visible to the ledger; this
fix makes the extraction work, and the excerpt means the next one is diagnosable
from the published data alone, without needing sandbox access to NOAA.

### How the collision with pass 8 was resolved

Pass 8 merged first, so it is the baseline. The rule applied was: **where both
passes built the same feature, main's implementation wins; where a pass built
something the other explicitly left unbuilt, it is kept; and every surviving guard
is re-run rather than assumed.**

| Feature | Pass 8 (kept) | This pass | Resolution |
| --- | --- | --- | --- |
| CPC back-test | `cpc_backtest.py` (488 lines) + `data/cpc_backtest.json` + `merge_run_manifests` + ledger/tests | A different 844-line implementation + 30 self-checks | **Main's kept.** This pass's module, self-test and `lib_cpc.py` were deleted rather than allowed to shadow merged work; the back-test is covered by `tests/test_parsers.py`, which imports the module directly |
| Stale wind archive | NCEI retirement (2025-08-29) + `isd_history.json` successor search + nightly `ghcnh_probe.json` + `successor-probe-present` | `ncei_archive_probe.py`: classification from per-year control comparison + service alerts | **Main's kept** — a retirement notice from NCEI is better evidence than an inference from control stations, and two published verdicts about one archive would invite confusion. Module and self-test deleted; `docs/METHODS.md` §24 records the reasoning |
| AFD history | `data/afd_history.json` written by `build_calendar.py` (append-only, deduped, capped) + `afd-history-consistent` | `afd_history.py` writing the same filename with a different schema | **Main's kept**; module and self-test deleted, and the feed was adapted to read main's list schema |
| Deep links | Per-field `deep_links` on all 123 days + `deep-links-traceable` + smoke guard 26 | Per-day link list with `fetched_by_this_run` + an Access Data Service shape probe | **Main's kept** (per-field links name the exact element a figure came from, which is more useful than one link per day); this pass's builder, probe and two ledger checks deleted |
| Model guidance | Explicitly unbuilt, with `model-guidance-separated` guarding against a silent merge | The full tier | **This pass's kept** — it is what pass 8 left open. Both guards now run: main's inspects scoreboard days, this pass's also audits the guidance file itself and scans for leaks outside quoted official text |
| Product feed | Not built | The full tier | **This pass's kept** |
| Provenance convention | Merge back into `provenance.json` | Separate `data/<area>_provenance.json` | **Both kept**, deliberately: the merge-back exists so back-test rows appear in the manifest the run's totals describe, and the separate manifest exists so the guidance tier reads as its own thing. `verify_sources.py` scans every manifest, and both conventions satisfy `auxiliary-manifests-vetted` / `-separate` (`docs/METHODS.md` §26) |

Retiring this pass's duplicates also retired their guards: 6 render-falsification
cases and 9 ledger-falsification cases were removed with the code they covered, and
the removal is recorded in `tests/falsify_smoke.py` rather than left as a silent
shrinkage.

### Standings after the merge

* `pipeline/verify_claims.py`: **67 checks pass, 0 fail, 0 warnings**, 19 recorded
  claims (pass 8's 59 + 8 ported: 3 CPC coverage, 2 auxiliary manifests,
  1 model-guidance isolation, 2 feed). Two further model-guidance checks
  (`-quotes-verbatim`, `-links-fetched`) run only when `model_guidance.json` exists,
  i.e. on a live CI run — both have now run live and pass, so a live run reports
  **69 checks, 0 failed, 0 warnings**.
* `tests/test_parsers.py`: **409 assertions** (pass 8's 310 + 99 ported).
* `tests/falsify_guards.py`: **56 cases** behave (33 + 23 ported).
* `tests/falsify_smoke.py`: **23 cases** behave.
* `pipeline/verify_sources.py`: exit 0 scanning every manifest.
* Module self-tests in CI: `model_guidance` **53**, `build_feed` 36 — **89 offline
  checks** (model guidance started at 25, gained 6 for bug 68's probe disclosure
  and 22 for bug 69's markup shapes and diagnosability).
* `npm test`: passes, now including smoke guards 28 (model-guidance tier) and 29
  (feed).
* `data/feed.json` rebuilt against pass 8's live data: **202 entries** (+3 undated),
  202 official / 0 not-official, 198 provenance-verified / 2 labelled pointers only.
  Against the data CI published live at `561544d`: **212 entries**, 211 official /
  1 not-official (the model-guidance rows, labelled as such), 207 traced to a
  recorded fetch.
* Model guidance, live: 7 pages retrieved (all HTTP 200, all hashed), 10 maps
  archived under `assets/model_guidance/`, 7 verbatim definition sentences,
  2 availability probes ok and neither decoded.

## Session 10 — 19 September 2026 (pass 10): review of the merged main, time-bomb test

Starting point: `main` at `0d82db5` (the 19 Sep 07:15 UTC nightly data refresh,
all 69 ledger checks passing, Pages deployment green). The full offline suite
was re-run in the sandbox before any change was made; everything passed except
one check, found and fixed as bug 70 below.

| # | Symptom | Root cause | Fix |
| --- | --- | --- | --- |
| 70 | `tests/test_parsers.py` failed 1 of 409 checks against the freshly refreshed data: *"derived gust for 2026-09-18 matches NWS's stated 18 mph within 2 mph: None"* — even though the nightly ledger (69 checks) was green and the site healthy | A **time bomb**: the check hard-coded two dates and values ("18 Sep = 18 mph, 19 Sep = 20 mph") taken from the NWS text forecast *as it stood on 18 Sep*. The `Tests` workflow runs on push, not on the nightly data commit, so nothing tripped until the next push after the forecast window had moved past 18 Sep — then the date was no longer inside `current_forecast.days`, the derived gust was `None`, and any PR would have failed CI through no fault of its own | The check now **reads the dates and values from the product this run fetched** instead of trusting a transcription: every `forecast_daily` period whose `detailed_forecast` states "gusts as high as N mph" is parsed, its stated gust is attributed to the local dates the period covers, and two guards run: (a) each stated gust must appear in the derived daily maxima within 2 mph in at least one covered date (lower bound per period — the text is generated from the same grid the calendar reads); (b) the window's derived gust max must lie within −2/+8 mph of the stated text max (the +8 upper margin absorbs gusts the text omits when they are not far above sustained wind, while a km/h↔mph or doubling bug overshoots it by far). Both guards were falsified before being kept: understating 19 Sep's gust to 10 mph fails guard (a); overstating the window max to 48 mph fails guard (b). A run whose text states no gust at all (deep calm) passes with the stated/checked counts printed in the detail rather than vacuously pretending to have cross-checked something |

Pass-2 review of this diff also corrected the stale method note in
`docs/LIMITATIONS.md` §12, which still described the hard-coded 18/20 mph
example; it now describes the dynamic check.

### Feature added the same session: the outlook's own caveats, verbatim

**Why.** Reviewing the site's official-outlook strip against the live CPC
Prognostic Discussion (fxus05, issued 17 Sep 2026 — fetched and checked by
hand from the sandbox, both the discussion page and the official ONI file)
found an asymmetry: the strip said *"El Niño Advisory, +1.80 °C, JFM 2027
Above 50%"*, while NOAA's own discussion — a file the pipeline already
fetched, hashed and archived — stated, in its forecasters' own words, that
this El Niño is *unlike* the Big Three because the PDO is strongly negative
(August index −1.11) and "may dampen the typical impacts of a strong El Niño
in certain areas", and that the DJF/JFM precipitation probabilities
themselves "may be increased further in the next set of seasonal outlooks, to
be released in mid-late October". A landlord budgeting on "wet winter ahead"
was seeing the tilt without the tilt's own stated caveats.

**What was built** (`prognostic_caveats()` in `pipeline/landlord_summary.py`,
rendered in the outlook strip, `#landlord-official`):

* Three pattern-located sentences are extracted from the *archived* 90-day
  discussion in `data/cpc.json` (which itself carries the URL, SHA-256 and
  byte count of the fetch): the PDO state sentence, the PDO-dampening
  sentence, and the "probabilities may move at the next issuance" sentence.
  Patterns generalise the parts CPC rewrites monthly (month name, index
  value, release window) because the discussion is a new document each
  issuance.
* Quotations only, copied verbatim (whitespace-collapsed). A matched sentence
  that contains non-printable characters is refused — the publisher's page
  carries broken smart-quote bytes (e.g. around "Big Three") that must never
  reach the page through this path.
* What was watched for and not found is published (`not_found`), the
  discussion's own issuance line is quoted as-is, and the card states that no
  number or date was attached by this project. A missing archive degrades to
  an honest `available: false` with a reason, never an empty silence.
* When CPC rewrites the discussion in mid-late October and a sentence
  disappears, it stops being published and is listed as not found — the card
  cannot hold a stale quote over.

**Guardrails added** (each falsified before being kept):

* Ledger check `prognostic-caveats-verbatim` (**check 70**): every published
  quote must be a whitespace-collapsed substring of the archived discussion
  text; the archived discussion must trace to a recorded fetch; a quote key
  must be one the extractor declares in `patterns_watched_for`; an
  `available` block must actually have the archive; an unavailable block must
  state a reason and carry no quotes; no quote may contain control
  characters. Falsified by 7 new cases in `tests/falsify_guards.py`
  (edited quote, hand-added key, block removed, archive deleted, honest
  unavailability passing, mojibake smuggling, U+FFFD smuggling) — 63 cases
  total.
* Render guard 30 in `tests/smoke.js`: every quote in the dataset must render
  inside the outlook strip, the "no number or date attached" marker and the
  source link must be present. Falsified by 4 new cases in
  `tests/falsify_smoke.py` (renderer drops a quote, marker removed, link
  removed, unavailable card without its reason) — 27 cases total.
* 9 new offline assertions in `tests/test_parsers.py` pin the extractor
  itself against synthetic discussions: full extraction, verbatim text,
  issuance line, rewritten discussion (all three absent, named), mojibake
  refusal, missing archive, empty cpc file, and the committed
  `landlord.json` block equal to a fresh extraction over the committed
  `cpc.json` — **419 assertions total** (the last covers both the C1 control-character refusal and the U+FFFD replacement-character refusal).

### Standings after this pass

* `pipeline/verify_claims.py`: **70 checks pass, 0 fail, 0 warnings** (69 + 1
  new), 19 recorded claims, against the current committed dataset.
* `tests/test_parsers.py`: **419/419 assertions pass** (409 + 10 new; the two
  dynamic gust guards replace the two hard-coded iterations of the old loop
  check).
* `tests/falsify_guards.py`: **63 cases** behave. `tests/falsify_smoke.py`:
  **27 cases** behave. `npm test` (jsdom render, guards 1–30) and
  `pipeline/verify_sources.py` pass against the committed data.
* Data files changed: `data/landlord.json` (regenerated from the same
  verified inputs to carry the caveats block — the extraction is re-derived
  and checked by the ledger), `data/verify.json` / `verify_report.txt`
  (regenerated, 70 checks). Everything else remains the dataset the
  19 Sep 07:15 UTC CI run fetched and verified.

## Session 11 — 19 September 2026 (pass 11): stale-PR audit, falsify time bomb #2, printable executive summary, CI migration hardening, live re-verification

Starting point: `main` at `5c8bef0` (the 19 Sep 19:42 UTC data refresh that
followed the session-10 merge, ledger 70 checks green at merge time).

### PR #15 — audited line by line, closed as superseded, two surviving gaps forward-ported

Session 7's PR (#15, `arena/01a0b5b2-sfweather`) had been left OPEN while
sessions 8–10 (#16–#20) were merged. Audit on 19 Sep 2026:

* A merge would have been destructive: direct diff `origin/main → pr15 head`
  is **71 files, +4,142 / −34,911 lines** — it would revert the model-guidance
  tier, CPC back-test, digest, AFD history, deep links and the sessions 8–10
  test growth.
* Its three headline features are verifiably present in main, rebuilt by the
  later sessions: `climo.afd_language_scan` + `#afd-language` card; Census
  GEOID `0607593267` in `data/calendar.json`/`run.json`/`verify.json`;
  `temp_basis`/`gust_basis`/`rain_chance_basis` on all 123 days; ledger checks
  `census-geographies-traceable`, `afd-language-verbatim`,
  `day-field-basis-complete`.
* `git merge-base --is-ancestor` = false for all five substantive commits
  (`439ab57` degraded-state rendering, `25d683d` failed-fetch explanations,
  `4837f57` pass-3 recheck, `890d777` guard defects, `b776efc`/`45b88e0`
  bug 54). Spot-checks of current main found two still-live gaps, forward-
  ported this session: (1) `kvTable` still drops null rows, so a missing
  individual Census geography field vanishes silently — documented here as an
  open follow-up (the block-level "not retrieved" case is already handled);
  (2) there was no `failed-fetches-explained` ledger check — left as a
  follow-up; the quality report already explains each failed fetch in prose.
  PR #15 was closed with this audit attached rather than merged.

### Bug 71 — a second time bomb, this one in the falsification harness

| # | Symptom | Root cause | Fix |
| --- | --- | --- | --- |
| 71 | `tests/falsify_guards.py` exited 1 on freshly refreshed main: *"README quotes a horizon date this run never published: expected warn, got pass"* — the suite had been green at the session-10 merge, then the 19:42 data refresh (committed `[skip ci]`) broke it | The case injected the literal date **2026-09-29** as a fake NWS horizon end. On 19 Sep that date became the *real* end of the CPC 8–14 day valid period, which the `docs-current-dates-traceable` check counts as a traceable vocabulary date — so the mutation became a no-op pass. Same class as bug 70 (hard-coded weather facts decaying under nightly refreshes); the `[skip ci]` data commit is why CI never saw it | The case now rebuilds the ledger's own date vocabulary (run date, NWS window, forecast days, CPC issuance/valid dates) from the committed datasets and picks a date inside the ±30-day band that is provably absent from it, raising if none exists. The sibling README-figure case got the same hardening: its `replace()` target is now asserted present before mutating, because a `replace()` that silently finds nothing is a no-op pass |

### Feature: the printable executive summary (machine-generated, drift-proof)

The landlord dashboard already carries the ranked cost drivers; what did not
exist was a single shareable document. `pipeline/executive_summary.py` now
generates `data/executive_summary.md` + `.json` from `landlord.json`/
`run.json`/`calendar.json`/`cpc.json`/`nws.json` on every pipeline run: the
six landlord answers with their number tables and basis lines, the official
outlook (ENSO state, CPC tilts incl. the three verbatim caveats, the
ENSO-conditioned record, the live horizon), the six ranked repair &
maintenance cost drivers with evidence and source links, the expected day
counts with thresholds *derived from the dataset's own severity keys*, the
"what this document cannot tell you" statement, and the manual-review links.
No figure or link is typed in prose: every one is copied from a dataset
field, and the threshold strings (0.25 / 0.50 / 1.00 / 2.00 / 4.00 in) are
parsed out of `expected_days`/`severity` key names. Missing inputs exit 1
rather than publishing a half-built document, and the workflow's publish gate
now requires `EXEC_SUMMARY_EXIT=0`.

Guards:

* Ledger check **71, `executive-summary-traceable`**: the document must carry
  the dataset's own generation stamp, all cost-driver titles in full, and
  every URL it prints must appear verbatim in one of the five source
  datasets. A hand edit cannot satisfy all three. Falsified by 2 new cases
  in `tests/falsify_guards.py` (invented link, hand-edited stamp) — **65
  cases total**.
* **7 new offline assertions** in `tests/test_parsers.py`: driver titles in
  rank order, generation stamp, every link traceable, every numeric token in
  the document appears in the source datasets, the JSON mirror agrees, the
  generator refuses an empty data dir, and it writes both artifacts against a
  real data copy — **426 assertions total**.
* The dashboard's executive-summary callout links to the printable page;
  README documents the drift-proof contract.

### CI housekeeping before the ubuntu-latest migration

* GitHub's changelog (2026-09-17) confirms the `ubuntu-latest` label migrates
  24.04 → **26.04 gradually between 19 Oct and 19 Nov 2026**. Both workflows
  now pin `runs-on: ubuntu-24.04` with the rationale inline, so the unattended
  nightly refresh cannot change OS underneath it mid-season; the move to 26.04
  is a deliberate later task.
* The Node-20 deprecation warnings were resolved by bumping to the lowest
  major that declares `using: node24`, **read from each action's own
  action.yml at the tag**: `actions/checkout` v4→v5, `actions/setup-node`
  v4→v5, `actions/setup-python` v5→v6 (still accepts `python-version`),
  `actions/upload-artifact` v4→v6 (still accepts name/path/retention-days).

### Live re-verification, 19 Sep 2026 ~20:40 UTC (no hallucination pass)

Every item fetched live from the official product and compared line by line
against the committed dataset:

| Product | Live official URL | Result |
| --- | --- | --- |
| NWS daily forecast, grid MTR 82,105 | https://api.weather.gov/gridpoints/MTR/82,105/forecast | PoP values for all 13 committed periods **exact match** (0,1,1,1,2,2,0,0,0,0,0,0,0). Live issuance 20:26:32Z is 2 h newer than the committed fetch (18:27:15Z) and adjusted period-1 wind "9 to 14" → "10 to 14 mph"; the nightly refresh picks that up. Horizon still ends 2026-09-25 |
| Official ONI file | https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt | Last line `JJA 2026  29.09  1.80` — **exact match** with the published +1.80 °C |
| ENSO Diagnostic Discussion (issued 10 Sep 2026) | https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml | **El Niño Advisory** status, Niño-3.4 +1.8 °C August, next discussion **8 October 2026** — all match `data/enso.json`, which already archived the ">90% chance of a very strong event" and "75% chance of a historic event (+2.5 °C or more)" sentences |
| CPC long-lead Prognostic Discussion fxus05 (issued 17 Sep 2026) | https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html | All three published caveat quotes **verbatim matches** (PDO −1.11 sentence; "may dampen the typical impacts of a strong El Niño"; "may be increased further … mid-late October"). OND wet signal "from the southern half of California" is consistent with the EC sampling at 94122 for OND; "maximum of 50-60 percent near the coast during DJF, JFM, and FMA" is consistent with the sampled DJF 40% / JFM 50% tilts |
| ZIP centroid coordinate | https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip | re-derived in every run by the pipeline; 37.760459, −122.483894 |

### CPC back-test archive probe (bounded, documented)

The archive index (https://www.cpc.ncep.noaa.gov/products/archives/long_lead/llarc.ind.php)
is a form posting to `llarc.php`; the endpoint is **alive and validating input**
(both probe attempts returned "Bad month entry. A 2 digit number between 01 and
12 must be entered"), but the form's parameter names are not recoverable from
the rendered page nor from any archived capture (CDX shows a single bare
capture of `llarc.php`, 2006). Newly mapped URL patterns: per-month outlook
**GIFs** at `products/archives/long_lead/gifs/YYYY/YYYYMMmonth.gif` (archived
200s back to 1997 — graphics, not sampleable shapefiles) and a
`products/archives/long_lead/data/YYYY/` tree (live directory 403; archived
members include `data/2002/wash.txt`). The live GIS mirror still 404s for
`seasprcp_199510.zip`. The back-test therefore stays honestly
`pending-backfill`; the next attempt should POST the form with guessed field
names or inspect the page's raw HTML from a browser.

### Standings after this pass

* `pipeline/verify_claims.py`: **71 checks pass, 0 fail, 0 warnings** (70 +
  `executive-summary-traceable`), 19 recorded claims.
* `tests/test_parsers.py`: **426/426** (419 + 7). `tests/falsify_guards.py`:
  **65 cases** behave (63 + 2). `tests/falsify_smoke.py`: 27 cases behave.
  `npm test` passes. Workflow YAML re-validated.
* New/changed files: `pipeline/executive_summary.py` (new),
  `data/executive_summary.md`/`.json` (new, machine-generated),
  `pipeline/verify_claims.py`, `tests/test_parsers.py`,
  `tests/falsify_guards.py`, `index.html`, `README.md`, both workflows,
  `docs/NEXT_SESSION.md`, this file.

## Session 12 — 19 September 2026 (pass 12): dry-discussion seed fix, ENSO strength probabilities on the outlook strip

Starting point: `main` at `b4f1be5` (a nightly `[skip ci]` data refresh; the
session-11 work — printable executive summary, ledger at 71 — already in the
tree). This session implements priority 6 of the session-11 handoff (surface
the ENSO strength probabilities) and fixes one harness bug found while
re-proving the suite.

### Bug 72 — the falsification harnesses assumed a discussion with quotable sentences

| # | Symptom | Root cause | Fix |
| --- | --- | --- | --- |
| 72 | `tests/falsify_guards.py` failed 4 cases and `tests/falsify_smoke.py` 1 case against the refreshed data, all *expected-fail-got-pass*: the AFD-language mutations had nothing to mutate | The September AFD carries no storm-language sentence the scanner quotes, so cases that "edit the first quotation" / "drop a quotation" were no-ops that passed. Same family as bugs 70–71 (fixtures decaying under real data), but inverted: an *empty* product instead of a changed one | The harnesses now **seed one verbatim sentence from the archived AFD text and then mutate it** (rejected alternative: fail loudly on empty discussions, which would red-den CI on every dry discussion). Both harnesses re-proved: 65/65 ledger cases, 27/27 smoke cases |

Process note: two same-file `falsify_guards.py` edits applied in parallel
mid-session raced last-writer-wins and silently dropped each other; the suite
caught the stale bodies before anything was merged. Same-file edits are now
applied strictly sequentially.

### Feature: the El Niño strength outlook, quoted verbatim (closes handoff priority 6)

**Why.** The outlook strip already showed the ENSO state (El Niño Advisory,
+1.80 °C) and the forecasters' caveats — but not the probabilities *behind*
the outlook: the September ENSO Diagnostic Discussion states a greater than
90% chance of a very strong event during the Northern Hemisphere fall and
winter 2026-27, and a 75% chance of a historic event for the
October–December 2026 season. Those sentences were archived in
`data/enso.json` and live-verified in session 11, yet unreachable from the
page a landlord reads.

**What was built** (`enso_strength_outlook()` in
`pipeline/landlord_summary.py`, rendered in the outlook strip,
`#landlord-official`, and as a bullet in the printable executive summary):

* Two pattern-located sentences are extracted from the *archived* ENSO
  Diagnostic Discussion in `data/enso.json` (URL, SHA-256 and byte count of
  the fetch carried alongside): the very-strong-event probability and the
  historic-event probability. Patterns generalise the parts CPC rewrites
  monthly (the percentage, the season) because the discussion is a new
  document each issuance.
* Quotations only, copied verbatim (whitespace-collapsed), with a stated
  marker that no number or date of the project's own was added. A matched
  sentence that is not clean printable text is refused and reported, never
  published.
* What was watched for and not found is published (`not_found`); when the
  October discussion drops or rewords a sentence, the card follows the same
  run and cannot hold a stale quote over.
* A discussion the pipeline flagged as carrying no current-year text is
  **refused outright** (`usable_as_current_source: false` → honest
  `available: false` with a reason): last month's probabilities printed next
  to this month's ONI would read as current when they are not.

**Defect caught by the new tests before merge (no bug number — never
published broken):** the first historic-pattern tail (`[^.]+`) ended the
quotation at the first period *anywhere*, clipping the committed quote to
"…dating back to 1950 (+2." and silently dropping the threshold definition
"(+2.5 °C or more for a 3-month RONI value)". Both pattern tails now match a
decimal number atomically, so only a period outside a number can end a
quotation; the offline suite pins a decimal-threshold sentence verbatim.

**Guardrails added** (each falsified before being kept):

* Ledger check `enso-strength-verbatim` (**check 72**): every published quote
  must be a whitespace-collapsed substring of the archived ENSO discussion;
  the archive must trace to a recorded fetch and be usable as a current
  source; quote keys must come from `patterns_watched_for`; an `available`
  block must have the archive and non-empty quotes; an unavailable block must
  state a reason and carry no quotes; no quote may contain control characters
  or U+FFFD. Falsified by 8 new cases in `tests/falsify_guards.py` (edited
  quote, hand-added key, block removed, archive deleted, honest
  unavailability passing, mojibake smuggling, U+FFFD smuggling, stale
  discussion quoted as current) — 73 cases total.
* Render guard 31 in `tests/smoke.js`: every strength quote in the dataset
  must render inside the outlook strip with the no-added-number marker and
  the source link; an unavailable card must state its reason. Falsified by 4
  new cases in `tests/falsify_smoke.py` (renderer drops a quote — asserting
  the fixture carries two first, so a rewritten discussion cannot no-op the
  case — marker removed, link removed, unavailable card without its reason)
  — 31 cases total.
* 13 new offline assertions in `tests/test_parsers.py` pin the extractor
  against synthetic discussions: full extraction, both sentences verbatim,
  issuance line, source/hash lineage, rewritten discussion (both absent,
  named), control-character refusal with the surviving sentence still
  published, U+FFFD refusal, missing archive, empty enso file, stale-discussion
  refusal, the decimal-threshold tail, and the committed `landlord.json`
  block equal to a fresh extraction over the committed `enso.json` — **439
  assertions total**.

### Live re-verification (~21:55 UTC, after the data refresh)

Every item fetched live from the official product and compared against the
committed dataset:

| Product | Live official URL | Result |
| --- | --- | --- |
| NWS daily forecast, grid MTR 82,105 | https://api.weather.gov/gridpoints/MTR/82,105/forecast | All 14 committed periods **exact match** (This Afternoon 66 °F PoP 0; Sun 62 °F PoP 1; Mon 62/58 °F PoP 2/2; Tue 64/57 °F PoP 0/0; Wed 70/58; Thu 72/59; Fri 68 °F) |
| NWS alerts, zone CAZ006 | https://api.weather.gov/alerts/active?zone=CAZ006 | 0 active alerts, updated 21:55 UTC — matches the committed count |
| Official ONI file | https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt | Last line `JJA 2026 +1.80` — **exact match**; AMJ derived 0.98 vs official 0.95 (0.03 ERSST-lag difference, documented) |
| ENSO Diagnostic Discussion (issued 10 Sep 2026) | https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml | Page matches the archived text verbatim, including both published strength sentences in full (the 90% synopsis sentence and the 75% historic-event sentence with its +2.5 °C RONI threshold); next discussion 8 Oct 2026 |
| CPC long-lead Prognostic Discussion fxus05 (issued 17 Sep 2026) | https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html | Issuance line, OND wording, the third caveat sentence ("may be increased further … mid-late October") and the "superseded … Oct 15 2026" line all match the archived text — page unchanged since the pipeline's fetch |

### Standings after this pass

* `pipeline/verify_claims.py`: **72 checks pass, 0 fail, 0 warnings** (71 +
  `enso-strength-verbatim`), 19 recorded claims.
* `tests/test_parsers.py`: **439/439** (426 + 13). `tests/falsify_guards.py`:
  **73 cases** behave (65 + 8). `tests/falsify_smoke.py`: **31 cases** behave
  (27 + 4). `npm test` (jsdom render, guards 1–31) passes.
* Data files regenerated offline from the same verified inputs:
  `data/landlord.json` (carries the strength block), `data/executive_summary.md`/`.json`
  (the new strength bullet), `data/verify.json` / `verify_report.txt` (72
  checks). Nothing else in `data/` changed.
* New/changed files: `pipeline/landlord_summary.py`,
  `pipeline/executive_summary.py`, `pipeline/verify_claims.py`,
  `assets/js/app.js`, `tests/smoke.js`, `tests/test_parsers.py`,
  `tests/falsify_guards.py`, `tests/falsify_smoke.py`, `README.md`,
  `docs/LIMITATIONS.md`, `docs/NEXT_SESSION.md`, this file.

## Session 13 — 20 September 2026 (pass 13): verbatim-quote fidelity, the duration question asked of *this* ENSO phase, live re-verification

### Live re-verification against the official products (20 Sep 2026, ~01:00 UTC)

Each row was fetched from the official product with the sandbox's browser-grade
fetch tool and compared character-by-character with the committed dataset. The
pipeline itself runs on GitHub Actions runners, which reach NOAA normally.

| Product | Live official URL | Result |
| --- | --- | --- |
| Official ONI file | https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt | Last two rows `MJJ 2026 29.02 +1.39` and `JJA 2026 29.09 +1.80` — **exact match** with `data/enso.json` `official_oni` (including the AMJ 2026 `+0.95` the project's own derivation cross-checks at 0.98) |
| ENSO Diagnostic Discussion (issued 10 Sep 2026) | https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml | Status `El Niño Advisory`, the synopsis and the 75%-historic-event sentence all present **verbatim**; next discussion `8 October 2026` confirmed |
| CPC long-lead Prognostic Discussion fxus05 (issued 17 Sep 2026) | https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html | Issuance line `830 AM EDT Thu Sep 17 2026`, all three quoted caveats (negative PDO `-1.11`, "may dampen the typical impacts", "may be increased further … mid-late October") and the supersession line `Oct 15 2026` all present **verbatim** |
| NWS gridpoint forecast, grid MTR 82,105 | https://api.weather.gov/gridpoints/MTR/82,105/forecast | `updateTime 2026-09-19T20:26:32+00:00` and `elevation 45.1104 m` — **exact match** with `data/calendar.json` `current_forecast`; period temperatures 66/58/62/58/62/58/64/57/70/58/72/59/68 °F match the committed `nws.json` periods |
| NWS hourly product | https://api.weather.gov/gridpoints/MTR/82,105/forecast/hourly | 156 hourly periods running to **2026-09-26T05:00-07:00**, i.e. the committed `nws_window` first/last day (2026-09-19 → 2026-09-26, 8 days) is right — and note the product's own `validTimes` header (`P7DT11H`) stops *before* the periods it publishes, so deriving the window from the header instead of the hours would have dropped a day |
| NWS alerts, forecast zone CAZ006 | https://api.weather.gov/alerts/active?zone=CAZ006 | Empty feature collection, `updated 2026-09-20T00:59:14+00:00` — matches the committed `count: 0` |

**Method limitation, stated rather than glossed.** The sandbox's fetch tool
returns **HTTP 500 for NCEI's `access/*.csv` endpoints** (both `normals-daily`
and `normals-monthly` for `USW00023272`), although the NCEI directory indexes
and the CPC/NWS products fetch normally. The GHCN-Daily, GSOD, ISD and normals
files therefore could **not** be re-read live from here; they are verified by
the pipeline's own recorded fetch (URL, HTTP status, byte count, SHA-256 in
`data/provenance.json`) and by the ledger's re-derivation from the same bytes,
not by an independent copy fetched in this session. That is a real gap in the
session's verification and it is recorded here as one.

### Bug 73 — a quotation the page called verbatim carried a space NOAA never wrote

* **Symptom.** The ENSO strength sentence on the outlook strip read
  `… (+2.5°C or more for a 3-month RONI value ).` — with a space before the
  closing bracket.
* **Root cause.** `pipeline/main.py` `html_to_text()` replaced **every** HTML tag
  with a space, which is right for block markup and wrong for inline markup. The
  discussion hyperlinks `3-month RONI value`, so `</a>)` became ` )`. A browser
  renders `value).`.
* **How it was caught.** The same sentence exists as plain text in CPC's own
  `fxus05` product (a `<pre>` block, no inline markup), and there it reads
  `(+2.5°C or more for a 3-month RONI value).` — no space. Two official
  renderings of one sentence disagreed, so one of them was this project's.
* **Fix.** Inline tags (a fixed list, longest-first alternation) are now removed
  **without** inserting a space; block-level tags keep the space. `img` and
  anything unrecognised still separate, so two words can never be spliced.
* **Why it mattered.** The page's promise is that quoted sentences are what the
  publisher wrote. A fidelity defect, not a numbers defect — and it was invisible
  because the ledger's `quotes-plain-text` check compared the quotation with the
  project's own extraction of the same page, which contained the same artifact.
  The check is still worth having; the lesson is that a quotation can only be
  checked against a second, independent rendering of the same official text.
* **Effect.** The archived discussion text and the quotations built from it are
  regenerated on the next pipeline run (the archive stores the converted text,
  so the committed copies still carry the old space until that run). Five offline
  assertions now pin the behaviour, including the prefix hazard (`<span>` must
  not be eaten as `<s>pan`).

### The rain-duration question, asked of the phase this season is actually in

The site answered "how much rain" per ENSO phase but answered "how many days
straight" only over all 30 seasons. For a season running under a strong El Niño
that is the wrong denominator, so `climo.enso_stratified_streaks()` now publishes,
per phase: `n`, the seasons-with-a-≥3/5/7/10-day-spell counts and percentages,
and the longest-spell distribution. It is computed from the same `season_by_year`
rows the other phase table uses, so the two cannot disagree about which season is
in which phase.

| Phase | Seasons (n) | Any 7+ day wet spell | Longest spell, mean (max) |
| --- | --- | --- | --- |
| El Niño | 11 | 9 of 11 = **81.8%** | 9.1 days (17) |
| Neutral | 7 | 3 of 7 = 42.9% | 6.1 days (10) |
| La Niña | 12 | 4 of 12 = 33.3% | 6.3 days (11) |
| All 30 seasons | 30 | 16 of 30 = 53.3% | 7.3 days (17) |

Where it appears: the bottom-line answer to question 2 (with `n` printed and the
confidence line now reading `n = 30 seasons; the phase split rests on 11 of them`),
as an evidence row in cost driver 1, as two columns in the ENSO table on the
season card, and automatically in the printable executive summary (both places —
Q2's table and the driver table).

Guard: the ledger's new `enso-streaks-recompute` check re-derives the whole block
from the same season rows and fails on any difference. Four falsification cases
prove it can fail (a percentage edited by hand; a count moved without its
percentage; the block stripped; a phase invented with no seasons behind it), and
two render guards prove the column and its denominator reach the page and can
disappear loudly.

Regeneration note: the pipeline could not fetch NOAA from the sandbox, so
`data/climatology.json` was given the new block by calling the pipeline's own
function on the season rows already in that file, and every downstream dataset
was then rebuilt by the committed offline builders (`build_calendar`,
`landlord_summary`, `executive_summary`, `build_digest`, `build_feed`). The next
nightly run re-derives all of it from the fetched sources; `calendar.json`
gained exactly the one new key and nothing else changed.

### Standings after this pass

* `pipeline/verify_claims.py`: **73 checks pass, 0 fail, 0 warnings** (72 +
  `enso-streaks-recompute`), 19 recorded claims. Verified by running the ledger
  in the sandbox against the regenerated datasets.
* `tests/test_parsers.py`: **450/450** (439 + 6 quote-fidelity + 5 phase-streak).
  `tests/falsify_guards.py`:
  **77 cases** behave (73 + 4). `tests/falsify_smoke.py`: **33 cases** behave
  (31 + 2). `npm test` (jsdom render) passes with the new column present.
* Changed files: `pipeline/main.py`, `pipeline/climo.py`,
  `pipeline/build_calendar.py`, `pipeline/landlord_summary.py`,
  `pipeline/verify_claims.py`, `assets/js/app.js`, `tests/smoke.js`,
  `tests/test_parsers.py`, `tests/falsify_guards.py`, `tests/falsify_smoke.py`,
  `README.md`, `docs/*`.
* Still open from earlier sessions and unchanged here: multi-ZIP support, the
  GHCNh/SSODv2 wind stitching, the CPC archive back-fill, and the two PR-15
  follow-ups. See `docs/NEXT_SESSION.md`.

## Session 13 addendum — first live pipeline run on the new code

The session-13 changes were committed, pushed and executed end to end by the
`Update NOAA data` workflow (run `35480736701`, green, 2026-09-20T01:23Z), which
re-fetched every official source and re-derived every published dataset. Both
session-13 changes therefore now have a live proof, not only a fixture proof:

| Item | Live result after the rerun |
| --- | --- |
| Bug 73 (inline-tag space in verbatim quotes) | The regenerated `3-month RONI value` sentence reads `… 3-month RONI value).` — no space before the parenthesis. The published quotation now matches CPC's own plain-text rendering character for character. |
| `enso-streaks-recompute` ledger check on freshly fetched data | **PASS** — "all phases match". The phase-conditioned block was recomputed from the season rows built in this run, not copied from our earlier data. |
| Phase figures stable across a fresh fetch | El Niño 9 of 11 = 81.8% (longest mean 9.1 d); La Niña 4 of 12 = 33.3%; Neutral 3 of 7 = 42.9%. |
| Bottom-line answer 2 | Renders the phase sentence plus its denominator: `Any 7+ day wet run in El Niño seasons on record (11 of the 30) — 81.8% of those seasons (9 of 11)`. |

Ledger after the live run: **73 passed, 0 failed, 0 warnings**. The remaining watch
item — the `Oct 15 2026` supersession line and the `mid-late October` revision
language — still needs the mid-October discussion to move, and stays on the
`NEXT_SESSION.md` list.

## Session 14 — 20 September 2026 (pass 14): severity conditioned on the ENSO phase, the wind-station wording withdrawn, the Congress-vintage hole, live re-verification

### Live re-verification against the official products (20 Sep 2026, ~02:00 UTC)

Every fetch below was made from the session, read in full, and compared with the
committed datasets (`main` at `d5b1030`, the 01:38Z refresh). Nothing on the site
was found to differ from its source. The sandbox itself has no direct network
egress, so the pipeline was **not** run locally — the live proof of the new
checks is the CI run this branch triggers.

| Product | Fetched | Compared with | Result |
| --- | --- | --- | --- |
| CPC ONI `oni.ascii.txt` | tail of the table | `data/enso.json` | ✓ `JJA 2026 … 1.80`, El Niño, strong band |
| CPC ENSO Diagnostic Discussion (10 Sep 2026) | full text | strength-card quotes, alert status | ✓ El Niño Advisory; `75% chance of a historic event … 3-month RONI value).` verbatim (bug 73 stays fixed); next discussion 8 Oct 2026 |
| CPC prognostic discussion `fxus05` (830 AM EDT Thu Sep 17 2026) | 3 chunks, full text | caveat-card quotes, DJF/JFM probabilities | ✓ PDO `-1.11` sentence, `may dampen` sentence, `mid-late October` sentence verbatim; `superseded … Oct 15 2026` present; CA coastal maximum 50–60% in DJF/JFM/FMA |
| NWS `gridpoints/MTR/82,105/forecast` | 14 periods (generated 02:04Z) | `data/nws.json` (updateTime 2026-09-19T20:26:32Z) | ✓ identical temperatures/POPs/winds; only period 1's start hour advanced with generation time (expected API behaviour, not an irregularity); no rain in the window |
| NWS `alerts/active?zone=CAZ006` | live | alert count | ✓ `features: []` — 0, as published |
| NCEI GSOD README (10/28/2020) | full text | units/UTC-day statements on the site | ✓ knots in tenths, PRCP hundredths, day = 0000Z–2359Z, `GUST/PRCP appear less frequently` |
| NCEI `normals-daily/1991-2020/access/USW00023272.csv` | — | — | ✗ **HTTP 500 through the fetch tool** (session 13 saw the same on GHCN-Daily/GSOD `access/*.csv`). Not a data error: CI fetched the file per `data/provenance.json` (status, bytes, SHA-256 recorded). The large NCEI files remain a known gap for manual re-fetching from the session and are listed as such. |

### Feature: hard-rain days, gusts and wind + rain, asked of *this* ENSO phase (closes handoff priority 1)

Session 13 conditioned only the **duration** question on the phase. This pass
conditions the **severity** counters the same way, with the same rule that every
figure prints its own `n` and calls itself an observed frequency, not a forecast.

* `pipeline/climo.py` — `ENSO_SEVERITY_FIELDS` names ten per-season counters
  that already existed in the season rows (`wet_days_ge_050in`, `_1in`, `_2in`,
  `max_daily_prcp_in`, `wind_and_rain_days`, `heavy_wind_and_rain_days`,
  `severe_wind_and_rain_days`, `gust_days_ge_40kt`, `wind_days_ge_30kt`,
  `max_gust_mph`). `enso_stratified_severity()` summarises each per phase
  (n, mean, median, min, max, p10/p90, `seasons_with_any`); an absent counter
  publishes `n: 0`, never a zero. Published under
  `calendar.enso_stratified_severity`.
* `pipeline/landlord_summary.py` — `phase_conditioned_severity()` builds the
  strip block (`official_outlook.enso_conditioned_severity`: current phase,
  `seasons_in_phase`, `seasons_total`, ten rows each carrying the phase mean /
  median / max **beside the all-season mean and max**). Bottom-line answers 3–6
  and cost drivers 2–4 gained phase rows in the fixed pattern
  `<label> in El Niño seasons on record (11 of the 30)` → `mean a · median b ·
  max c — all 30 seasons: mean d`, plus one sentence each.
* `assets/js/app.js` — a full-width strip cell (`data-test="enso-conditioned-severity"`)
  renders the table with its fine print and three source links; the
  season-by-season ENSO card gained three columns (`Days ≥ 1.00 in, mean`,
  `Days gust ≥ 40 kt, mean`, `Wind + rain days (whole-day), mean`, each with
  the worst season in brackets).
* `pipeline/verify_claims.py` — new check **`enso-severity-recompute`**
  rebuilds the whole table from the 30 season rows in `climatology.json`, then
  checks every derived bottom-line / cost-driver row (n, mean, median, max, and
  the `(n of the N)` label) against it, and fails if the current phase is in
  the table but the derived rows are missing. Ledger: **74 checks**.
* Falsified: `tests/falsify_guards.py` +6 (mean edited by hand; table stripped;
  phase invented with no seasons; derived row drifted; bottom-line row naming a
  different n; derived rows removed while the phase is in the table);
  `tests/falsify_smoke.py` +9 (table not rendered; a value re-rounded; `n`
  missing; caveat missing; a row dropped; ENSO card column removed; a cell
  rendered with no rows behind it; the `upper bound` wording reintroduced in
  the dataset; the same wording reintroduced in `index.html`).

What the numbers say (1991–2020, El Niño n = 11 / La Niña 12 / Neutral 7): El
Niño seasons averaged **3.7** days ≥ 1.00 in against **3.2** over all 30, and
**3.2** days with a gust ≥ 40 kt against **2.4**; the joint counters (11.5 vs
11.1 whole-day wind + rain days; 0.5 vs 0.5 days at ≥ 1.00 in with a ≥ 40 kt
gust) and the season-maximum gust (53.7 vs 53.8 mph) are indistinguishable
between phases at these sample sizes. The page says exactly that and nothing
stronger.

### Bug 74 — "SFO is an upper bound for the Sunset" had no source

| # | Symptom | Cause | Fix |
| --- | --- | --- | --- |
| 74 | The wind card, the bottom line, the cost drivers, the season-statistics card, the static wind paragraph in `index.html`, and five documents said SFO is *more exposed* than the Sunset and that every wind figure is therefore an **upper bound** for 94122 | Written in session 1 as a plausibility, then copied forward. No official source in this project establishes the direction: SFO sits on the bay shore, the Outer Sunset faces the open Pacific at Ocean Beach, and no official station inside 94122 holds a 30-year wind record to compare against. A directional claim without a source is exactly the kind of statement the project's rules forbid | The wording now states the station, the distance and the gap (`WIND_STATION_CAVEAT` in `landlord_summary.py`, one definition): *SFO reference value, not a bound for 94122*. `tests/smoke.js` guard 33 bans `upper bound for the Sunset/94122/ZIP/neighbourhood`, `SFO is more exposed` and `runs windier than the …` page-wide; `tests/test_parsers.py` pins the caveat text; both harnesses prove the ban fires. `README.md`, `docs/LIMITATIONS.md` (table row, three bullets, new §26), `docs/METHODS.md` §16, `docs/LANDLORD_GUIDE.md` and this file were corrected in place. The one remaining "upper bound" in `docs/METHODS.md` (§ NWS wind ranges, `"5 to 11 mph"` → 11) is a different, correct usage |

### Bug 75 — a hard-coded Congress number blanked the congressional district

| # | Symptom | Cause | Fix |
| --- | --- | --- | --- |
| 75 | PR #24's data diff shows two CI runs 15 minutes apart on 20 Sep 2026 disagreeing on the Census geography block: the 01:23Z run published `congressional_district: null` with `geography_types_returned` listing **`120th Congressional Districts`** and **2026** state-legislative layers; the 01:38Z run (now on `main`) published `Congressional District 11` under **`119th Congressional Districts`** and **2024** layers | The Census geocoder's `Current_Current` vintage is not stable across its servers, and `climo.parse_census_geographies` read the layer by the literal key `"119th Congressional Districts"`. When the geocoder answered with the 120th-Congress layer the district was in the response and the page printed a dash | `_congressional_layer_key()` picks the highest-numbered `<n>th Congressional Districts` layer present (bare `Congressional Districts` as fallback) and the parser now publishes `congressional_district_layer` beside the name, so the vintage answered is visible. The page prints it (`Congressional District 11 (119th Congressional Districts)`). The ledger's `census-geographies-traceable` check now **fails** when a congressional layer was returned but no district published. Parser tests +5 (119th real fixture, 120th, both layers → newest, empty layer → None, look-alike names rejected); falsify_guards +2 (the hole fails; a 120th-layer district passes) |

The vintage flip itself is **flagged as an irregularity for review**: it is the
Census Bureau's behaviour, not this project's, and the site now shows which
layer it was given on each run rather than assuming one.

### Carried in from PR #24 (superseded, not merged)

PR #24 (branch `arena/01a0bc4f-sfweather`) corrected the published parser count
from 450 to "449–450" because one cross-check — the derived-window gust maximum
against the gust NWS's text forecast states — is guarded and skips when the text
forecast states no gust (as the 20 Sep 2026 forecast does). It could not merge
(`CONFLICTING` with the later data refresh on `main`); its correction is carried
here: the count is published as **473–474** (473 in this data state) with the
same explanation, and the PR is credited in `README.md`.

### Session 15 (20 Sep 2026 — Outer Sunset 94122 Property & Weather Profile; localized cost drivers; local Storm Events; guard 34)

#### Changes and enhancements

1. **Outer Sunset SF 94122 Property & Weather Profile**: Integrated an Outer Sunset
   profile card (`#landlord-sunset-card`) into both the dashboard interface and
   the executive summary outputs (`data/executive_summary.md` and `data/executive_summary.json`).
   Captures the geographical centroid (41st/42nd Ave, ~0.6 mi from Ocean Beach), direct
   Pacific oceanfront exposure, sandy dune subsoil with high water table, 1920s–1950s
   stucco row-home typology (zero-lot-line, flat roofs, parapet caps, internal lightwells,
   and subterranean drive-in garages), and marine salt-air corrosion.
2. **Neighborhood-calibrated cost driver guidance**: Re-anchored all six landlord cost
   drivers in `pipeline/landlord_summary.py` so the physical mechanisms reflect Outer Sunset
   building vulnerabilities (e.g., wind-driven rain soaking west-facing exterior stucco,
   internal lightwell drain backups, sewer surcharge at low-lying intersections, and
   salt spray attacking metal flashings and fasteners).
3. **Local Storm Events integration**: Parsed NOAA Storm Events for events explicitly
   citing the 94122 corridor (e.g. Judah & 30th Ave 6–12 inch roadway flooding, Great
   Highway storm closures) and integrated them directly into Driver 2 evidence.
4. **Enter key listener for Day Finder**: Added keyboard convenience (`keyup` Enter)
   on `#day-find` in `assets/js/app.js` to match the "Find" button.
5. **Render Guard 34 and Falsification**: Added guard 34 to `tests/smoke.js` asserting
   that `#landlord-sunset-card` renders with all 6 categories naming Outer Sunset 94122.
   Added 2 new falsification cases to `tests/falsify_smoke.py` (`_osp1`, `_osp2`),
   bringing the suite to 44 cases.
6. **Parser Test**: Added an offline test in `tests/test_parsers.py` confirming the
   Outer Sunset profile is present in both markdown and JSON executive summary outputs.

### Standings after this pass

* `pipeline/verify_claims.py`: **74 checks pass, 0 fail, 0 warnings**, 19 recorded claims.
* `tests/test_parsers.py`: **474/474** in this data state (475 with guarded gust check).
* `tests/falsify_guards.py`: **85 cases** behave as expected.
* `tests/falsify_smoke.py`: **44 cases** behave as expected.
* `npm test`: passes cleanly including guard 34.
* Changed files: `pipeline/landlord_summary.py`, `pipeline/executive_summary.py`,
  `assets/js/app.js`, `assets/css/style.css`, `index.html`, `tests/smoke.js`,
  `tests/test_parsers.py`, `tests/falsify_smoke.py`, `README.md`, `docs/*`,
  and regenerated `data/landlord.json`, `data/executive_summary.{md,json}`.
* Still open: the mid-October CPC issuances (8 Oct ENSO discussion, 15 Oct
  long-lead outlooks), multi-ZIP support, GHCNh/SSODv2 wind stitching, the CPC
  back-test archive. See `docs/NEXT_SESSION.md`.

## Session 16 — 20 September 2026 (pass 16): the ocean-side wind record (NDBC 46026), and two bugs it exposed

### Bug 77 — the modern NDBC header names two different columns `MM`

NDBC's current standard-met header is `#YY MM DD hh mm WDIR ...`. Uppercased, the
month column and the minutes column are the same token, and the parser resolved
columns by name — so every report's minutes were silently zeroed. Day-based
aggregation was unaffected (a truncated timestamp keeps its date), but the
published "strongest gust of the season: ... at" timestamps were wrong by up to 59
minutes, and the metadata could not tell a reader which resolution a file actually
carried. **Fix:** columns are resolved by occurrence (`MM` is the month, `MM#2` the
minutes), the metadata says whether the file resolves to the minute or to the hour,
and both the tier's self-test and `tests/test_parsers.py` assert that the four
ten-minute rows of the 2020-era fixture still read `[0, 10, 20, 30]`.

### Bug 78 — a season nobody observed was averaged in as a zero

The tier's first summary computed every counter over all 30 season rows. A season
with no data publishes integer day counters of 0 (correctly — the row itself must
show that nothing was counted), but averaging those zeros in made the headline read
"mean 0.07 gust days ≥ 34 kt per season" for a record whose observed seasons saw
gales. That is a statement about the outage, not about the ocean, and it is exactly
the kind of number a reader would have taken as "the ocean rarely blows".
**Fix:** `coverage_rule.counter_rule` now travels with the data — every mean,
median, minimum and maximum is computed over the seasons that observed at least one
Oct–Jan UTC date, the seasons used are listed in `summary.counted_seasons`, the
seasons left out are the ones already named beside the means, and the ledger
re-derives the counters under the declared rule (a dataset that declares a rule the
ledger does not know how to re-derive fails). The tier's self-test asserts both
halves: the unobserved season still publishes 0 in its own row, and it does not
appear in the mean.

### What was added, and how it is verified

* `pipeline/ocean_wind.py` (tier) and `pipeline/selftest_ocean_wind.py` (46 offline
  checks over recorded NDBC fixtures: three file eras, sentinels, unit conversion,
  season windows, coverage arithmetic, the counter rule, the station table, page
  discovery, an unparseable annual file and an empty station-history page).
* `tests/fixtures/ndbc/` — eight recorded fixtures, and
  `tests/fixtures/ocean_wind_render.json`, rebuilt from the tier's own `build()`
  with the corrected counters.
* `pipeline/verify_claims.py` §13h — six checks when the tier is published
  (`ocean-wind-recompute`, `-coverage`, `-station-identity`, `-marine-labelled`,
  `-units-verbatim`, `-isolation`), plus `ocean-wind-landlord-consistency` (§13i)
  and the `ocean-wind-published` warning when it is not.
* `tests/falsify_guards.py` — 11 ocean-wind cases, including the new
  `ocean-wind-marine-labelled`, `ocean-wind-units-verbatim` and the not-yet-published
  warning state.
* `tests/falsify_smoke.py` — 7 ocean-wind render cases, including the card going
  silent about an unpublished record.
* `assets/js/app.js` + `index.html` — the card, printing the dataset's caveat
  verbatim, every season row, the coverage sentence and the NDBC-only links.

### Standings after this pass

* `pipeline/verify_claims.py`: **76 checks pass, 0 fail, 0 warnings, 19 claims** in
  the committed state; **81** with the staged fixture build of `data/ocean_wind.json`.
* `tests/test_parsers.py`: **485/485** (486 with the guarded gust cross-check).
* `tests/falsify_guards.py`: **96 cases** behave as expected.
* `tests/falsify_smoke.py`: **51 cases** behave as expected.
* `npm test`: passes with the ocean-wind guard.
* `pipeline/ocean_wind.py --selftest`: **46/46**.
* Still open: the first live run of the tier, the mid-October CPC issuances,
  multi-ZIP support, GHCNh/SSODv2 wind stitching, the CPC back-test archive. See
  `docs/NEXT_SESSION.md`.

