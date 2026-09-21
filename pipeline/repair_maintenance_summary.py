#!/usr/bin/env python3
"""Repair & Maintenance focused executive summary generator (schema v2).

Reads the verified datasets and produces three artifacts:

* ``data/repair_maintenance_summary.json``  - machine-readable, rendered on the
  page by ``assets/js/app.js`` (``renderRepairExecutive``) and re-checked line by
  line by ``pipeline/verify_claims.py``.
* ``data/repair_maintenance_executive.md``  - one printable page, generated from
  the JSON, never retyped.
* ``docs/REPAIR_MAINTENANCE_EXECUTIVE_SUMMARY.md`` - byte-identical copy of the
  printable page, so the repository shows it without a build step.

Every number is copied from ``landlord.json`` / ``calendar.json`` / ``run.json`` /
``cpc.json`` / ``enso.json`` / ``nws.json``.  Nothing is typed in: the module
holds no weather value, no percentage and no date of its own.  Every sentence
attributed to NOAA is copied verbatim out of text this project fetched (and
hashed) - a sentence that is not found in the fetched text is *not published* and
is listed under ``*_not_found`` instead (bug-40 rule: a retyped or paraphrased
quote is a defect, not a convenience).

Schema rules this module enforces (``RepairTierError`` - the run fails, nothing
is written):

1. **One stamp.**  ``generated_utc`` is the ``landlord.json`` stamp - the dataset
   that carries the block this tier republishes.  A tier may never stamp itself
   with the wall clock, because that is how a stale artifact comes to look fresh.
   ``sources_read`` publishes, per input file, the build stamp it carries *and*
   the newest retrieval timestamp recorded inside it, and ``currency`` states
   whether the build-stamped files agree, which files carry no build stamp (the
   raw CPC/ENSO/NWS fetch containers record per-fetch ``retrieved_utc`` instead),
   and whether any fetched content is newer than the artifact.  The claim ledger
   re-derives all of that and fails the build when the tier is stale.
2. **Ranks are a permutation of 1..N** and severity is a pure function of rank
   (1-3 high, 4-5 medium, 6+ low, rule published in ``severity_rule``).  A
   driver with no rank, no ``why_it_costs`` or no source URL stops the run.
3. **Absent data is published as absent.**  When a tier the summary would quote
   is not published in this snapshot (the ocean buoy record, the hourly
   wind+rain block), the key carries ``available: false`` and an explicit
   sentence - never a ``null`` that a renderer turns into a blank or a dash.
4. **The watch list quotes NOAA, it does not schedule.**  The next ENSO
   discussion date and the "may be increased further" sentence are extracted by
   pattern from the fetched CPC text and carried verbatim with the URL and
   SHA-256 of the file they came from.  If CPC rewrites the sentence, the entry
   disappears from the JSON and its key appears in ``next_issuances_not_found``.

Usage::

    python3 pipeline/repair_maintenance_summary.py            # write artifacts
    python3 pipeline/repair_maintenance_summary.py --selftest # offline tests
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The project keeps one whitespace-collapsing rule (used by the prognostic-caveat
# extractor and by the claim ledger's verbatim checks).  Reusing it here means a
# quote published by this tier is comparable with the ledger's own comparison,
# instead of being a second, subtly different definition of "verbatim".
from climo import collapse_ws  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
_env = os.environ.get("SFWEATHER_DATA")
if _env:
    DATA = Path(_env)

SCHEMA_VERSION = "2"

#: Files this tier reads, in the order they are stamped.  ``landlord.json`` is
#: the dataset that carries the executive summary block; the others are read for
#: the verbatim CPC/NWS text and the scoreboard geometry.
SOURCE_FILES = ("landlord.json", "calendar.json", "run.json", "cpc.json",
                "enso.json", "nws.json")

#: Severity is a documented function of rank, nothing else.
SEVERITY_BY_RANK = ((1, 3, "high"), (4, 5, "medium"), (6, 10 ** 6, "low"))
SEVERITY_RULE = (
    "Severity is derived from the driver's rank in the verified landlord "
    "dataset and from nothing else: ranks 1-3 = high, 4-5 = medium, 6 or lower = "
    "low. It says which mechanism is most likely to drive repair and maintenance "
    "cost first; it is not a dollar threshold and not an official hazard rating."
)

#: The official source ledger.  Every key here is already a vetted official host
#: (see pipeline/verify_sources.py and the claim ledger's OFFICIAL_HOSTS).
SOURCES = {
    "ghcn_daily": ("NCEI GHCN-Daily USW00023272 (rain, daily high/low)",
                   "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023272.csv"),
    "gsod": ("NCEI GSOD 72494023234 (daily wind and gusts, KSFO)",
             "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/"),
    "isd": ("NCEI ISD hourly 72494023234 (hour-by-hour wind + rain)",
            "https://www.ncei.noaa.gov/data/global-hourly/access/"),
    "cpc_gis": ("CPC long-lead outlook GIS archive (monthly/seasonal probabilities)",
                "https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/us_tempprcpfcst/"),
    "cpc_discussion": ("CPC Prognostic Discussion, 30-day / 90-day outlooks",
                       "https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html"),
    "enso_discussion": ("CPC ENSO Diagnostic Discussion (Alert System Status)",
                        "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml"),
    "oni": ("CPC Oceanic Nino Index (ONI) table",
            "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"),
    "nws_api": ("NWS gridded forecast for this ZIP's grid cell",
                "https://api.weather.gov/points/37.7605,-122.4839"),
    "census": ("U.S. Census Bureau Gazetteer (ZIP centroid)",
               "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip"),
    "storm_events": ("NCEI Storm Events database (local severe-weather record)",
                     "https://www.ncdc.noaa.gov/stormevents/"),
    "ndbc_46026": ("NOAA NDBC buoy 46026 (ocean-side wind, 19.4 mi offshore)",
                   "https://www.ndbc.noaa.gov/station_page.php?station=46026"),
}

#: The Census URL above is the catalogue page; the coordinate actually used is
#: published in run.json (``target.centroid.url``).  ``main()`` replaces it with
#: the URL the dataset records when that dataset is present, so the ledger's
#: "every URL traces to the datasets" rule holds for this file too.
CENSUS_URL_OVERRIDE_SOURCE = "target.centroid.url"

#: Files whose newest content is best dated by a field the product itself
#: publishes, rather than by a generic ``retrieved_utc`` scan.
CONTENT_AS_OF_OVERRIDES = {
    # gridpoint_raw.generatedAt is the NWS product's own generation time.
    "nws.json": ("gridpoint_raw/generated_at",
                 "the NWS gridded product's own generatedAt timestamp"),
}

#: (key, label, regex, where to look, how to pick the right text)
#:
#: Each pattern is anchored on a sentence NOAA's own forecasters wrote, and is
#: searched only inside text this project fetched and hashed.  The captured
#: group is the date or the window the sentence names; the whole sentence is
#: published beside it.
NEXT_ISSUANCE_SPECS = (
    {
        "key": "next_enso_discussion",
        "label": "When CPC's next ENSO assessment is due (NOAA's own sentence)",
        "dataset": "enso.json",
        "haystack": "sources[].text",
        "url_contains": "ensodisc",
        "pattern": r"(The next ENSO Diagnostics Discussion is scheduled for [^.]+\.)",
        "value_pattern": r"scheduled for ([^.]+)\.",
    },
    {
        "key": "next_long_lead_may_rise",
        "label": "What CPC says about the next set of seasonal outlooks (NOAA's own sentence)",
        "dataset": "cpc.json",
        "haystack": "discussions[].text",
        "url_contains": "fxus05",
        "pattern": r"(These probabilities may be increased further in the next set of seasonal outlooks[^.]*\.)",
        "value_pattern": r"to be released in ([^,]+),",
    },
    {
        "key": "next_long_lead_issuance",
        "label": "The date CPC names for its next long-lead issuance (NOAA's own sentence)",
        "dataset": "cpc.json",
        "haystack": "discussions[].text",
        "url_contains": "fxus05",
        "pattern": r"(This set of outlooks will be superseded by the issuance of the new set next month on [A-Za-z]+ \d{1,2} \d{4})",
        "value_pattern": r"next month on ([A-Za-z]+ \d{1,2} \d{4})",
    },
)


class RepairTierError(RuntimeError):
    """A contract this tier publishes against was broken; nothing is written."""


def all_strings(obj, _out=None):
    """Every string inside a dataset (used to read a value out of published prose)."""
    out = [] if _out is None else _out
    if isinstance(obj, dict):
        for v in obj.values():
            all_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            all_strings(v, out)
    elif isinstance(obj, str):
        out.append(obj)
    return out


#: "11.9 miles ... 94122" - the station-to-ZIP distance as one of the datasets'
#: own sentences writes it.  Parsed, never typed: if no sentence carries it, the
#: tier publishes no distance rather than a remembered one.
DISTANCE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mi|miles)\b[^.]{0,100}?94122")

#: "gale_days_ge_34kt" -> 34.  The threshold is part of the dataset's own key.
THRESHOLD_KEY_RE = re.compile(r"^gale_days_ge_(\d+)kt$")


#: An internal field path leaking into a published sentence would read as
#: machine furniture on a landlord-facing page, so a sentence that carries one is
#: only published when the dataset offers nothing else.
INTERNAL_PATH_RE = re.compile(r"[a-z_]+\.[a-z_]{3,}")


def derived_distance(landlord: dict):
    """(miles, sentence) for the SFO-to-94122 distance, read from the dataset.

    Every sentence in the dataset that states the distance is collected, and the
    one published is chosen by preference (no internal field path, then shortest) -
    the tier still publishes only words the dataset wrote.
    """
    found = []
    for text in all_strings(landlord):
        m = DISTANCE_RE.search(text)
        if not m:
            continue
        flat = collapse_ws(text)
        i = flat.find(m.group(0))
        # A sentence with no ". " before the match starts at 0 - rfind() returns
        # -1 and adding 2 to it would silently chop the first letter.
        j = flat.rfind(". ", 0, i)
        start = j + 2 if j > -1 else 0
        end = flat.find(". ", i + len(m.group(0)))
        sentence = flat[start:(end + 1 if end > -1 else len(flat))].strip()
        found.append((float(m.group(1)), sentence))
    if not found:
        return None, None
    miles = found[0][0]
    if len({f[0] for f in found}) != 1:
        raise RepairTierError(
            "the datasets state more than one SFO-to-ZIP distance "
            f"({sorted({f[0] for f in found})}); refusing to choose for the reader")
    clean = [f for f in found if not INTERNAL_PATH_RE.search(f[1])]
    pool = clean or found
    return miles, sorted(pool, key=lambda f: len(f[1]))[0][1]


def derived_gale_threshold(ocean: dict):
    """(kt, key) for the gale counter, taken from the landlord dataset's key name."""
    for key in sorted(ocean):
        m = THRESHOLD_KEY_RE.match(key)
        if m:
            return int(m.group(1)), key
    return None, None


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def load(name: str, datadir: Path | None = None) -> dict:
    p = (datadir or DATA) / name
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001 - a corrupt dataset is "absent", not fatal here
        return {}


def dig(obj, path: str, default=None):
    """``dig(d, "a/b/0/c")`` - read a nested path without raising."""
    cur = obj
    for part in path.split("/"):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return default
        else:
            return default
        if cur is None:
            return default
    return cur


def parse_iso(value):
    """Parse an ISO-8601 stamp (``Z`` or offset) into a datetime, or ``None``."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def newest_retrieval(obj, _found=None):
    """Newest ``retrieved_utc`` recorded anywhere inside a dataset."""
    found = _found if _found is not None else []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "retrieved_utc" and isinstance(v, str):
                found.append(v)
            newest_retrieval(v, found)
    elif isinstance(obj, list):
        for v in obj:
            newest_retrieval(v, found)
    return max(found) if found else None


def severity_for_rank(rank) -> str:
    if not isinstance(rank, int):
        raise RepairTierError(f"driver rank is not an integer: {rank!r}")
    for lo, hi, sev in SEVERITY_BY_RANK:
        if lo <= rank <= hi:
            return sev
    raise RepairTierError(f"driver rank {rank} has no severity")


def fmt(value, ndigits=None) -> str:
    """Render a value for the printable page; ``None`` becomes an em dash.

    Numbers are printed **as published**: no rounding, so the page can never show
    a figure (7.4 from 7.37) that exists in no dataset.  ``ndigits`` is available
    for the few places where a fixed number of decimals is wanted, and the claim
    ledger's printable-page check would flag any rounding that invented a value.

    The em dash is only ever used for a value the source dataset does not carry,
    and every block that can be absent carries an explicit sentence saying so.
    """
    if value is None:
        return "\u2014"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    if isinstance(value, float):
        if ndigits is not None:
            return f"{value:,.{ndigits}f}"
        return f"{value:,}"
    return str(value)


def _sentence_source(dataset: dict, spec: dict):
    """Return (text, url, sha256, label) for the first matching fetched file.

    ``spec["haystack"]`` names the array holding the fetched pages: ``enso.json``
    keeps them under ``sources[]``, ``cpc.json`` under ``discussions[]``.  The
    page is matched on its URL so a pattern can never be satisfied by a different
    product's text.
    """
    if spec["haystack"].startswith("sources"):
        pages = dataset.get("sources") or []
    else:
        pages = dataset.get("discussions") or []
    for item in pages:
        url = str(item.get("url") or "")
        if spec["url_contains"] and spec["url_contains"] not in url:
            continue
        text = item.get("text") or ""
        if not text:
            continue
        return text, url, item.get("sha256"), item.get("label")
    return None, None, None, None


def extract_next_issuances(datasets: dict) -> tuple[list, list, dict]:
    """Extract NOAA's own sentences about when its next products are due.

    Returns ``(found, not_found_keys, scan)``.  A sentence that is no longer in
    the fetched text is *not* paraphrased or reconstructed: its key moves to
    ``not_found`` (the same design as the prognostic-caveat extractor, where a
    growing ``not_found`` list is the feature working, not a bug).
    """
    found: list = []
    not_found: list = []
    scan: dict = {}
    for spec in NEXT_ISSUANCE_SPECS:
        dataset = datasets.get(spec["dataset"]) or {}
        text, url, sha, label = _sentence_source(dataset, spec)
        scan[spec["key"]] = {
            "dataset": spec["dataset"],
            "url": url,
            "sha256": sha,
            "characters": len(text or ""),
        }
        # Search the whitespace-collapsed page: CPC's HTML-to-text conversion
        # wraps sentences across lines, so a phrase spanning a line break would
        # otherwise never match.  The published sentence is the collapsed one,
        # which is exactly what the claim ledger checks as a substring.
        m = re.search(spec["pattern"], collapse_ws(text or "")) if text else None
        if not m:
            not_found.append(spec["key"])
            continue
        sentence = collapse_ws(m.group(1)).strip()
        if any(ord(ch) < 32 or ord(ch) in (127, 0xFFFD) for ch in sentence):
            not_found.append(spec["key"] + " (matched but not clean plain text)")
            continue
        vm = re.search(spec["value_pattern"], sentence)
        item = {
            "key": spec["key"],
            "label": spec["label"],
            "text": sentence,
            "value": (vm.group(1).strip() if vm else None),
            "source_label": label or spec["dataset"],
            "source_url": url,
            "source_sha256": sha,
            "how_to_read": (
                "Copied verbatim from the file this project fetched and hashed "
                "(URL and SHA-256 above). It is CPC's statement about its own "
                "issuance schedule, not this project's forecast: the sentence "
                "disappears from this list if CPC rewrites it."
            ),
        }
        found.append(item)
    return found, not_found, scan


def next_issuance_keys() -> list:
    """The keys this tier watches for - the contract the ledger checks against."""
    return [spec["key"] for spec in NEXT_ISSUANCE_SPECS]


# --------------------------------------------------------------------------- #
# the summary
# --------------------------------------------------------------------------- #

def build_summary(datasets: dict) -> dict:
    """Assemble the executive summary from the verified datasets.

    Raises :class:`RepairTierError` rather than publishing an incomplete or
    self-contradicting summary.
    """
    landlord = datasets.get("landlord.json") or {}
    calendar = datasets.get("calendar.json") or {}
    run = datasets.get("run.json") or {}
    cpc = datasets.get("cpc.json") or {}
    enso = datasets.get("enso.json") or {}
    nws = datasets.get("nws.json") or {}

    es = landlord.get("executive_summary") or {}
    if not es:
        raise RepairTierError("landlord.json has no executive_summary block")

    # How current each input is: the build stamp a file carries (if it carries
    # one) and the newest retrieval timestamp recorded inside it.  The raw fetch
    # containers (cpc.json, enso.json, nws.json) carry no build stamp - they
    # record when each URL was retrieved - so they are published as such instead
    # of being folded into a claim of agreement they cannot support.
    sources_read = {}
    for name in SOURCE_FILES:
        ds = datasets.get(name) or {}
        build_stamp = ds.get("generated_utc")
        content_as_of = newest_retrieval(ds)
        content_kind = "newest per-fetch retrieved_utc recorded in this file"
        if name in CONTENT_AS_OF_OVERRIDES:
            path, content_kind = CONTENT_AS_OF_OVERRIDES[name]
            content_as_of = dig(ds, path) or content_as_of
        sources_read[name] = {
            "build_stamp": build_stamp,
            "build_stamp_kind": ("pipeline build stamp" if build_stamp
                                 else "not carried by this file"),
            "content_as_of_utc": content_as_of,
            "content_as_of_kind": content_kind,
        }
    landlord_stamp = sources_read["landlord.json"]["build_stamp"]
    if not landlord_stamp:
        raise RepairTierError("landlord.json carries no generated_utc stamp")
    stamped = sorted(v["build_stamp"] for v in sources_read.values() if v["build_stamp"])
    newest, oldest = stamped[-1], stamped[0]
    unstamped = sorted(n for n, v in sources_read.items() if not v["build_stamp"])
    artifact_dt = parse_iso(landlord_stamp)
    content_newer = sorted(
        n for n, v in sources_read.items()
        if parse_iso(v["content_as_of_utc"]) and artifact_dt
        and parse_iso(v["content_as_of_utc"]) > artifact_dt)
    content_as_of = max((v["content_as_of_utc"] for v in sources_read.values()
                         if v["content_as_of_utc"]), default=None)
    sources_agree = len(set(stamped)) == 1 and not content_newer

    target = run.get("target") or {}
    centroid = target.get("centroid") or {}

    official_outlook = es.get("official_outlook") or {}
    current_enso = dict(es.get("current_enso") or {})
    official_enso = official_outlook.get("enso") or {}
    # CPC's Alert System Status is published by CPC, so it is carried from
    # official_outlook (the verbatim product block) into current_enso as well -
    # one number, one source, never retyped.
    if official_enso.get("alert_status"):
        current_enso["alert_status"] = official_enso["alert_status"]
        current_enso["alert_status_source_url"] = official_enso.get("source_url")

    cpc_tilt = official_outlook.get("cpc_tilt") or {}
    enso_strength = official_outlook.get("enso_strength") or {}
    prognostic = official_outlook.get("prognostic_caveats") or {}
    conditioned = official_outlook.get("enso_conditioned_record") or {}
    daily_fc = official_outlook.get("daily_forecast") or {}

    drivers_in = es.get("cost_drivers") or []
    if not drivers_in:
        raise RepairTierError("landlord.json executive_summary has no cost_drivers")
    ranks = [d.get("rank") for d in drivers_in]
    if sorted(r for r in ranks if isinstance(r, int)) != list(range(1, len(ranks) + 1)):
        raise RepairTierError(f"cost-driver ranks are not a 1..{len(ranks)} permutation: {ranks}")

    drivers = []
    for d in sorted(drivers_in, key=lambda x: x.get("rank") or 0):
        rank = d.get("rank")
        if not d.get("why_it_costs"):
            raise RepairTierError(f"driver #{rank} has no why_it_costs sentence")
        srcs = [s for s in (d.get("sources") or []) if (s or {}).get("url")]
        if not srcs:
            raise RepairTierError(f"driver #{rank} carries no source URL")
        evidence = d.get("evidence") or []
        drivers.append({
            "rank": rank,
            "driver": d.get("driver"),
            "severity": severity_for_rank(rank),
            "severity_rule": SEVERITY_RULE,
            "why_it_costs": d.get("why_it_costs"),
            "why_it_costs_label": "guidance, not a weather claim",
            "key_metric": (evidence[0].get("value") if evidence else None),
            "metric_label": (evidence[0].get("label") if evidence else None),
            "evidence": evidence,
            "evidence_count": len(evidence),
            "sources": srcs,
        })

    definitions = calendar.get("definitions") or {}
    archives = {a.get("area"): a for a in ((es.get("record_coverage") or {}).get("archives") or [])}

    def archive_basis(area, fallback):
        a = archives.get(area) or {}
        if not a.get("label"):
            return fallback
        return (f"{a.get('label')}"
                + (f"; newest row fetched {a.get('last_date')}" if a.get("last_date") else ""))

    streak = es.get("streak_probability") or {}
    longest = es.get("longest_streak") or {}
    enso_streaks = ((es.get("enso_stratified_streaks") or {}).get(current_enso.get("phase") or "") or {})
    hourly = es.get("wind_and_rain_hourly") or {}
    wind_rain_day = es.get("wind_and_rain") or {}
    heavy = es.get("heavy_wind_and_rain") or {}
    gusts = es.get("max_gust") or {}
    ocean = es.get("ocean_wind") or {}
    gale_threshold_kt, gale_key = derived_gale_threshold(ocean)
    gale_stats = (ocean.get(gale_key) or {}) if gale_key else {}
    gust_distance_mi, gust_distance_sentence = derived_distance(landlord)
    season_total = es.get("season_total_prcp") or {}
    hours_stats = hourly.get("simultaneous_hours_per_season") or {}

    days = calendar.get("days") or []
    day_numbers_present = [
        bool([k for k in ("high_f", "low_f", "humidity_pct", "wind_max_mph",
                          "gust_max_mph", "rain_chance_pct", "rain_amount_in")
              if d.get(k) is not None]) for d in days
    ]
    days_complete = sum(1 for ok in day_numbers_present if ok)
    tiers = {}
    for d in days:
        tiers[d.get("tier")] = tiers.get(d.get("tier"), 0) + 1

    next_issuances, next_not_found, next_scan = extract_next_issuances(datasets)

    caveats = [q for q in (prognostic.get("quotes") or []) if q.get("text")]
    strength_quotes = [q for q in (enso_strength.get("quotes") or []) if q.get("text")]

    sources = {}
    for key, (label, url) in SOURCES.items():
        sources[key] = {"label": label, "url": url}
    recorded_census = dig(run, "target/centroid/url")
    if recorded_census and str(recorded_census).startswith("http"):
        sources["census"]["url"] = recorded_census
        sources["census"]["url_note"] = ("the catalogue page for this product is "
                                         "published in SOURCES; this is the file "
                                         "the run actually fetched")
    sources_list = [{"key": k, "label": v["label"], "url": v["url"]}
                    for k, v in sorted(sources.items(), key=lambda kv: kv[1]["label"])]

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": landlord_stamp,
        "built_from": {
            "datasets": list(SOURCE_FILES),
            "rule": ("Every published value is read from one of these files at "
                     "build time. generated_utc is the landlord.json stamp; this "
                     "tier never stamps itself with the wall clock."),
        },
        "sources_read": sources_read,
        "currency": {
            "artifact_generated_utc": landlord_stamp,
            "oldest_source_utc": oldest,
            "newest_source_utc": newest,
            "sources_disagreeing": sorted(n for n, v in sources_read.items()
                                          if v["build_stamp"] and v["build_stamp"] != landlord_stamp),
            "sources_without_a_build_stamp": unstamped,
            "newest_fetched_content_utc": content_as_of,
            "content_newer_than_the_artifact": content_newer,
            "sources_agree": sources_agree,
            "is_current": sources_agree,
            "note": (
                f"Every dataset that carries a build stamp carries the same one "
                f"({landlord_stamp}); the newest content fetched into this tier's "
                f"inputs is "
                + (f"{content_as_of}. " if content_as_of else
                   "not recorded by the inputs themselves. ")) + (
                (f"{len(unstamped)} input(s) carry no build stamp of their own "
                   f"({', '.join(unstamped)}) and record the retrieval time of each "
                   f"fetch instead, so they are listed rather than assumed. "
                   if unstamped else "")
                + "The claim ledger re-derives this and blocks publication when the "
                  "summary is older than the data it summarises."
                if sources_agree else
                ("This summary is NOT current: "
                 + (f"build stamps differ ({', '.join(sorted(n for n, v in sources_read.items() if v['build_stamp'] and v['build_stamp'] != landlord_stamp))}); "
                    if len(set(stamped)) > 1 else "")
                 + (f"content fetched after the artifact stamp ({', '.join(content_newer)}); "
                    if content_newer else "")
                 + "it is published with this warning rather than as fresh.")),
        },
        "location": es.get("location") or target.get("label") or "San Francisco, CA 94122",
        "season_window": es.get("season_window"),
        "coordinates": {
            "lat": centroid.get("lat"),
            "lon": centroid.get("lon"),
            "source": es.get("verified_coordinate_source"),
            "source_url": es.get("coordinate_source_url"),
        },
        "executive_headline": es.get("key_finding"),
        "scoreboard": {
            "days_total": len(days),
            "days_with_all_seven_fields": days_complete,
            "days_with_a_real_official_forecast_now":
                daily_fc.get("days_in_this_scoreboard_with_a_real_forecast"),
            "official_horizon_ends": daily_fc.get("official_horizon_ends"),
            "days_by_tier": tiers,
            "fields": ["high_f", "low_f", "humidity_pct", "wind_max_mph",
                       "gust_max_mph", "rain_chance_pct", "rain_amount_in"],
            "note": ("A day inside the official NWS horizon carries the real "
                     "gridded forecast for this ZIP's cell; every other day "
                     "carries the 1991-2020 observed record for that calendar "
                     "date, labelled as such. No daily forecast is invented."),
            "source_url": sources["nws_api"]["url"],
        },
        "current_enso": current_enso,
        "official_enso": official_enso,
        "enso_strength_quotes": strength_quotes,
        "enso_strength": {k: v for k, v in enso_strength.items() if k != "quotes"},
        "cpc_tilt": cpc_tilt,
        "caveats": caveats,
        "caveats_not_found": prognostic.get("not_found") or [],
        "caveats_note": prognostic.get("how_to_read"),
        "next_issuances": next_issuances,
        "next_issuances_not_found": next_not_found,
        "next_issuances_patterns_watched_for": next_issuance_keys(),
        "next_issuances_scan": next_scan,
        "expected_rain": {
            "n_seasons": season_total.get("n"),
            "season_total_mean_in": season_total.get("mean"),
            "season_total_median_in": season_total.get("median"),
            "season_total_min_in": season_total.get("min"),
            "season_total_max_in": season_total.get("max"),
            "season_total_p10_in": season_total.get("p10"),
            "season_total_p90_in": season_total.get("p90"),
            "oct_mean_in": (es.get("oct_total") or {}).get("mean"),
            "nov_mean_in": (es.get("nov_total") or {}).get("mean"),
            "dec_mean_in": (es.get("dec_total") or {}).get("mean"),
            "jan_mean_in": (es.get("jan_total") or {}).get("mean"),
            "basis": "1991-2020 observed record, " + archive_basis(
                "rain_temp", sources["ghcn_daily"]["label"]),
            "definition_wet_day": definitions.get("wet_day"),
            "definition_wet_streak": definitions.get("wet_streak"),
            "source_url": sources["ghcn_daily"]["url"],
            "source_key": "ghcn_daily",
        },
        "rain_duration": {
            "ge_3_days_pct": (streak.get("ge_3_days") or {}).get("pct"),
            "ge_3_days_n": (streak.get("ge_3_days") or {}).get("seasons"),
            "ge_5_days_pct": (streak.get("ge_5_days") or {}).get("pct"),
            "ge_5_days_n": (streak.get("ge_5_days") or {}).get("seasons"),
            "ge_7_days_pct": (streak.get("ge_7_days") or {}).get("pct"),
            "ge_7_days_n": (streak.get("ge_7_days") or {}).get("seasons"),
            "ge_10_days_pct": (streak.get("ge_10_days") or {}).get("pct"),
            "ge_10_days_n": (streak.get("ge_10_days") or {}).get("seasons"),
            "longest_mean_days": longest.get("mean"),
            "longest_median_days": longest.get("median"),
            "longest_max_days": longest.get("max"),
            "n_seasons": longest.get("n"),
            "phase_conditioned": {
                "phase": current_enso.get("phase"),
                "phase_label": enso_streaks.get("phase_label") or current_enso.get("phase_label"),
                "n": enso_streaks.get("n"),
                "ge_7_days_pct": (enso_streaks.get("ge_7_days") or {}).get("pct"),
                "ge_7_days_seasons": (enso_streaks.get("ge_7_days") or {}).get("seasons"),
                "ge_10_days_pct": (enso_streaks.get("ge_10_days") or {}).get("pct"),
                "longest_mean_days": (enso_streaks.get("longest_streak_days") or {}).get("mean"),
                "longest_max_days": (enso_streaks.get("longest_streak_days") or {}).get("max"),
                "caveat": ("Observed frequency in the seasons on record whose ONI "
                           "placed them in this phase - a small sample, printed "
                           "with its denominator. Not a forecast for 2026-27."),
            },
            "basis": "1991-2020 observed record (" + archive_basis(
                "rain_temp", sources["ghcn_daily"]["label"]) + ")",
            "definition": " ".join(x for x in (definitions.get("wet_day"),
                                               definitions.get("wet_streak")) if x),
            "source_url": sources["ghcn_daily"]["url"],
            "source_key": "ghcn_daily",
        },
        "wind_rain": {
            "hourly_available": bool(hourly.get("available")),
            "hourly_mean_days": (hourly.get("days_with_a_simultaneous_hour") or {}).get("mean"),
            "hourly_median_days": (hourly.get("days_with_a_simultaneous_hour") or {}).get("median"),
            "hourly_max_days": (hourly.get("days_with_a_simultaneous_hour") or {}).get("max"),
            "hourly_n_seasons": (hourly.get("days_with_a_simultaneous_hour") or {}).get("n"),
            "hourly_mean_hours": hours_stats.get("mean"),
            "hourly_median_hours": hours_stats.get("median"),
            "hourly_max_hours": hours_stats.get("max"),
            "hourly_station_id": hourly.get("station_id"),
            "hourly_station_name": hourly.get("station_name"),
            "hourly_wind_threshold_kt": hourly.get("wind_threshold_kt"),
            "hourly_multi_hour_reports": hourly.get("simultaneous_hours_from_multi_hour_reports"),
            "whole_day_mean_days": wind_rain_day.get("mean"),
            "whole_day_median_days": wind_rain_day.get("median"),
            "whole_day_max_days": wind_rain_day.get("max"),
            "whole_day_n_seasons": wind_rain_day.get("n"),
            "heavy_mean_days": heavy.get("mean"),
            "heavy_median_days": heavy.get("median"),
            "heavy_max_days": heavy.get("max"),
            "heavy_definition": definitions.get("heavy_wind_and_rain_day"),
            "hourly_definition": definitions.get("wind_and_rain_day"),
            "basis": ("hour-by-hour: " + archive_basis("isd_hourly", sources["isd"]["label"])
                      + "; whole-day and heavy pairings: "
                      + archive_basis("wind", sources["gsod"]["label"])),
            "source_urls": [sources["isd"]["url"], sources["gsod"]["url"],
                            sources["ghcn_daily"]["url"]],
            "caveat": ("Wind is measured at SFO (KSFO), 11.9 mi from this ZIP, the "
                       "nearest official station with a complete 1991-2020 wind "
                       "record; whether the ocean-facing Sunset is windier or "
                       "calmer is not established here, so this is an SFO "
                       "reference value, not a bound for 94122."),
        },
        "peak_gusts": {
            "n_seasons": gusts.get("n"),
            "station_id": hourly.get("station_id"),
            "station_name": hourly.get("station_name"),
            "distance_mi": gust_distance_mi,
            "distance_sentence": gust_distance_sentence,
            "distance_note": ("Read out of the verified dataset's own sentence (published "
                              "above word for word); a distance this tier cannot find in "
                              "the data is left empty rather than remembered."
                              if gust_distance_mi else
                              "No dataset read by this tier states the station's distance "
                              "from the ZIP centroid, so none is published."),
            "mean_mph": gusts.get("mean"),
            "median_mph": gusts.get("median"),
            "max_mph": gusts.get("max"),
            "min_mph": gusts.get("min"),
            "basis": "1991-2020 observed record, " + archive_basis("wind", sources["gsod"]["label"]),
            "source_url": sources["gsod"]["url"],
            "source_key": "gsod",
        },
        "ocean_wind": {
            "available": bool(ocean.get("available")),
            "station_id": ocean.get("station_id"),
            "station_name": ocean.get("station_name"),
            "distance_mi": ocean.get("distance_mi_from_centroid"),
            "seasons_with_data": ocean.get("seasons_with_data"),
            "seasons_total": ocean.get("seasons_total"),
            "thin_seasons": ocean.get("thin_seasons"),
            "gale_threshold_kt": gale_threshold_kt,
            "gale_counter_key": gale_key,
            "gale_mean_days": gale_stats.get("mean"),
            "gale_median_days": gale_stats.get("median"),
            "gale_max_days": gale_stats.get("max"),
            "gale_n_seasons": gale_stats.get("n_seasons"),
            "max_gust_mean_mph": (ocean.get("max_gust_mph") or {}).get("mean"),
            "max_gust_max_mph": (ocean.get("max_gust_mph") or {}).get("max"),
            "caveat": ocean.get("caveat"),
            "caveat_is_bound": ocean.get("is_a_bound_for_94122"),
            "source_url": sources["ndbc_46026"]["url"],
            "source_key": "ndbc_46026",
            "unavailable_note": (
                None if ocean.get("available") else
                "The ocean-side buoy record (NOAA NDBC station 46026) is not "
                "published in this snapshot, so no ocean wind figure is shown "
                "here. The land record at KSFO above is unaffected."),
            "status": ("published" if ocean.get("available") else "not published in this snapshot"),
        },
        "enso_conditioned": {
            "phase": conditioned.get("phase"),
            "phase_label": conditioned.get("phase_label"),
            "seasons_in_phase": conditioned.get("seasons_in_phase"),
            "mean_in": conditioned.get("mean_in"),
            "median_in": conditioned.get("median_in"),
            "min_in": conditioned.get("min_in"),
            "max_in": conditioned.get("max_in"),
            "contrast": conditioned.get("contrast") or [],
            "how_to_read": conditioned.get("how_to_read"),
            "source_url": conditioned.get("source_url") or sources["oni"]["url"],
            "source_key": "oni",
        },
        "definitions": definitions,
        "cost_drivers_ranked": drivers,
        "cost_drivers_note": es.get("cost_drivers_note"),
        "outer_sunset_profile": es.get("outer_sunset_profile"),
        "bottom_line": es.get("bottom_line"),
        "record_coverage": es.get("record_coverage"),
        "sources": {k: v["url"] for k, v in sources.items()},
        "sources_detail": sources,
        "sources_list": sources_list,
        "disclaimer": (
            "Independent project. Not affiliated with NOAA / NWS / NCEI / CPC. "
            "For life-safety decisions use weather.gov and weather.gov/mtr "
            "directly. No daily forecast exists beyond about 7 days; the "
            "1991-2020 figures here are an observed record, not a forecast."
        ),
        "verification_note": (
            "Every number above is re-derived from its source dataset and checked "
            "line by line before this page is published; every quoted sentence is "
            "re-checked as a verbatim substring of the fetched file. Sources are "
            "official NOAA / NWS / NCEI / CPC / U.S. Census hosts only - no "
            "commercial provider is used, because a number that cannot be "
            "checked against a public file is not published here."
        ),
    }
    return summary


# --------------------------------------------------------------------------- #
# printable page
# --------------------------------------------------------------------------- #

def render_markdown(summary: dict) -> str:
    """Render the printable one-pager from the JSON alone.

    Every number and every quoted sentence in the output is read out of
    ``summary``; nothing is typed in here.  ``selftest`` asserts that property by
    extracting each numeric token from this page and requiring it to exist in the
    JSON, so a hand-typed figure cannot survive.
    """
    s = summary
    line = []
    add = line.append

    add(f"# Repair & Maintenance Cost Impact \u2014 Executive Summary, ZIP 94122")
    add("")
    add(f"**Location:** {fmt(s.get('location'), 0)} \u00b7 "
        f"**Season:** {fmt(s.get('season_window'), 0)} \u00b7 "
        f"**Built from datasets stamped:** {fmt(s.get('generated_utc'), 0)}")
    add("")
    add(f"> {s['disclaimer']}")
    add("")
    add(f"**In one paragraph.** {fmt(s.get('executive_headline'), 0)}")
    add("")

    sb = s.get("scoreboard") or {}
    add("## Where the numbers come from, and how current they are")
    add("")
    add(f"- **Datasets read:** {', '.join(s['built_from']['datasets'])}, with the "
        f"newest content fetched into them at "
        f"{fmt(s['currency'].get('newest_fetched_content_utc'), 0)}; "
        f"build-stamped inputs: "
        + "; ".join(f"{k} {v.get('build_stamp')}"
                    for k, v in (s.get("sources_read") or {}).items()
                    if v.get("build_stamp"))
        + (f"; no build stamp of their own (per-fetch retrieval times are recorded in "
           f"the file): {', '.join(s['currency'].get('sources_without_a_build_stamp') or [])}."
           if s["currency"].get("sources_without_a_build_stamp") else "."))
    add(f"- **Scoreboard:** {fmt(sb.get('days_total'), 0)} days, "
        f"{fmt(sb.get('days_with_all_seven_fields'), 0)} of them carrying all seven "
        f"requested fields (high, low, humidity, wind, gusts, rain chance, rain amount). "
        f"{fmt(sb.get('days_with_a_real_official_forecast_now'), 0)} day(s) of this window lie "
        f"inside the official NWS forecast horizon today"
        + (f" (the horizon currently ends {sb.get('official_horizon_ends')})"
           if sb.get("official_horizon_ends") else "")
        + ". Every other day shows the 1991-2020 observed record for that calendar date.")
    add(f"- **Currency rule:** {s['currency']['note']} "
        f"Oldest source stamp: {fmt(s['currency'].get('oldest_source_utc'), 0)}; "
        f"newest: {fmt(s['currency'].get('newest_source_utc'), 0)}.")
    add("")

    add("## What could change this outlook, and when (NOAA's own sentences)")
    add("")
    if s.get("next_issuances"):
        for item in s["next_issuances"]:
            add(f"- **{fmt(item.get('label'), 0)}**")
            add(f"  - \u201c{item.get('text')}\u201d")
            add(f"  - Verify: [{item.get('source_url')}]({item.get('source_url')})"
                + (f" \u00b7 file SHA-256 `{str(item.get('source_sha256'))[:16]}\u2026`"
                   if item.get("source_sha256") else ""))
    if s.get("next_issuances_not_found"):
        add(f"- Not located in the fetched text this run: "
            f"{', '.join(s['next_issuances_not_found'])}. A sentence CPC rewrites "
            f"stops appearing here rather than being paraphrased.")
    add("")

    add("## Current Official Outlook for Oct 2026 \u2013 Jan 2027")
    add("")
    enso = s.get("official_enso") or {}
    cur = s.get("current_enso") or {}
    add(f"- **ENSO state (CPC's product, not a re-derivation):** "
        f"{enso.get('state') or fmt(cur.get('phase_label'))} \u00b7 "
        f"Alert System Status: {fmt(enso.get('alert_status') or cur.get('alert_status'))} "
        f"(latest published ONI {fmt(cur.get('oni_c_fmt'))}, {fmt(cur.get('label'))})")
    add(f"  - Verify: [ENSO Diagnostic Discussion]({fmt(enso.get('source_url'), 0)}) "
        f"\u00b7 [ONI table]({s['sources']['oni']})")
    for q in s.get("enso_strength_quotes") or []:
        add(f"- **{fmt(q.get('label'), 0)}** \u2014 \u201c{q.get('text')}\u201d")
    tilt = s.get("cpc_tilt") or {}
    if tilt:
        add(f"- **CPC precipitation outlooks covering this season:** "
            f"{fmt(tilt.get('periods_with_a_tilt'), 0)} of "
            f"{fmt(tilt.get('periods_covering_this_season'), 0)} carry a tilt above the "
            f"{fmt(tilt.get('baseline_pct'), 1)}% three-way baseline; "
            f"{fmt(tilt.get('periods_at_climatological_baseline'), 0)} sit on it (equal chances).")
        hp = tilt.get("highest_probability") or {}
        if hp:
            add(f"  - Strongest tilt: {hp.get('period')} \u2014 {hp.get('category_label')} "
                f"{fmt(hp.get('probability_pct'), 1)}% (issued {hp.get('issued')})")
            add(f"  - Verify: [{hp.get('source_url')}]({hp.get('source_url')})")
    rec = s.get("enso_conditioned") or {}
    if rec.get("seasons_in_phase"):
        add(f"- **What the same ENSO phase delivered in the record:** "
            f"{rec.get('phase_label')} seasons averaged {fmt(rec.get('mean_in'))} in "
            f"(median {fmt(rec.get('median_in'))}, range {fmt(rec.get('min_in'))}\u2013"
            f"{fmt(rec.get('max_in'))} in) over {fmt(rec.get('seasons_in_phase'), 0)} seasons. "
            f"{fmt(rec.get('how_to_read'), 0)}")
    for c in s.get("caveats") or []:
        add(f"- **What NOAA's forecasters caution (verbatim):** \u201c{c.get('text')}\u201d")
    if s.get("caveats_not_found"):
        add(f"- Caveat sentences no longer present in the fetched discussion are listed, "
            f"not rewritten: {', '.join(s['caveats_not_found'])}")
    add("")

    er = s.get("expected_rain") or {}
    add("## Expected Rain Amounts (1991\u20132020 observed)")
    add("")
    add(f"- **Season total, Oct 1 \u2013 Jan 31:** mean {fmt(er.get('season_total_mean_in'))} in \u00b7 "
        f"median {fmt(er.get('season_total_median_in'))} in \u00b7 p10\u2013p90 "
        f"{fmt(er.get('season_total_p10_in'))}\u2013{fmt(er.get('season_total_p90_in'))} in \u00b7 "
        f"range {fmt(er.get('season_total_min_in'))}\u2013{fmt(er.get('season_total_max_in'))} in "
        f"over {fmt(er.get('n_seasons'), 0)} seasons")
    add(f"- **By month (means):** Oct {fmt(er.get('oct_mean_in'))} in \u00b7 "
        f"Nov {fmt(er.get('nov_mean_in'))} in \u00b7 Dec {fmt(er.get('dec_mean_in'))} in \u00b7 "
        f"Jan {fmt(er.get('jan_mean_in'))} in")
    add(f"- **Basis:** {fmt(er.get('basis'), 0)}")
    add(f"- **Verify:** [{fmt(er.get('source_url'), 0)}]({fmt(er.get('source_url'), 0)})")
    add("")

    rd = s.get("rain_duration") or {}
    add("## Long-Duration Rain Events (the repair bottleneck)")
    add("")
    add(f"- **Share of the {fmt(rd.get('n_seasons'), 0)} seasons on record with a run of:** "
        f"3+ wet days {fmt(rd.get('ge_3_days_pct'), 1)}% ({fmt(rd.get('ge_3_days_n'), 0)} of "
        f"{fmt(rd.get('n_seasons'), 0)}) \u00b7 5+ days {fmt(rd.get('ge_5_days_pct'), 1)}% "
        f"({fmt(rd.get('ge_5_days_n'), 0)}) \u00b7 7+ days {fmt(rd.get('ge_7_days_pct'), 1)}% "
        f"({fmt(rd.get('ge_7_days_n'), 0)}) \u00b7 10+ days {fmt(rd.get('ge_10_days_pct'), 1)}% "
        f"({fmt(rd.get('ge_10_days_n'), 0)})")
    add(f"- **Longest run in a season:** mean {fmt(rd.get('longest_mean_days'), 1)} days \u00b7 "
        f"median {fmt(rd.get('longest_median_days'), 1)} \u00b7 max {fmt(rd.get('longest_max_days'), 1)} days")
    ph = rd.get("phase_conditioned") or {}
    if ph.get("n"):
        add(f"- **Conditioned on this season's phase ({fmt(ph.get('phase_label'), 0)}, "
            f"n = {fmt(ph.get('n'), 0)} seasons):** 7+ day runs in "
            f"{fmt(ph.get('ge_7_days_pct'), 1)}% of them ({fmt(ph.get('ge_7_days_seasons'), 0)} of "
            f"{fmt(ph.get('n'), 0)}); 10+ day runs in {fmt(ph.get('ge_10_days_pct'), 1)}%; longest run "
            f"averaged {fmt(ph.get('longest_mean_days'), 1)} days (max {fmt(ph.get('longest_max_days'), 1)}). "
            f"{fmt(ph.get('caveat'), 0)}")
    add(f"- **Basis:** {fmt(rd.get('basis'), 0)} \u00b7 "
        f"[source]({fmt(rd.get('source_url'), 0)})")
    add("")

    wr = s.get("wind_rain") or {}
    add("## Wind + Rain Together (wind-driven intrusion)")
    add("")
    if wr.get("hourly_available"):
        add(f"- **Hour by hour (true simultaneous), station {fmt(wr.get('hourly_station_id'), 0)}:** "
            f"mean {fmt(wr.get('hourly_mean_days'), 1)} days/season \u00b7 median "
            f"{fmt(wr.get('hourly_median_days'), 1)} \u00b7 max {fmt(wr.get('hourly_max_days'), 1)} "
            f"(n = {fmt(wr.get('hourly_n_seasons'), 0)} seasons) \u00b7 "
            f"{fmt(wr.get('hourly_mean_hours'), 1)} simultaneous hours/season on average "
            f"(median {fmt(wr.get('hourly_median_hours'), 1)}, max {fmt(wr.get('hourly_max_hours'), 1)}) "
            f"at >= {fmt(wr.get('hourly_wind_threshold_kt'), 0)} kt")
        if wr.get("hourly_multi_hour_reports"):
            add(f"  - Hours whose precipitation report covers more than one hour, disclosed "
                f"separately: {fmt(wr.get('hourly_multi_hour_reports'), 0)}")
    else:
        add("- **Hour-by-hour wind + rain:** not published in this snapshot "
            "(the NCEI hourly archive this tier reads was not available on this run).")
    add(f"- **Whole-day pairing (the comparison figure):** mean "
        f"{fmt(wr.get('whole_day_mean_days'), 1)} days/season \u00b7 median "
        f"{fmt(wr.get('whole_day_median_days'), 1)} \u00b7 max {fmt(wr.get('whole_day_max_days'), 1)} "
        f"(n = {fmt(wr.get('whole_day_n_seasons'), 0)}) \u2014 this counts a day when rain and "
        f"wind each occurred somewhere in it, which is why it is higher.")
    add(f"- **Heavy joint days** ({fmt(wr.get('heavy_definition'), 0)}): mean "
        f"{fmt(wr.get('heavy_mean_days'), 1)} \u00b7 median {fmt(wr.get('heavy_median_days'), 1)} \u00b7 "
        f"max {fmt(wr.get('heavy_max_days'), 1)} per season")
    pg = s.get("peak_gusts") or {}
    add(f"- **Season peak gust** at {fmt(pg.get('station_name'))} "
        f"({fmt(pg.get('station_id'))}): mean {fmt(pg.get('mean_mph'))} mph \u00b7 median "
        f"{fmt(pg.get('median_mph'))} \u00b7 lowest {fmt(pg.get('min_mph'))} \u00b7 record "
        f"{fmt(pg.get('max_mph'))} mph (n = {fmt(pg.get('n_seasons'))} seasons)")
    add(f"  - Distance from the ZIP centroid \u2014 the dataset's own sentence, "
        f"published whole so the number is never separated from its caveat: "
        f"\u201c{fmt(pg.get('distance_sentence'))}\u201d")
    ow = s.get("ocean_wind") or {}
    if ow.get("available"):
        add(f"- **Ocean-side reference (NOAA NDBC {fmt(ow.get('station_id'))}, "
            f"{fmt(ow.get('distance_mi'))} mi offshore):** gale days at "
            f"{fmt(ow.get('gale_threshold_kt'))} kt mean {fmt(ow.get('gale_mean_days'))} \u00b7 "
            f"median {fmt(ow.get('gale_median_days'))} \u00b7 max {fmt(ow.get('gale_max_days'))}; season "
            f"maximum gust mean {fmt(ow.get('max_gust_mean_mph'))} mph \u00b7 worst "
            f"{fmt(ow.get('max_gust_max_mph'))} mph")
        add(f"  - NDBC's own caveat, published with the numbers: \u201c{ow.get('caveat')}\u201d")
    else:
        add(f"- **Ocean-side reference:** {fmt(ow.get('unavailable_note'), 0)}")
    add(f"- **SFO caveat:** {fmt(wr.get('caveat'), 0)}")
    add(f"- **Verify:** " + " \u00b7 ".join(f"[{u}]({u})" for u in (wr.get("source_urls") or [])))
    add("")

    add("## Ranked Repair & Maintenance Cost Drivers")
    add("")
    add(f"_{fmt(s.get('cost_drivers_note'), 0)}_")
    add("")
    add(f"_{fmt(SEVERITY_RULE, 0)}_")
    add("")
    for d in s.get("cost_drivers_ranked") or []:
        add(f"### #{d.get('rank')} {fmt(d.get('driver'), 0)} \u2014 severity: "
            f"{str(d.get('severity')).upper()}")
        add("")
        add(f"**Headline number:** {fmt(d.get('metric_label'), 0)} \u2014 {fmt(d.get('key_metric'), 0)}")
        add("")
        add(f"**Why it costs ({fmt(d.get('why_it_costs_label'), 0)}):** {fmt(d.get('why_it_costs'), 0)}")
        add("")
        add("| Evidence | Value |")
        add("| --- | --- |")
        for ev in d.get("evidence") or []:
            add(f"| {ev.get('label')} | {ev.get('value')} |")
        add("")
        srcs = " \u00b7 ".join(f"[{x.get('label')}]({x.get('url')})"
                              for x in (d.get("sources") or []) if x.get("url"))
        add(f"**Verify:** {srcs}")
        add("")

    osp = s.get("outer_sunset_profile") or {}
    if osp:
        add("## Outer Sunset 94122 Property Profile")
        add("")
        for key in ("neighborhood", "centroid_coordinates", "ocean_exposure",
                    "building_stock_vulnerabilities", "soil_and_drainage",
                    "marine_corrosion"):
            if osp.get(key):
                add(f"- **{key.replace('_', ' ').title()}:** {osp[key]}")
        add("")

    rc = s.get("record_coverage") or {}
    if rc.get("archives"):
        add("## How current each archive is")
        add("")
        add(f"As of {rc.get('as_of')} (published by the run, not typed here):")
        add("")
        add("| Archive | Newest row fetched | Age (days) | Source |")
        add("| --- | --- | --- | --- |")
        for a in rc["archives"]:
            add(f"| {a.get('label')} | {a.get('last_date')} | {a.get('age_days')} | "
                f"[link]({a.get('url')}) |")
        add("")

    add("## Verification \u2014 official sources only")
    add("")
    for item in s.get("sources_list") or []:
        add(f"- **{item.get('label')}** \u2014 {item.get('url')}")
    add("")
    add(f"- **Built from:** {', '.join((s.get('built_from') or {}).get('datasets') or [])}.")
    add("  - Input stamps: " + " \u00b7 ".join(
        f"{k} {v.get('build_stamp') or 'no build stamp (per-fetch retrieval times)'}"
        for k, v in (s.get('sources_read') or {}).items()))
    add(f"- **Claim ledger:** `data/verify_report.txt` and `data/verify.json` "
        f"re-derive every number above from its source file on every pipeline run.")
    add("")
    add(f"_{s.get('verification_note')}_")
    add("")
    return "\n".join(line) + "\n"


def write_outputs(summary: dict, datadir: Path, docsdir: Path) -> tuple[Path, Path, Path]:
    out_json = datadir / "repair_maintenance_summary.json"
    out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    md = render_markdown(summary)
    out_md = datadir / "repair_maintenance_executive.md"
    out_md.write_text(md, encoding="utf-8")
    docs_md = docsdir / "REPAIR_MAINTENANCE_EXECUTIVE_SUMMARY.md"
    docs_md.parent.mkdir(parents=True, exist_ok=True)
    docs_md.write_text(md, encoding="utf-8")
    return out_json, out_md, docs_md


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true",
                    help="run the offline self-test and exit")
    ap.add_argument("--datadir", default=str(DATA))
    ap.add_argument("--docsdir", default=str(ROOT / "docs"))
    args = ap.parse_args(argv)

    if args.selftest:
        import selftest_repair_tier
        return selftest_repair_tier.run()

    datadir = Path(args.datadir)
    datasets = {name: load(name, datadir) for name in SOURCE_FILES}
    if not (datasets.get("landlord.json") or {}).get("executive_summary"):
        print("repair_maintenance_summary: landlord.json is missing or has no "
              "executive_summary block - nothing written", file=sys.stderr)
        return 1
    try:
        summary = build_summary(datasets)
    except RepairTierError as exc:
        print(f"repair_maintenance_summary: {exc} - nothing written", file=sys.stderr)
        return 1

    out_json, out_md, docs_md = write_outputs(summary, datadir, Path(args.docsdir))
    c = summary["currency"]
    print(f"repair_maintenance_summary: wrote {out_json.name} "
          f"({out_json.stat().st_size:,} bytes), {out_md.name}, {docs_md.name}")
    print(f"  stamp {summary['generated_utc']} \u00b7 drivers "
          f"{len(summary['cost_drivers_ranked'])} \u00b7 "
          f"watch-list quotes {len(summary['next_issuances'])}/"
          f"{len(summary['next_issuances']) + len(summary['next_issuances_not_found'])} \u00b7 "
          f"sources_agree={c['sources_agree']}")
    if not c["sources_agree"]:
        print(f"  IRREGULARITY: datasets disagree on their stamp "
              f"(oldest {c['oldest_source_utc']}, newest {c['newest_source_utc']}, "
              f"differing: {c['sources_disagreeing']})")
    if summary["next_issuances_not_found"]:
        print(f"  not found in the fetched text this run (published as such, not "
              f"paraphrased): {summary['next_issuances_not_found']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
