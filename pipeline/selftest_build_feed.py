#!/usr/bin/env python3
"""Offline self-test for the official-product feed.

The feed's risks are quiet ones: a timestamp invented where a publisher only gave
a date, a link published with no recorded fetch behind it, model guidance sitting
in the same list marked as official, and a missing dataset being papered over.
Each is asserted here against a synthetic ``data/`` directory.

Writes only into temporary directories; touches no network.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_feed as bf  # noqa: E402

CHECKS = []

NWS_URL = "https://api.weather.gov/gridpoints/MTR/82,105/forecast"
SHP_URL = "https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/610temp_latest.zip"
DISC_URL = "https://www.cpc.ncep.noaa.gov/products/predictions/610day/fxus06.html"
UNFETCHED = "https://api.weather.gov/alerts/0e6f5d2c-0000-0000-0000-000000000000"
ALERTS_URL = "https://api.weather.gov/alerts/active?zone=CAZ006"
MG_INDEX_URL = "https://www.cpc.ncep.noaa.gov/products/NMME/probindex.shtml"
MG_IMAGE_URL = ("https://www.cpc.ncep.noaa.gov/products/NMME/prob/images/"
                "prob_ensemble_prate_us_season1.png")
NCEI_URL = ("https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/"
            "2025/72494023234.csv")
MAP_URL = "https://www.cpc.ncep.noaa.gov/products/predictions/610day/610temp.new.gif"
HOURLY_URL = NWS_URL + "/hourly"
AFD_PRODUCT_URL = "https://api.weather.gov/products/2f89"
AFD_HIST_URL = "https://api.weather.gov/products/aaa"
CPC_INDEX_URLS = [f"https://www.cpc.ncep.noaa.gov/products/predictions/{k}/"
                  for k in ("610day", "30day", "90day", "longlead")]

#: deliberately absent from the manifest: the "no evidence" case
ORPHAN_URL = "https://www.weather.gov/some-page-this-project-never-fetched"

#: every URL the fixture data cites as having been fetched, as the real manifests do
FETCHED = [NWS_URL, HOURLY_URL, SHP_URL, DISC_URL, ALERTS_URL, MG_INDEX_URL,
           MG_IMAGE_URL, NCEI_URL, MAP_URL, AFD_PRODUCT_URL, AFD_HIST_URL,
           *CPC_INDEX_URLS]


def manifest_entry(url, note="test fetch", status=200, ok=True, bytes_=1234,
                   sha="a" * 64, when="2026-09-18T20:40:00Z"):
    return {"url": url, "http_status": status, "ok": ok, "bytes": bytes_ if ok else 0,
            "sha256": sha if ok else None, "content_type": "application/octet-stream",
            "retrieved_utc": when if ok else None, "elapsed_s": 0.1, "note": note}


def fixture(datadir: Path):
    (datadir / "provenance.json").write_text(json.dumps({
        "generated_utc": "2026-09-18T20:42:23Z",
        "note": "test",
        "entries": [manifest_entry(u, f"recorded fetch of {u.split('/')[-1] or u}")
                    for u in FETCHED]}))
    (datadir / "nws.json").write_text(json.dumps({
        "forecast_daily": {
            "updated": "2026-09-18T18:27:04+00:00",
            "generated_at": "2026-09-18T18:27:04+00:00",
            "valid_times": "2026-09-18T12:00:00+00:00/2026-09-25T18:00:00+00:00",
            "source_url": NWS_URL,
            "human_url": "https://forecast.weather.gov/MapClick.php?lat=37.760459&lon=-122.483894",
            "periods": [
                {"number": 1, "name": "This Afternoon", "short_forecast": "Mostly Sunny",
                 "start_time": "2026-09-18T12:00:00-07:00",
                 "end_time": "2026-09-18T18:00:00-07:00",
                 "temperature_f": 65, "wind_direction": "W", "wind_speed": "9 to 15 mph",
                 "pop_pct": 0},
                {"number": 2, "name": "Tonight", "short_forecast": "Partly Cloudy",
                 "start_time": "2026-09-18T18:00:00-07:00",
                 "end_time": "2026-09-19T06:00:00-07:00",
                 "temperature_f": 58, "wind_direction": "WSW", "wind_speed": "5 to 9 mph",
                 "pop_pct": None},
                {"number": 3, "name": "Thursday", "short_forecast": "Chance Rain",
                 "start_time": "2026-10-02T06:00:00-07:00",
                 "end_time": "2026-10-02T18:00:00-07:00",
                 "temperature_f": 62, "wind_direction": "SW", "wind_speed": "15 to 25 mph",
                 "pop_pct": 60},
                {"number": 4, "name": "Broken", "short_forecast": "?",
                 "start_time": "not-a-timestamp", "end_time": None,
                 "temperature_f": None, "pop_pct": None},
            ]},
        "forecast_hourly": {
            "updated": "2026-09-18T18:27:04+00:00", "source_url": NWS_URL.replace("/forecast", "/forecast/hourly"),
            "periods": [{"start_time": "2026-09-18T12:00:00-07:00",
                         "end_time": "2026-09-18T13:00:00-07:00"}]},
        "active_alerts": {"zone": "CAZ006", "count": 1, "updated": "2026-09-18T20:00:00Z",
                          "source_url": ALERTS_URL,
                          "human_url": "https://forecast.weather.gov/product.php?site=NWS&issuedby=MTR",
                          "events": [{"event": "Wind Advisory", "severity": "Moderate",
                                      "certainty": "Likely", "onset": "2026-09-19T03:00:00-07:00",
                                      "expires": "2026-09-19T18:00:00-07:00", "@id": UNFETCHED}]},
        "products": {"AFD": {"id": "2f89", "issuance_time": "2026-09-18T18:24:00+00:00",
                             "product_name": "Area Forecast Discussion",
                             "wmo_collective_id": "FXUS66",
                             "url": AFD_PRODUCT_URL}},
    }))
    (datadir / "cpc.json").write_text(json.dumps({
        "valid_periods": {
            "610day": {"valid": "September 24 to 28, 2026", "issued": "18 Sep 2026",
                       "url": CPC_INDEX_URLS[0]},
            "30day": {"valid": None, "issued": "September 17, 2026",
                      "url": CPC_INDEX_URLS[1]},
            "90day": {"valid": None, "issued": None,
                      "url": CPC_INDEX_URLS[2]},
            "broken": {"valid": None, "issued": "Sometime soon",
                       "url": CPC_INDEX_URLS[3]},
        },
        "shapefiles": [{"label": "6-10 Day Temperature Outlook", "ok": True, "url": SHP_URL,
                        "sha256": "b" * 64, "n_shapefiles": 1, "n_sampled_ok": 1,
                        "retrieved_utc": "2026-09-18T20:40:41Z"}],
        "maps": [{"label": "6-10 Day Temperature", "ok": True, "url": MAP_URL,
                  "sha256": "c" * 64, "retrieved_utc": "2026-09-18T20:40:42Z",
                  "local_path": "assets/cpc/610day_temp.gif"}],
        "discussions": [{"label": "6-10 & 8-14 Day Prognostic Discussion", "ok": True,
                         "url": DISC_URL, "sha256": "d" * 64, "characters": 14339,
                         "retrieved_utc": "2026-09-18T20:40:45Z"}],
    }))
    (datadir / "forecast_history.json").write_text(json.dumps([
        {"issuance_date": "2026-09-18", "generated_utc": "2026-09-18T19:55:15+00:00",
         "forecast_updated": "2026-09-18T18:27:04+00:00",
         "days": [{"target_date": "2026-09-18", "high_f": 64},
                  {"target_date": "2026-09-19", "high_f": 65}]}]))
    (datadir / "afd_history.json").write_text(json.dumps({
        "warning": "prose", "products": [
            {"id": "aaa", "issuance_utc": "2026-09-18T10:23:00+00:00",
             "url": AFD_HIST_URL,
             "quotes": [{"text": "A weak front will bring periods of rain Thursday night into Friday.",
                         "keywords": ["rain", "storm"]}]}]}))
    (datadir / "model_guidance.json").write_text(json.dumps({
        "warning": "MODEL GUIDANCE - NOT AN OFFICIAL FORECAST.",
        "coverage_verbatim": "October 2026 - April 2027",
        "generated_utc": "2026-09-18T21:00:00Z",
        "pages": {"prob_index": {"url": MG_INDEX_URL, "ok": True}},
        "images": [{"variable": "precipitation rate", "season_index": 1,
                    "url": MG_IMAGE_URL,
                    "local_path": "assets/model_guidance/nmme_prate_us_season1.png",
                    "sha256": "e" * 64, "retrieved_utc": "2026-09-18T21:00:05Z",
                    "warning": "Model guidance, not an official forecast."}]}))
    (datadir / "ncei_archive_probe.json").write_text(json.dumps({
        "generated_utc": "2026-09-18T21:10:00Z", "verdict": "archive-wide-lag",
        "gsod_last_date": "2025-08-27", "subject_url": ORPHAN_URL,
        "gsod_urls": [NCEI_URL]}))
    (datadir / "quality_report.json").write_text(json.dumps(
        {"generated_utc": "2026-09-18T20:42:23Z", "counts": {}, "irregularities": [
            {"severity": "info", "area": "nws", "message": "kept"}]}))


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))


def by_kind(out, kind):
    return [e for e in out["entries"] if e["kind"] == kind]


def run():
    CHECKS.clear()
    tmp = Path(tempfile.mkdtemp(prefix="feed_"))
    fixture(tmp)
    out = bf.build(tmp)
    entries, undated = out["entries"], out["undated_entries"]

    # ---- shape and ordering ----------------------------------------------
    check("the feed was built from the datasets present",
          out["counts"]["entries"] == len(entries) > 20
          and "data/nws.json" in out["sources_used"],
          f"n={out['counts']['entries']} used={out['sources_used']}")
    stamps = [e["timestamp_utc"] for e in entries if e.get("timestamp_utc")]
    check("entries are sorted newest first", stamps == sorted(stamps, reverse=True),
          f"first={stamps[:3]}")
    check("every dated entry carries a date and says its time is known",
          all(e["date_utc"] and e["time_known"] for e in entries if e.get("timestamp_utc")),
          "date_utc/time_known")
    check("an unparseable publisher timestamp is dropped and flagged, not guessed",
          not any(e.get("title", "").startswith("Broken") for e in entries + undated)
          and any(i["severity"] == "warning" and "no parseable start time" in i["message"]
                  for i in out["irregularities"]),
          f"irregularities={[i['message'][:50] for i in out['irregularities']]}")

    # ---- NWS ---------------------------------------------------------------
    check("the NWS forecast issuance is listed with the API's own timestamp",
          any(e["kind"] == "nws-forecast" and e["timestamp_utc"] == "2026-09-18T18:27:04Z"
              for e in entries),
          f"{[e['timestamp_utc'] for e in by_kind(out, 'nws-forecast')]}")
    check("a forecast period's local start time is converted to UTC, not relabelled",
          any(e["title"].startswith("This Afternoon") and e["timestamp_utc"] == "2026-09-18T19:00:00Z"
              for e in entries),
          f"{[ (e['title'], e['timestamp_utc']) for e in by_kind(out, 'nws-period')]}")
    check("a period with no chance-of-precipitation value says so instead of printing 0",
          any("not given" in (e.get("detail") or "") for e in by_kind(out, "nws-period")),
          f"details={[e.get('detail') for e in by_kind(out, 'nws-period')]}")
    check("the active alert is listed with its onset time and severity",
          any(e["kind"] == "nws-alert" and e["timestamp_utc"] == "2026-09-19T10:00:00Z"
              and "Moderate" in (e.get("detail") or "") for e in entries),
          f"{by_kind(out, 'nws-alert')}")

    # ---- CPC issue dates ----------------------------------------------------
    c610 = [e for e in entries if e["kind"] == "cpc-outlook" and "610day" in e["title"]]
    check("a CPC issue date printed as '18 Sep 2026' becomes a date, with no invented time",
          c610 and c610[0]["date_utc"] == "2026-09-18" and c610[0]["time_known"] is False
          and c610[0]["timestamp_utc"] is None,
          f"{c610}")
    check("the publisher's own date text is kept alongside the parsed date",
          c610 and c610[0].get("issued_verbatim") == "18 Sep 2026", f"{c610}")
    check("a three-letter month abbreviation in a CPC issue date is parsed",
          bf.cpc_issued_to_utc("18 Sep 2026")["date"] == "2026-09-18"
          and bf.cpc_issued_to_utc("03 Sept 2026")["date"] == "2026-09-03"
          and bf.month_number("Sep.") == 9 and bf.month_number("sept") == 9
          and bf.month_number("December") == 12,
          f"{bf.cpc_issued_to_utc('18 Sep 2026')}")
    check("an impossible or unknown month is not turned into a date",
          bf.cpc_issued_to_utc("32 Sep 2026") is None
          and bf.cpc_issued_to_utc("18 Blorp 2026") is None
          and bf.month_number("Blorp") is None and bf.month_number("") is None,
          "rejects bad input")
    check("the long-form 'September 17, 2026' is parsed too",
          any(e["kind"] == "cpc-outlook" and e.get("date_utc") == "2026-09-17" for e in entries),
          f"{[e.get('date_utc') for e in by_kind(out, 'cpc-outlook')]}")
    check("a CPC product with no issue date is listed undated, with no date asserted",
          any(e["kind"] == "cpc-outlook" and "90day" in e["title"]
              and e.get("date_utc") is None for e in undated),
          f"undated={[e['title'] for e in undated]}")
    check("an unparsable issue date raises a warning and asserts nothing",
          any(i["severity"] == "warning" and "issue date could not be parsed" in i["message"]
              for i in out["irregularities"])
          and not any(e.get("date_utc") for e in undated if "broken" in e["title"]),
          f"{[i['message'][:60] for i in out['irregularities']]}")
    check("archived CPC products carry their hash from the recorded fetch",
          all(e.get("sha256") for e in by_kind(out, "cpc-shapefile") + by_kind(out, "cpc-discussion")),
          f"{[(e['kind'], e.get('sha256')) for e in by_kind(out, 'cpc-shapefile')]}")

    # ---- provenance verification -------------------------------------------
    verified = {e["url"] for e in entries if e.get("provenance_verified") is True}
    check("URLs with a recorded successful fetch are marked verified",
          {NWS_URL, SHP_URL, DISC_URL, MG_INDEX_URL, MAP_URL} <= verified
          and ORPHAN_URL not in verified,
          f"{sorted(verified)[:4]}")
    check("provenance counts add up against the entries",
          out["counts"]["provenance_verified"] + out["counts"]["provenance_unverified"]
          + sum(1 for e in entries if e.get("provenance_verified") is None)
          == out["counts"]["entries"],
          f"counts={out['counts']}")
    check("a fetch entry is present for every successful manifest row",
          len(by_kind(out, "official-fetch")) == len(FETCHED),
          f"{len(by_kind(out, 'official-fetch'))} vs {len(FETCHED)}")
    check("a convenience link to the publisher's human page is verified through its evidence",
          all(e.get("link_kind") == "human-page" and e["provenance_verified"] is True
              and e["link_verified"] is False and e.get("evidence_url") == NWS_URL
              for e in by_kind(out, "nws-period")),
          f"{[(e.get('link_kind'), e.get('provenance_verified'), e.get('link_verified')) for e in by_kind(out, 'nws-period')][:2]}")
    check("an API object id cited inside a fetched product is not treated as its own evidence",
          any(e.get("url") == UNFETCHED and e.get("link_kind") == "api-object-id"
              and e["link_verified"] is False and e["provenance_verified"] is True
              and e.get("evidence_url") == ALERTS_URL for e in entries),
          f"{[e for e in entries if e.get('url') == UNFETCHED]}")
    check("an entry with no fetch behind it is marked unverified, not dropped or trusted",
          any(e.get("url") == ORPHAN_URL and e["provenance_verified"] is False
              and e.get("provenance_note") for e in entries)
          and any(i["severity"] == "warning" and "no successful fetch in any" in i["message"]
                  for i in out["irregularities"])
          and out["counts"]["provenance_unverified"] == 1,
          f"unverified={out['counts']['provenance_unverified']}")
    check("convenience links are counted separately from missing evidence",
          out["counts"]["links_that_are_convenience_pages"] == 6
          and any(i["severity"] == "info" and "human-facing page" in i["message"]
                  for i in out["irregularities"]),
          f"n={out['counts']['links_that_are_convenience_pages']}")

    # ---- model guidance stays separate -------------------------------------
    mg = [e for e in entries + undated if e["kind"].startswith("model-guidance")]
    check("model-guidance entries are marked not official and carry the tier warning",
          len(mg) >= 2 and all(e["official"] is False and "NOT AN OFFICIAL FORECAST" in e["warning"].upper()
                               for e in mg),
          f"{[(e['kind'], e['official']) for e in mg]}")
    check("the feed counts official and model-guidance entries separately",
          out["counts"]["official"] + out["counts"]["not_official"] == out["counts"]["entries"]
          and out["counts"]["not_official"] == len(mg),
          f"{out['counts']}")
    check("no model-guidance entry was marked official (would be an error)",
          not any(i["severity"] == "error" for i in out["irregularities"]),
          f"{out['irregularities']}")

    # ---- derived content ---------------------------------------------------
    check("an archived forecast snapshot says who archived it",
          any(e["kind"] == "forecast-snapshot" and "this project" in (e.get("publisher") or "")
              for e in entries),
          f"{by_kind(out, 'forecast-snapshot')}")
    check("an AFD quote is carried verbatim with its keywords",
          any(e["kind"] == "afd-quote" and e.get("verbatim") is True
              and e["detail"].startswith("A weak front") and e.get("keywords") == ["rain", "storm"]
              for e in entries),
          f"{by_kind(out, 'afd-quote')}")
    check("entries dated inside the Oct 2026 - Jan 2027 window are counted",
          out["counts"]["entries_inside_season_window"] >= 1
          and all(bf.SEASON_START.isoformat() <= e["date_utc"] <= bf.SEASON_END.isoformat()
                  for e in entries if e.get("date_utc") and
                  bf.SEASON_START.isoformat() <= e["date_utc"] <= bf.SEASON_END.isoformat()),
          f"n={out['counts']['entries_inside_season_window']}")
    check("the feed's own window is stated in the file",
          out["earliest_utc"] and out["latest_utc"] and out["season"]["start"] == "2026-10-01",
          f"{out['earliest_utc']} -> {out['latest_utc']}")

    # ---- robustness --------------------------------------------------------
    shutil.copy(tmp / "nws.json", tmp / "nws.json.bak")
    (tmp / "nws.json").write_text("{not json")
    out_bad = bf.build(tmp)
    check("a corrupt dataset is reported as an error and skipped, not fatal",
          any(i["severity"] == "error" and "not valid JSON" in i["message"]
              for i in out_bad["irregularities"])
          and "data/nws.json" in out_bad["sources_missing"]
          and out_bad["counts"]["entries"] > 0,
          f"{[i['message'][:50] for i in out_bad['irregularities']]}")
    (tmp / "nws.json.bak").rename(tmp / "nws.json")

    empty_dir = Path(tempfile.mkdtemp(prefix="feed_empty_"))
    out_empty = bf.build(empty_dir)
    check("an empty data directory yields an empty feed plus one explanatory note",
          out_empty["counts"]["entries"] == 0
          and any("not present when the feed was built" in i["message"]
                  for i in out_empty["irregularities"]),
          f"{out_empty['counts']}")
    shutil.rmtree(empty_dir, ignore_errors=True)

    # ---- outputs ------------------------------------------------------------
    path = bf.write_outputs(out, tmp)
    check("write_outputs wrote data/feed.json", path.exists(), str(path))
    rep = json.loads((tmp / "quality_report.json").read_text())
    check("feed irregularities merged into the quality report under a tag",
          any(i.get("source") == "feed" for i in rep["irregularities"])
          and any(i["message"] == "kept" for i in rep["irregularities"]),
          f"{rep['counts']}")
    bf.write_outputs(out, tmp)
    rep2 = json.loads((tmp / "quality_report.json").read_text())
    check("merging twice does not double-count",
          len([i for i in rep2["irregularities"] if i.get("source") == "feed"])
          == len([i for i in rep["irregularities"] if i.get("source") == "feed"]),
          f"{rep2['counts']}")
    check("the feed file does not carry a second provenance manifest of its own",
          not (tmp / "feed_provenance.json").exists()
          and all(e.get("sha256") in (None, "a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64)
                  for e in entries),
          "no network access in this module")

    shutil.rmtree(tmp, ignore_errors=True)
    failed = [c for c in CHECKS if not c[1]]
    for name, ok, detail in CHECKS:
        print(f"  [{'ok ' if ok else 'FAIL'}] {name}" + (f"  :: {detail}" if not ok else ""))
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} feed self-checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
