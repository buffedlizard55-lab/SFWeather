#!/usr/bin/env python3
"""Build the chronological feed of official products: ``data/feed.json``.

The site answers "what will the weather do".  This answers the other question a
careful reader asks: *"what has NOAA actually published, and when?"*  One
timeline, newest first, of every official product this project fetched or
quoted - NWS forecast issuances, NWS alerts, Area Forecast Discussions, CPC
outlook issue dates, archived observations, and the model-guidance tier (marked,
in the feed itself, as not official).

The feed is **derived, never authored**:

* every entry is assembled from a file already in ``data/``, which in turn comes
  from a recorded fetch.  No timestamp, title or link is written by hand here;
* every entry that cites an official URL is checked against the union of all
  provenance manifests (``lib_provenance.urls_with_evidence``).  A URL with no
  successful fetch behind it is published as ``provenance_verified: false`` **and**
  raises an irregularity, so a link can never appear on the site without the
  fetch that justifies it;
* model-guidance entries carry ``official: false`` and the tier's warning, so
  they cannot be mistaken for NWS products in the same list;
* a timestamp that will not parse is dropped with an irregularity rather than
  guessed at, and undated entries are listed separately instead of being given a
  made-up date.

Run: ``python3 pipeline/build_feed.py``       ``python3 pipeline/build_feed.py --selftest``
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib_provenance as provlib  # noqa: E402

SEASON_START = dt.date(2026, 10, 1)
SEASON_END = dt.date(2027, 1, 31)

WARNING = (
    "Everything in this feed is an official U.S. government product, listed with "
    "the timestamp the publisher put on it and a link back to the published item. "
    "Entries marked NOT OFFICIAL come from the model-guidance tier and are kept "
    "visibly separate."
)

#: Files this feed is assembled from.  Each is optional: a module that has not
#: run yet is reported, not invented around.
SOURCES = [
    ("nws.json", "National Weather Service"),
    ("cpc.json", "NOAA Climate Prediction Center"),
    ("forecast_history.json", "this project's archived NWS forecasts"),
    ("afd_history.json", "NWS Area Forecast Discussion"),
    ("model_guidance.json", "NMME model guidance (not an official forecast)"),
    ("ncei_archive_probe.json", "NCEI observation archive"),
    ("provenance.json", "recorded fetches"),
]

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}
CPC_ISSUED_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})")
CPC_ISSUED_LONG_RE = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})")


def log(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------- timestamps
def to_utc(value):
    """Parse a publisher timestamp into UTC.  Returns ``None`` if it will not parse."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def iso(parsed):
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ") if parsed else None


def month_number(name):
    """Month number from 'September', 'Sep' or 'Sept' (CPC uses all three)."""
    if not name:
        return None
    key = name.title().rstrip(".")
    if key in MONTHS:
        return MONTHS[key]
    if key == "Sept":
        return 9
    for full, num in MONTHS.items():
        if full.startswith(key) and len(key) >= 3:
            return num
    return None


def cpc_issued_to_utc(text):
    """CPC prints issue dates as '18 Sep 2026' or 'September 17, 2026' (no time).

    Only the date is published; the time is left off rather than set to midnight
    and implied to be an issuance time.
    """
    if not text:
        return None
    m = CPC_ISSUED_RE.search(text)
    if m:
        day, mon, year = int(m.group(1)), month_number(m.group(2)), int(m.group(3))
        if mon:
            try:
                return {"date": dt.date(year, mon, day).isoformat(), "time_known": False,
                        "verbatim": text.strip()}
            except ValueError:
                return None
    m = CPC_ISSUED_LONG_RE.search(text)
    if m:
        mon, day, year = month_number(m.group(1)), int(m.group(2)), int(m.group(3))
        if mon:
            try:
                return {"date": dt.date(year, mon, day).isoformat(), "time_known": False,
                        "verbatim": text.strip()}
            except ValueError:
                return None
    return None


# ------------------------------------------------------------------- entries
def entry(kind, title, ts=None, detail=None, url=None, sha256=None,
          source_file=None, official=True, warning=None, date_only=None,
          evidence_url=None, link_kind=None):
    """One feed item.

    ``url`` is the link a reader is given; ``evidence_url`` is the URL whose
    recorded fetch justifies the content of the item.  They differ for NWS's
    human-facing pages (``forecast.weather.gov/MapClick.php``), which this project
    links for convenience but never fetched - the numbers came from the API URL,
    and saying so is what keeps "every figure traces to a fetch" true instead of
    merely plausible.
    """
    out = {
        "kind": kind,
        "title": title,
        "official": bool(official),
        "timestamp_utc": iso(ts) if isinstance(ts, dt.datetime) else ts,
        "date_utc": (ts.astimezone(dt.timezone.utc).date().isoformat()
                     if isinstance(ts, dt.datetime) else (date_only or None)),
        "time_known": bool(isinstance(ts, dt.datetime)),
        "detail": detail,
        "url": url,
        "sha256": sha256,
        "source_file": source_file,
    }
    if evidence_url:
        out["evidence_url"] = evidence_url
    if link_kind:
        out["link_kind"] = link_kind
    if warning:
        out["warning"] = warning
    return out


def load(datadir, name):
    path = Path(datadir) / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001 - a corrupt file is reported, not fatal
        return "CORRUPT"


def build(datadir=Path("data")):
    datadir = Path(datadir)
    irregularities = []
    entries = []
    undated = []
    sources_used, sources_missing = [], []

    def note(severity, message, evidence=None):
        irregularities.append({"severity": severity, "area": "feed",
                               "message": message, "evidence": evidence or {}})

    data = {}
    for name, label in SOURCES:
        obj = load(datadir, name)
        if obj == "CORRUPT":
            note("error", f"{label}: data/{name} exists but is not valid JSON, so its "
                          f"entries are not in the feed.", {"file": f"data/{name}"})
            sources_missing.append(name)
            continue
        if obj is None:
            sources_missing.append(name)
            continue
        data[name] = obj
        sources_used.append(name)
    if sources_missing:
        note("info", "Some datasets were not present when the feed was built, so the "
                     "feed covers fewer sources than a complete run would. Nothing was "
                     "invented to fill the gap.",
             {"missing": [f"data/{m}" for m in sources_missing]})

    # ---- NWS: forecast issuances, periods, alerts, AFD --------------------
    nws = data.get("nws.json") or {}
    if nws:
        daily = nws.get("forecast_daily") or {}
        upd = to_utc(daily.get("updated")) or to_utc(daily.get("generated_at"))
        periods = daily.get("periods") or []
        first = to_utc(periods[0].get("start_time")) if periods else None
        last = to_utc(periods[-1].get("end_time")) if periods else None
        entries.append(entry(
            "nws-forecast", "NWS official 7-day forecast (issued)", ts=upd,
            detail=(f"{len(periods)} forecast periods covering "
                    f"{first.date().isoformat() if first else '?'} to "
                    f"{last.date().isoformat() if last else '?'} (local time)."),
            url=daily.get("source_url"), source_file="data/nws.json"))
        if daily.get("human_url"):
            entries.append(entry(
                "nws-forecast", "NWS forecast page for this location", ts=upd,
                detail=daily.get("valid_times"), url=daily["human_url"],
                source_file="data/nws.json", evidence_url=daily.get("source_url"),
                link_kind="human-page"))
        for per in periods[:14]:
            ts = to_utc(per.get("start_time"))
            if not ts:
                note("warning", "An NWS forecast period carried no parseable start time, "
                                "so it is not listed in the feed.",
                     {"period": per.get("name"), "start_time": per.get("start_time")})
                continue
            pop = per.get("pop_pct")
            entries.append(entry(
                "nws-period",
                f"{per.get('name')}: {per.get('short_forecast')}", ts=ts,
                detail=(f"high {per.get('temperature_f')}\u00b0F; wind {per.get('wind_direction')} "
                        f"{per.get('wind_speed')}; chance of precipitation "
                        f"{'not given' if pop is None else str(pop) + '%'}"),
                url=daily.get("human_url"), source_file="data/nws.json",
                evidence_url=daily.get("source_url"), link_kind="human-page"))
        hourly = nws.get("forecast_hourly") or {}
        hp = hourly.get("periods") or []
        if hp:
            hfirst, hlast = to_utc(hp[0].get("start_time")), to_utc(hp[-1].get("end_time"))
            entries.append(entry(
                "nws-hourly", "NWS official hourly forecast (issued)",
                ts=to_utc(hourly.get("updated")) or hfirst,
                detail=f"{len(hp)} hourly steps, {iso(hfirst)} to {iso(hlast)} UTC.",
                url=hourly.get("source_url"), source_file="data/nws.json"))
        alerts = nws.get("active_alerts") or {}
        events = alerts.get("events") or []
        entries.append(entry(
            "nws-alerts",
            f"NWS active alerts for this zone: {alerts.get('count', 0)}",
            ts=to_utc(alerts.get("updated")),
            detail=("No active alerts." if not events else
                    "; ".join(sorted({e.get("event") or "?" for e in events if isinstance(e, dict)}))),
            url=alerts.get("human_url") or alerts.get("source_url"),
            source_file="data/nws.json", evidence_url=alerts.get("source_url"),
            link_kind="human-page"))
        for ev in events[:10]:
            if not isinstance(ev, dict):
                continue
            on = to_utc(ev.get("onset")) or to_utc(ev.get("sent"))
            (entries if on else undated).append(entry(
                "nws-alert", f"NWS alert: {ev.get('event')}", ts=on,
                detail=f"severity {ev.get('severity')}; certainty {ev.get('certainty')}; "
                       f"expires {ev.get('expires')}",
                url=ev.get("@id") or alerts.get("source_url"),
                source_file="data/nws.json",
                evidence_url=alerts.get("source_url"), link_kind="api-object-id"))
        afd = ((nws.get("products") or {}).get("AFD") or {})
        if afd.get("issuance_time"):
            ts = to_utc(afd["issuance_time"])
            entries.append(entry(
                "afd", "NWS Area Forecast Discussion (latest issuance)", ts=ts,
                detail=f"{afd.get('wmo_collective_id')} {afd.get('product_name')} - "
                       f"forecasters' prose; not a numeric forecast.",
                url=afd.get("url") or f"https://api.weather.gov/products/{afd.get('id')}",
                source_file="data/nws.json"))

    # ---- CPC: outlook issue dates and archived products -------------------
    cpc = data.get("cpc.json") or {}
    if cpc:
        for key, per in (cpc.get("valid_periods") or {}).items():
            if not isinstance(per, dict):
                continue
            issued = cpc_issued_to_utc(per.get("issued"))
            title = f"CPC {key} outlook issued"
            detail = (f"valid {per.get('valid') or '(period not stated on the page)'}"
                      + (f"; issued {issued['verbatim']}" if issued else ""))
            item = entry("cpc-outlook", title,
                         ts=None, date_only=(issued or {}).get("date"),
                         detail=detail, url=per.get("url"), source_file="data/cpc.json")
            if issued:
                item["time_known"] = False
                item["issued_verbatim"] = issued["verbatim"]
                entries.append(item)
            else:
                if per.get("issued"):
                    note("warning", "A CPC outlook issue date could not be parsed from "
                                    "NOAA's own text, so no date is asserted for it in the feed.",
                         {"product": key, "issued": per.get("issued")})
                undated.append(item)
        for sf in (cpc.get("shapefiles") or []):
            if not isinstance(sf, dict) or not sf.get("ok"):
                continue
            entries.append(entry(
                "cpc-shapefile", f"CPC {sf.get('label')} (shapefile archive)",
                ts=to_utc(sf.get("retrieved_utc")),
                detail=f"{sf.get('n_shapefiles')} file(s); sampled polygons: "
                       f"{sf.get('n_sampled_ok')}",
                url=sf.get("url"), sha256=sf.get("sha256"), source_file="data/cpc.json"))
        for mp in (cpc.get("maps") or []):
            if not isinstance(mp, dict) or not mp.get("ok"):
                continue
            entries.append(entry(
                "cpc-map", f"CPC {mp.get('label')} map (archived image)",
                ts=to_utc(mp.get("retrieved_utc")),
                detail=f"local copy: {mp.get('local_path')}",
                url=mp.get("url"), sha256=mp.get("sha256"), source_file="data/cpc.json"))
        for disc in (cpc.get("discussions") or []):
            if not isinstance(disc, dict) or not disc.get("ok"):
                continue
            entries.append(entry(
                "cpc-discussion", f"CPC {disc.get('label')} (prognostic discussion)",
                ts=to_utc(disc.get("retrieved_utc")),
                detail=f"{disc.get('characters')} characters of NOAA's own text",
                url=disc.get("url"), sha256=disc.get("sha256"),
                source_file="data/cpc.json"))

    # ---- this project's archived forecast snapshots -----------------------
    hist = data.get("forecast_history.json")
    if isinstance(hist, list):
        for snap in hist:
            if not isinstance(snap, dict):
                continue
            ts = to_utc(snap.get("generated_utc")) or to_utc(snap.get("forecast_updated"))
            days = snap.get("days") or []
            item = entry(
                "forecast-snapshot",
                f"Archived NWS forecast snapshot ({snap.get('issuance_date')})", ts=ts,
                detail=(f"{len(days)} days captured, "
                        f"{days[0].get('target_date') if days else '?'} to "
                        f"{days[-1].get('target_date') if days else '?'}; kept so each "
                        f"day's forecast can be scored against what actually happened."),
                url=None, source_file="data/forecast_history.json")
            item["official"] = True
            item["publisher"] = "this project (copy of an NWS forecast, unaltered)"
            (entries if ts else undated).append(item)

    # ---- AFD history quotes ------------------------------------------------
    afdh = data.get("afd_history.json") or {}
    if afdh:
        for prod in (afdh.get("products") or []):
            if not isinstance(prod, dict):
                continue
            for q in (prod.get("quotes") or []):
                ts = to_utc(prod.get("issuance_utc"))
                item = entry(
                    "afd-quote", "NWS discussion quote (verbatim)", ts=ts,
                    detail=q.get("text"), url=prod.get("url"),
                    source_file="data/afd_history.json")
                item["keywords"] = q.get("keywords")
                item["verbatim"] = True
                (entries if ts else undated).append(item)

    # ---- NCEI archive probe -----------------------------------------------
    probe = data.get("ncei_archive_probe.json") or {}
    if probe:
        ts = to_utc(probe.get("generated_utc"))
        entries.append(entry(
            "ncei-archive", "NCEI observation-archive staleness probe", ts=ts,
            detail=(f"verdict: {probe.get('verdict')}; GSOD/ISD last published "
                    f"{probe.get('gsod_last_date') or probe.get('subject_last_date') or '?'}"),
            url=probe.get("subject_url") or "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/",
            source_file="data/ncei_archive_probe.json"))

    # ---- model guidance (never marked official) ---------------------------
    mg = data.get("model_guidance.json") or {}
    if mg:
        warn = mg.get("warning") or "Model guidance - not an official forecast."
        ts = to_utc(mg.get("generated_utc"))
        entries.append(entry(
            "model-guidance",
            f"NMME model guidance retrieved (coverage: {mg.get('coverage_verbatim') or 'not stated'})",
            ts=ts, detail=warn, url=(mg.get("pages") or {}).get("prob_index", {}).get("url"),
            source_file="data/model_guidance.json", official=False, warning=warn))
        for img in (mg.get("images") or [])[:10]:
            if not isinstance(img, dict):
                continue
            (entries if img.get("retrieved_utc") else undated).append(entry(
                "model-guidance-image",
                f"NMME {img.get('variable')} map, season {img.get('season_index')} (archived image)",
                ts=to_utc(img.get("retrieved_utc")),
                detail=f"local copy: {img.get('local_path')}",
                url=img.get("url"), sha256=img.get("sha256"),
                source_file="data/model_guidance.json", official=False,
                warning=img.get("warning") or warn))

    # ---- every successful recorded fetch, newest first ---------------------
    fetch_entries = []
    for rec in provlib.load_entries(datadir):
        if not rec.get("ok"):
            continue
        ts = to_utc(rec.get("retrieved_utc"))
        item = entry("official-fetch", (rec.get("note") or rec["url"])[:150], ts=ts,
                     detail=f"HTTP {rec.get('http_status')}; {rec.get('bytes'):,} bytes"
                            if isinstance(rec.get("bytes"), int) else None,
                     url=rec["url"], sha256=rec.get("sha256"),
                     source_file=f"data/{rec.get('manifest', 'provenance.json')}")
        item["manifest"] = rec.get("manifest")
        (fetch_entries if ts else undated).append(item)
    entries.extend(fetch_entries)

    # ---- integrity: every cited URL must have a recorded fetch -------------
    evidenced = provlib.urls_with_evidence(datadir)
    no_evidence, convenience_links = [], []
    for item in entries + undated:
        url = item.get("url")
        evidence = item.get("evidence_url") or url
        if not url or str(url).startswith(("assets/", "data/")):
            # a local artefact (an archived image, a snapshot): nothing external to
            # verify, and the fetch that produced it is recorded separately
            item["provenance_verified"] = None
            item["link_verified"] = None
            continue
        item["link_verified"] = url in evidenced
        item["provenance_verified"] = evidence in evidenced
        if not item["provenance_verified"]:
            no_evidence.append(item)
            item["provenance_note"] = (
                "No recorded fetch stands behind this entry, so it is evidence for "
                "nothing: it is published as a pointer for manual review only.")
        elif url != evidence:
            convenience_links.append(item)
            item["provenance_note"] = (
                "The link given here is the publisher's human-facing page. The content "
                "of this entry comes from the recorded fetch of the machine-readable "
                "product named in evidence_url.")
    if no_evidence:
        note("warning",
             f"{len(no_evidence)} feed entries cite a URL with no successful fetch in any "
             f"provenance manifest. They are marked provenance_verified=false rather than "
             f"dropped, so a reader can still follow them, but no figure on the site may "
             f"depend on them.",
             {"urls": sorted({u["url"] for u in no_evidence})[:20]})
    if convenience_links:
        note("info",
             f"{len(convenience_links)} feed entries link a publisher's human-facing page "
             f"that was not itself fetched (the underlying product was). Each is labelled "
             f"link_kind=human-page or api-object-id and verified through its evidence_url.",
             {"distinct_links": sorted({u["url"] for u in convenience_links})[:10]})

    official_model = [i for i in entries + undated
                      if i.get("kind", "").startswith("model-guidance") and i.get("official")]
    if official_model:
        note("error", "A model-guidance entry was marked official, which would present raw "
                      "model output as an NWS forecast.",
             {"n": len(official_model)})

    entries.sort(key=lambda e: (e.get("timestamp_utc") or "", e.get("kind") or ""),
                 reverse=True)
    by_date = {}
    for item in entries:
        if item.get("date_utc"):
            by_date.setdefault(item["date_utc"], []).append(item["kind"])
    in_season = [i for i in entries
                 if i.get("date_utc") and SEASON_START.isoformat() <= i["date_utc"] <= SEASON_END.isoformat()]

    out = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "warning": WARNING,
        "season": {"start": SEASON_START.isoformat(), "end": SEASON_END.isoformat()},
        "sources_used": [f"data/{s}" for s in sources_used],
        "sources_missing": [f"data/{s}" for s in sources_missing],
        "counts": {
            "entries": len(entries),
            "undated_entries": len(undated),
            "kinds": {k: sum(1 for i in entries if i["kind"] == k)
                      for k in sorted({i["kind"] for i in entries})},
            "official": sum(1 for i in entries if i.get("official")),
            "not_official": sum(1 for i in entries if not i.get("official")),
            "provenance_verified": sum(1 for i in entries if i.get("provenance_verified") is True),
            "provenance_unverified": sum(1 for i in entries if i.get("provenance_verified") is False),
            "links_that_are_convenience_pages": len(convenience_links),
            "distinct_dates": len(by_date),
            "entries_inside_season_window": len(in_season),
        },
        # date-only entries (a CPC issue date, for example) carry no clock time,
        # so the window is computed from the entries that do have one
        "earliest_utc": min([e["timestamp_utc"] for e in entries if e.get("timestamp_utc")],
                            default=None),
        "latest_utc": max([e["timestamp_utc"] for e in entries if e.get("timestamp_utc")],
                          default=None),
        "entries": entries,
        "undated_entries": undated,
        "irregularities": irregularities,
    }
    return out


def write_outputs(out, datadir=Path("data")):
    datadir = Path(datadir)
    datadir.mkdir(parents=True, exist_ok=True)
    (datadir / "feed.json").write_text(json.dumps(out, indent=2) + "\n")
    provlib.merge_irregularities(datadir, "feed", out["irregularities"])
    return datadir / "feed.json"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datadir", default="data")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        import selftest_build_feed
        return selftest_build_feed.run()

    out = build(Path(args.datadir))
    path = write_outputs(out, Path(args.outdir or args.datadir))
    c = out["counts"]
    log(f"feed: {c['entries']} entries across {c['distinct_dates']} dates "
        f"({c['official']} official, {c['not_official']} model guidance, "
        f"{c['provenance_unverified']} links without a recorded fetch)")
    log(f"  window {out['earliest_utc']} -> {out['latest_utc']}")
    log(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
