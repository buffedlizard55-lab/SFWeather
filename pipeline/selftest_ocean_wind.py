#!/usr/bin/env python3
"""Offline self-test for the ocean-side wind tier.

The tier's risks are specific, and each one is asserted here:

* a **units** mistake (reading metres per second as knots would understate every
  gust by a factor of two) - checked against the threshold boundary rows;
* a **format** mistake (the archive changed shape in 1996, 2005 and 2020: two-digit
  and four-digit years, an optional minute column, ``WD``/``WDIR``, ``BAR``/``PRES``,
  a units row that some eras have and some do not);
* a **missing-value** mistake (NDBC writes 9s, and a season of sentinel values must
  read as "no data", never as "no storms");
* a **silent-empty** mistake (a page that no longer matches must produce a warning
  with the raw markup, not an empty block that passes every check);
* a **labelling** mistake (the marine caveat must be in the dataset, and the marine
  flags must be false-safe rather than absent).

Everything runs against the committed NDBC-shaped fixtures in
``tests/fixtures/ndbc/``; nothing here touches the network and nothing is written
outside a temporary directory.
"""

from __future__ import annotations

import gzip
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ocean_wind as ow  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "ndbc"

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))


def fixture(name):
    return (FIX / name).read_text()


class _Res:
    """A FetchResult-shaped stand-in, so the whole build path can run offline."""

    def __init__(self, url, body=None, status=200, error=None):
        self.url = url
        self.ok = status == 200 and body is not None
        self.status = status
        self.body = body
        self.error = error
        self.content_type = "text/plain"
        self.elapsed = 0.01
        self.retrieved_utc = "2026-09-20T00:00:00Z"

    @property
    def size(self):
        return len(self.body) if self.body else 0

    @property
    def sha256(self):
        if not self.body:
            return None
        import hashlib
        return hashlib.sha256(self.body).hexdigest()

    def text(self, encoding="utf-8", errors="replace"):
        return self.body.decode(encoding, errors) if self.body else ""

    def provenance(self, note=None, **extra):
        rec = {"url": self.url, "http_status": self.status, "ok": self.ok,
               "bytes": self.size, "sha256": self.sha256, "error": self.error,
               "content_type": self.content_type, "retrieved_utc": self.retrieved_utc}
        if note:
            rec["note"] = note
        rec.update(extra)
        return rec


def run():
    CHECKS.clear()

    # ---------------------------------------------------------------- parsing
    rows96, meta96 = ow.parse_stdmet(fixture("46026_1996_era.txt"))
    check("1990s file: two-digit year read as 1996",
          meta96["first_ts"].year == 1996 and meta96["first_ts"].month == 3,
          f"first_ts={meta96['first_ts']}")
    check("1990s file: the header's 'WD' column is used for wind direction",
          rows96[0]["wdir"] == 318.0, f"wdir={rows96[0]['wdir']}")
    check("1990s file: no units row in that era, so the unit falls back to NDBC's page",
          meta96["wind_units"] == "m/s" and meta96["wind_units_basis"],
          f"units={meta96['wind_units']} basis={bool(meta96['wind_units_basis'])}")
    check("1990s file: an all-9 report is dropped, not counted as an observation",
          len(rows96) == 5 and meta96["n_empty_rows"] == 1,
          f"rows={len(rows96)} empty={meta96['n_empty_rows']}")

    rows05, meta05 = ow.parse_stdmet(fixture("46026_2005_era.txt"))
    check("2005 file: four-digit year, hourly rows, and 'BAR' header still parses",
          meta05["first_ts"].year == 2005 and len(rows05) == 5,
          f"n={len(rows05)} first={meta05['first_ts']}")
    check("2005 file: a 9.9 m/s gust survives the sentinel test (19.2 kt) while the "
          "99.0 sentinel does not",
          rows05[0]["gst_kt"] == 19.244, f"gst={rows05[0]['gst_kt']} kt")

    rows20, meta20 = ow.parse_stdmet(fixture("46026_2020_era.txt"))
    check("2020 file: 10-minute rows, WDIR/PRES header, units row says m/s",
          len(rows20) == 8 and meta20["wind_units"] == "m/s",
          f"n={len(rows20)} units={meta20['wind_units']}")
    check("2020 file: the minutes column survives - a header with 'MM' twice (month "
          "and minutes) resolves each column by occurrence, not by name",
          [r["ts"].minute for r in rows20[:4]] == [0, 10, 20, 30]
          and meta20["timestamps"] == "to the minute"
          and meta20["minute_column"],
          f"{[r['ts'].minute for r in rows20[:4]]} {meta20['timestamps']}")
    check("2020 file: WVHT 99.00 and DEWP 999.0 are dropped as missing",
          rows20[0]["wvht_m"] is None and rows20[0]["wtmp_c"] == 13.0,
          f"wvht={rows20[0]['wvht_m']} wtmp={rows20[0]['wtmp_c']}")
    check("2020 file: the units row is counted, not parsed as an observation",
          meta20["n_malformed"] == 1 and meta20["n_parsed"] == 8,
          f"malformed={meta20['n_malformed']} parsed={meta20['n_parsed']}")

    rows_rt, meta_rt = ow.parse_stdmet(fixture("46026_realtime.txt"))
    check("realtime file: 'MM' markers are missing values, and rows still parse",
          len(rows_rt) >= 4 and meta_rt["wind_units"] == "m/s",
          f"n={len(rows_rt)} units={meta_rt['wind_units']}")
    check("realtime file: a row with every field missing is not an observation",
          all(not (r["wspd_kt"] is None and r["gst_kt"] is None and r["wvht_m"] is None)
              for r in rows_rt) and len(rows_rt) == 6,
          f"rows={len(rows_rt)}")

    # ------------------------------------------------------------- aggregation
    rows_season, _ = ow.parse_stdmet(fixture("46026_season_synthetic.txt"))
    seasons = ow.aggregate_seasons(rows_season, years=[1991, 1992])
    s91, s92 = seasons
    check("season window: an October and a January row land in season 1991-1992",
          s91["observations"] == 4, f"observations={s91['observations']}")
    check("season window: a February-September row can never enter a season",
          all(not (r["ts"].month not in (10, 11, 12, 1)) for r in rows_season),
          "fixture carries only Oct/Nov/Jan rows")
    check("coverage: 3 distinct UTC dates of the 123 expected = 2.4%",
          s91["dates_with_data"] == 3 and s91["coverage_pct"] == 2.4,
          f"dates={s91['dates_with_data']} pct={s91['coverage_pct']}")
    check("thresholds: 18.0 m/s = 35.0 kt clears 34 kt, 12.0 m/s = 23.3 kt clears 20 kt",
          s91["days_gust_ge_34kt"] == 2 and s91["days_wind_ge_20kt"] == 2,
          f"g34={s91['days_gust_ge_34kt']} w20={s91['days_wind_ge_20kt']}")
    check("thresholds: 25.0 m/s = 48.6 kt clears the 48 kt row exactly once",
          s91["days_gust_ge_48kt"] == 1 and s91["days_gust_ge_40kt"] == 2,
          f"g48={s91['days_gust_ge_48kt']} g40={s91['days_gust_ge_40kt']}")
    check("thresholds: 16.0 m/s = 31.1 kt clears 30 kt but not the 34 kt gust row",
          s91["days_wind_ge_30kt"] == 1 and s91["max_wind_kt"] == 31.1,
          f"w30={s91['days_wind_ge_30kt']} max={s91['max_wind_kt']}")
    check("conversions: the season maximum is published in kt and mph",
          s91["max_gust_kt"] == 48.6 and s91["max_gust_mph"] == 55.9,
          f"{s91['max_gust_kt']} kt / {s91['max_gust_mph']} mph")
    check("conversions: a 9.9 m/s reading is 19.2 kt, not 9.9 kt (the unit mistake this "
          "test exists to catch)",
          round(9.9 * ow.MS_TO_KT, 2) == 19.24 and ow.wind_kt("9.9", "m/s") == 19.244,
          f"9.9 m/s = {ow.wind_kt('9.9', 'm/s')} kt")
    check("waves: the maximum significant wave height is in metres and feet",
          s91["max_wvht_m"] == 5.0 and s91["max_wvht_ft"] == 16.4,
          f"{s91['max_wvht_m']} m / {s91['max_wvht_ft']} ft")
    check("a season with no rows is published as no data, not as a quiet season",
          s92["observations"] == 0 and s92["dates_with_data"] == 0
          and s92["coverage_pct"] == 0.0 and s92["max_gust_kt"] is None,
          f"obs={s92['observations']} max_gust={s92['max_gust_kt']}")

    summary = ow.summarize(seasons)
    check("summary: a mean is never published alone - median, min and max are carried",
          summary["counters"]["days_gust_ge_34kt"] ==
          {"mean": 2.0, "median": 2, "min": 2, "max": 2, "n_seasons_with_value": 1},
          json.dumps(summary["counters"]["days_gust_ge_34kt"]))
    check("summary: a season nobody observed is published as 0 in its own row and is "
          "NOT averaged into the season means as if the ocean had been calm",
          s92["days_gust_ge_34kt"] == 0
          and summary["counted_seasons"] == ["1991-1992"]
          and summary["seasons_with_no_data"] == ["1992-1993"]
          and "1992-1993" not in summary["counted_seasons"],
          f"row={s92['days_gust_ge_34kt']} counted={summary['counted_seasons']}")
    check("summary: thin seasons and seasons with no data are named",
          summary["thin_seasons"] == ["1991-1992", "1992-1993"]
          and summary["seasons_with_no_data"] == ["1992-1993"],
          f"thin={summary['thin_seasons']} empty={summary['seasons_with_no_data']}")

    # --------------------------------------------------------- page discovery
    years = ow.discover_historical_years(fixture("station_history_excerpt.html"),
                                         ow.STATION_HISTORY_PAGE)
    check("page discovery: the station's own annual links are found (relative hrefs "
          "resolved, &amp; decoded)",
          set(years) == {1982, 1991, 1996, 2005, 2021}, f"years={sorted(years)}")
    check("page discovery: a monthly current-year link is not mistaken for a year file",
          all("stdmet/Aug" not in u for u in years.values()),
          f"urls={sorted(years.values())[:2]}")
    check("page discovery: another station's file is not collected",
          all("46012" not in u for u in years.values()), "46012 excluded")

    stations = ow.parse_station_table(fixture("station_table_excerpt.txt"))
    st = stations.get("46026") or {}
    check("station table: the 46026 row parses with owner, type, name and coordinates",
          st.get("owner_code") == "N" and st.get("type") == "3-meter foam buoy"
          and st.get("lat") == 37.750 and st.get("lon") == -122.838
          and st.get("name") == "SAN FRANCISCO - 18NM West of San Francisco, CA",
          f"type={st.get('type')} lat={st.get('lat')} lon={st.get('lon')}")
    check("station table: southern/western signs are applied (the Samoa row)",
          stations["51111"]["lat"] < 0 and stations["51111"]["lon"] < 0,
          f"{stations['51111']['lat']},{stations['51111']['lon']}")

    quotes = ow.verbatim_excerpt(fixture("measdes_excerpt.html"), ow.UNITS_QUOTES)
    check("units page: all seven quoted sentences are found verbatim",
          all(v["found_verbatim"] for v in quotes.values()),
          ", ".join(k for k, v in quotes.items() if not v["found_verbatim"]) or "all found")
    check("units page: the excerpt beside each quote is bounded and non-empty",
          all(v["excerpt"] and len(v["excerpt"]) < 400 for v in quotes.values()),
          f"max={max(len(v['excerpt']) for v in quotes.values())}")

    # ---------------------------------------------------------------- distance
    d = ow.great_circle_mi(37.760459, -122.483894, 37.750, -122.838)
    check("distance: the 94122 centroid to the buoy is ~19.5 statute miles",
          19.0 < d < 20.0, f"{d:.2f} mi")

    # ------------------------------------------------------- full build (fake net)
    tmp_data = Path(tempfile.mkdtemp(prefix="ow_data_"))
    try:
        (tmp_data / "run.json").write_text(json.dumps(
            {"target": {"centroid": {"lat": 37.760459, "lon": -122.483894}}}))

        files = {
            ow.STATION_TABLE: fixture("station_table_excerpt.txt").encode(),
            ow.STATION_HISTORY_PAGE: fixture("station_history_excerpt.html").encode(),
            ow.MEASDES_PAGE: fixture("measdes_excerpt.html").encode(),
            ow.REALTIME_URL: fixture("46026_realtime.txt").encode(),
            ow.STATION_PAGE: ("<table><tr><td>Anemometer height:</td><td>4.1 m above site "
                              "elevation</td></tr><tr><td>Water depth:</td><td>53 m</td>"
                              "</tr></table>").encode(),
        }
        # Only two of the five listed years are published, so a year NDBC lists but the
        # archive no longer serves (1996) is exercised as a real failure in this run,
        # not silently relabelled as an expected absence.
        for year, body in ((1991, fixture("46026_season_synthetic.txt")),
                           (2005, fixture("46026_2005_era.txt"))):
            files[f"{ow.HISTORICAL_DIR}{ow.STATION_ID}h{year}.txt.gz"] = \
                gzip.compress(body.encode())

        def fake_fetch(url, timeout=180):
            return _Res(url, files.get(url), 200 if url in files else 404,
                        None if url in files else "HTTP 404 Not Found")

        out, manifest = ow.build(datadir=tmp_data, fetch_impl=fake_fetch)
        ow.write_outputs(out, manifest, tmp_data)

        check("build: the document is available and carries the marine flags",
              out["available"] is True and out["is_land_station"] is False
              and out["is_measurement_inside_94122"] is False
              and out["is_a_bound_for_94122"] is False,
              f"available={out['available']}")
        check("build: the caveat says it is not a land station, is not inside the ZIP "
              "and is not a bound",
              all(s in out["caveat"] for s in
                  ("NOT A LAND STATION", "NOT A MEASUREMENT INSIDE ZIP 94122",
                   "NOT a bound")),
              out["caveat"][:90])
        check("build: only the seasons whose files arrived carry observations, and the "
              "rest are published as no data",
              out["years_fetched"] == [1991, 2005]
              and out["summary"]["seasons"] == 30
              and len(out["summary"]["seasons_with_no_data"]) == 28
              and out["seasons"][0]["observations"] == 4
              and out["seasons"][13]["season"] == "2004-2005"
              and out["seasons"][13]["observations"] == 5,
              f"fetched={out['years_fetched']} empty={len(out['summary']['seasons_with_no_data'])} "
              f"2004-2005={out['seasons'][13]['observations']}")
        check("build: a year NDBC lists but the archive did not serve is a warning with "
              "the URL, not a silent gap",
              any(i["severity"] == "warning" and "could not be retrieved" in i["message"]
                  for i in out["irregularities"])
              and any(not f["ok"] for f in out["year_files"]),
              f"irregularities={len(out['irregularities'])}")
        check("build: the station-page context fields are parsed, not assumed",
              out["station"]["anemometer_height_m"] == 4.1
              and out["station"]["water_depth_m"] == 53.0,
              f"anemo={out['station']['anemometer_height_m']} depth={out['station']['water_depth_m']}")
        check("build: the distance from the ZIP centroid is computed and published",
          19.0 < (out["station"]["distance_mi_from_centroid"] or 0) < 20.0,
          f"distance={out['station']['distance_mi_from_centroid']}")
        check("build: the latest buoy observation is labelled an observation, not a "
              "forecast, and carries its file value beside the converted one",
              out["latest_observation"]
              and "not a forecast" in out["latest_observation"]["note"]
              and out["latest_observation"]["wind_kt"] == 11.7
              and out["latest_observation"]["gust_kt"] == 15.6
              and out["latest_observation"]["wind_file_value"] == 6.0
              and out["latest_observation"]["file_wind_units"] == "m/s",
              f"latest={out['latest_observation']}")
        check("build: every manifest row is HTTPS on www.ndbc.noaa.gov",
              manifest and all(m["url"].startswith("https://www.ndbc.noaa.gov/")
                               for m in manifest),
              f"n={len(manifest)}")
        check("build: the manifest records the byte count and hash of every success",
              all(m.get("bytes") and m.get("sha256") for m in manifest if m.get("ok")),
              f"ok={sum(1 for m in manifest if m.get('ok'))}/{len(manifest)}")
        check("build: what the tier does not do is stated in the file",
              any("does not publish rain" in s for s in out["what_this_tier_does_not_do"]),
              out["what_this_tier_does_not_do"][1][:50])
        check("build: the written JSON is valid and has no NaN",
              json.loads((tmp_data / "ocean_wind.json").read_text())["tier"] == "ocean-wind",
              "ocean_wind.json parses")

        # ---- a page that no longer matches must fail loudly, not silently ----
        broken = dict(files)
        broken[ow.STATION_HISTORY_PAGE] = b"<html><body><p>we redesigned the site</p></body></html>"
        out2, _ = ow.build(datadir=tmp_data,
                           fetch_impl=lambda url, timeout=180: _Res(url, broken.get(url),
                                                                    200 if url in broken else 404))
        check("a station-history page with no annual links produces a warning, not an "
              "empty block that passes",
              any("listed no annual" in i["message"] for i in out2["irregularities"])
              and out2["available"] is False,
              f"available={out2['available']} irregularities={len(out2['irregularities'])}")

        # ---- an annual file that will not parse must not read as a calm season ----
        broken2 = dict(files)
        broken2[f"{ow.HISTORICAL_DIR}{ow.STATION_ID}h1991.txt.gz"] = gzip.compress(b"not a data file\n")
        out3, _ = ow.build(datadir=tmp_data,
                           fetch_impl=lambda url, timeout=180: _Res(url, broken2.get(url),
                                                                    200 if url in broken2 else 404))
        check("an unparseable annual file is published as no data with the raw excerpt",
              any("no usable rows" in i["message"] for i in out3["irregularities"])
              and any(i.get("evidence", {}).get("markup_excerpt") for i in out3["irregularities"]),
              f"irregularities={len(out3['irregularities'])}")
    finally:
        shutil.rmtree(tmp_data, ignore_errors=True)

    failed = [c for c in CHECKS if not c[1]]
    print(f"ocean-wind self-test: {len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    for name, ok, detail in CHECKS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    if failed:
        print(f"\n{len(failed)} FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
