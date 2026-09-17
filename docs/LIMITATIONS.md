# Limitations, and what to build next

## Limitations that cannot be engineered away

### 1. No daily forecast exists for most of the window
The NWS gridded forecast reaches about 7 days. Every other official product is a
probability for a *period*. Any site, app or model that shows you a specific
temperature or rainfall for a named day in December 2026 is producing it from a
model or a guess, not from an official forecast. This project refuses to do that,
which necessarily makes the far end of the calendar less "exciting" than a
fabricated forecast would be.

**Mitigation:** two clearly separated tiers, nightly rebuild, and automatic
promotion of days into the `NWS FORECAST` tier as they come into range.

### 2. Two different stations, ~10 miles apart
Rain and temperature come from `USW00023272` (San Francisco Downtown); wind and
gusts from `72494023234` (SFO). The only long daily wind record near 94122 is at
the airport, and SFO's open exposure runs windier than the Sunset.

**Mitigation:** both stations are named, linked and their coordinates published
on the site; wind figures are described as an upper bound.

### 3. GSOD days are UTC days
Per the [NCEI README](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt),
GSOD values are summarised 0000Z-2359Z, which is roughly 16:00-16:00 Pacific.
GHCN rain days are local days. The joint "wind + rain" statistic therefore pairs
a local-day rainfall with a UTC-day wind figure for the same date.

**Mitigation:** stated on the site and in the data; the joint statistic is
described as an approximation. Fixing it properly requires hourly ISD data (see
below).

### 4. Small samples
Single-date percentages use 30 seasons. ENSO-stratified samples are 8-13 seasons
each. These are indicative, not precise.

### 5. San Francisco microclimates
A ZIP-code centroid is one point. The Sunset, Twin Peaks and downtown can differ
by several degrees and by meaningful rainfall on the same day.

### 6. Storm Events is a reported-events database
It contains what somebody reported to an NWS office. Quiet but damaging events
may be absent.

### 7. No bias correction, downscaling or post-processing
Numbers are used exactly as published. A research-grade product would calibrate
CPC probabilities against local observations and downscale to the neighbourhood.

### 8. AccuWeather and commercial providers are excluded
They are not open, not free in the sense required here, and not independently
verifiable line by line. If you want a second opinion you must go and read it
yourself - this project cannot vouch for it.

---

## Recommended next work, in priority order

### High value, moderate effort

1. **Hourly ISD wind for a true local day.** Replace GSOD with the NOAA
   Integrated Surface Database hourly file
   (`/data/global-hourly/access/{year}/{station}.csv`) so wind days match the
   local calendar day used for rain, and so "wind + rain at the same time" can be
   tested hour by hour instead of day by day. This directly improves the answer
   to "simultaneous wind and rain events".

2. **Back-test the CPC signal for San Francisco.** The archive holds 6-10 day and
   monthly outlooks going back years. Sample the archive shapefiles for past
   issuance dates and score them against what actually happened, so the site can
   say "when CPC tips above-median for OND here, it verified X% of the time"
   instead of only reporting the tip.

3. **Atmospheric-river awareness.** ARs drive almost all of California's
   high-impact winter rain. NOAA/NWS does not publish a per-day AR forecast, but
   the NWS Bay Area Area Forecast Discussion discusses them; extracting
   AR-related language from the AFD (text already fetched) would add real signal
   for the "days of straight rain" question.

4. **Verification of the NWS 7-day forecast.** Store each night's forecast and
   score it against the next day's observations. Turns the site from a viewer
   into an accountability tool.

### Moderate value, low effort

5. **Station comparison.** Add `USW00023234` (SFO) and any nearer cooperative
   stations alongside downtown, and show the spread between them as an explicit
   uncertainty range for the neighbourhood.

6. **Printable / CSV export** of the whole Oct-Jan scoreboard for offline use.

7. **Email or RSS digest** when a day enters the 7-day window with a high POP, or
   when an NWS alert is issued for `CAZ006`.

### Larger undertakings

8. **CFSv2 / NMME ensemble sampling.** NCEP publishes the Climate Forecast System
   and the North American Multi-Model Ensemble openly on NOMADS. Sampling them
   would give a genuine *model* view of Oct-Jan - but it requires GRIB2 decoding
   (`eccodes`/`cfgrib`), heavy storage, and very prominent caveats: raw
   single-member daily output at 2-6 month leads has little skill for a specific
   day and is **not** an official forecast.

9. **Bias correction and downscaling** of the gridded guidance to the Sunset,
   calibrated against the downtown gauge.

10. **Interactive map** allowing any ZIP code, not just 94122 - the pipeline is
    already parameterised by coordinate, so this is mostly front-end work.

---

## Operational notes

* The nightly job runs at **07:15 UTC (00:15 Pacific)**, after the NWS 00Z cycle
  and after CPC posts its daily 6-10 / 8-14 day outlooks.
* `pipeline/verify_sources.py` fails the build on any non-official host.
* The workflow commits data with `[skip ci]` so it cannot trigger itself.
* The site is static; it degrades to an explicit error banner if `data/` is
  missing rather than rendering blanks.
