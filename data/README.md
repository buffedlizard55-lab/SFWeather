# data/

This directory is **generated**, not hand-written. Every file here is produced by
`.github/workflows/update-data.yml`, which runs nightly at 07:15 UTC and on
every push to the repository.

| File | Contents |
| --- | --- |
| `run.json` | run metadata, the verified 94122 centroid, season bounds, fetch counts |
| `nws.json` | NWS point metadata, hourly and daily forecasts, observations, alerts, forecast discussion |
| `cpc.json` | CPC shapefile outlooks point-sampled at 94122 (6-10 d, 8-14 d, weeks 3-4, monthly/seasonal) |
| `enso.json` | Nino 3.4 anomalies, computed ONI, current phase and CPC discussion text |
| `climatology.json` | 1991-2020 per-calendar-date normals, wet streaks, wind statistics, ENSO stratification |
| `calendar.json` | the assembled Oct 1 - Jan 31 scoreboard, one record per day |
| `storm_events.json` | NCEI Storm Events records for San Francisco County (FIPS 06075) |
| `provenance.json` | every HTTP fetch: URL, status, bytes, SHA-256, retrieval timestamp |
| `quality_report.json` | irregularities detected during the run |
| `pipeline.log` | human-readable copy of the run log (reviewable without Actions logs) |

If this directory looks empty, the last run failed or has not completed yet; the
site shows an explicit error banner rather than rendering blanks.

Do not edit these files by hand. Change `pipeline/` and let the workflow rebuild
them.
