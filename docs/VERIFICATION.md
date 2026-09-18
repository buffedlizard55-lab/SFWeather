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
| 47 | **Two of my own new render guards were wrong on the first falsification run**: the quotation-key check counted *sentences* instead of *keys* (always failing), the basis guard read a third table cell that does not exist (the basis renders inline in a `.fine` span), and the scope check was keyword-based so it still passed with the caveat stripped | Guards written against an assumed DOM shape and an unflattened `flatMap` | All three rewritten; the scope guard now asserts the published `scope_caveat`, `usage_note` and `verbatim_rule` strings appear on the page, so a renderer reading the wrong key cannot pass |

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
