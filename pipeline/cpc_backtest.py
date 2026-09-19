#!/usr/bin/env python3
"""Back-test NOAA/CPC seasonal outlooks against what actually fell at 94122.

The site publishes CPC's official 3-month precipitation and temperature
outlooks, sampled point-in-polygon at the verified 94122 centroid.  A tilt that
is never scored is decoration, so this script asks the only question that
matters: **when CPC named a category for a season, did that season verify in
that category here?**

How it works
------------
1.  *Discover* which issuances exist.  The list is read from CPC's own GIS page
    (``.../GIS_DATA/us_tempprcpfcst/seasonal.php``) rather than guessed, so the
    retention window CPC actually operates is measured on every run and
    published with the result.  Verified 18 Sep 2026: that page links eight
    monthly issuances (``seasprcp_202602.zip`` .. ``seasprcp_202609.zip``), all
    on ``ftp.cpc.ncep.noaa.gov`` - a host this project has already vetted.
2.  *Fetch and sample* each ``seasprcp_YYYYMM.zip`` / ``seastemp_YYYYMM.zip``
    with :mod:`lib_cpc` - the identical code path that samples the live outlook
    published on the front page.  Every lead inside the archive is sampled
    (``lead1_OND_prcp`` .. ``lead14_...``), so one issuance yields up to 14
    scoreable seasons.
3.  *Observe* the target season from NCEI GHCN-Daily at the published rain/
    temperature station (``USW00023272``), the same file the whole climatology
    is built from.
4.  *Assign a tercile* to the observed season total against this project's own
    1991-2020 distribution of the same 3-month season at the same station, and
    compare it with the category CPC named.
5.  *Accumulate.*  CPC drops an issuance off its server after roughly eight
    months, so every sampled issuance is kept in ``data/cpc_backtest.json``.
    An issuance sampled today and a season that ends in January are still both
    in the file when the observations finally arrive - which is how the Oct-Jan
    seasons get scored prospectively even though they cannot be back-filled.

Nothing here is a forecast and nothing here is merged into the scoreboard.

Run:  ``python3 pipeline/cpc_backtest.py [--datadir data] [--outdir data]``
      ``python3 pipeline/cpc_backtest.py --selftest``   (offline, synthetic)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib_cpc as cpclib                     # noqa: E402
import lib_fetch as fetchlib                 # noqa: E402
import lib_provenance as provlib             # noqa: E402
import climo                                 # noqa: E402
from build_calendar import parse_season_key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# Sources.  Every one of these is an official NOAA host already vetted by
# pipeline/verify_sources.py.  No new host is introduced by this script.
# --------------------------------------------------------------------------

#: CPC's own index of monthly/seasonal outlook shapefiles.  Parsed for the
#: issuance list so the retention window is *measured*, not assumed.
CPC_SEASONAL_INDEX = ("https://www.cpc.ncep.noaa.gov/products/GIS/GIS_DATA/"
                      "us_tempprcpfcst/seasonal.php")
CPC_GIS_BASE = "https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst"

#: The station the whole rain/temperature climatology is built from.  Read from
#: ``data/climatology.json`` when present so this script can never drift onto a
#: different station than the one the site publishes.
GHCN_STATION_FALLBACK = "USW00023272"
GHCN_BASE = ("https://www.ncei.noaa.gov/data/global-historical-climatology-"
             "network-daily/access")

#: Base period for the terciles.  Same 30 seasons the site publishes.
BASE_PERIOD = (1991, 2020)

#: A three-way split has a climatological baseline of 100/3 %.  Published next
#: to every hit-rate so a reader can see whether a number beats doing nothing.
BASELINE_PCT = round(100.0 / 3.0, 1)

#: CPC writes its categories in the shapefile DBF ``Cat`` field.  These are the
#: only values this project has observed in the real files (recorded in
#: ``data/calendar.json`` -> ``cpc.records``); anything else is reported rather
#: than mapped by guesswork.
CATEGORY_TO_TERCILE = {
    "ABOVE": "above", "A": "above",
    "BELOW": "below", "B": "below",
    "NORMAL": "normal", "N": "normal", "NEAR": "normal",
}
#: ``EC`` = "equal chances": CPC's own label for *no tilt*.  It makes no
#: categorical statement, so it can neither hit nor miss.  Counted separately.
NO_TILT_CATEGORIES = {"EC", "EQUAL CHANCES", "EQUAL"}

#: Minimum probability (per cent) for a pair to count as a genuine tilt.  CPC's
#: long-lead polygons frequently carry ``Cat="Above"`` together with
#: ``Prob=33.0``, which is the baseline and not a tilt - the site already flags
#: that case, and the back-test keeps it out of the tilt subset for the same
#: reason.
TILT_PROB_MIN = 40.0

#: Documented, verified state of the third-party archive named in the brief.
IRI_FINDING = {
    "host": "iridl.ldeo.columbia.edu",
    "url": "https://iridl.ldeo.columbia.edu/SOURCES/.NOAA/.NCEP/.CPC/.seasonal/",
    "checked_utc": "2026-09-18T00:00:00Z",
    "result": "sign-in required",
    "evidence": ("Fetching that URL returns the IRI Data Library sign-in page "
                 "('The Data Library now requires all users to sign in.'), not a "
                 "directory of shapefiles."),
    "decision": ("NOT added to ALLOWED_HOSTS. This project's rule is free, "
                 "public, official sources with no account and no key, and every "
                 "published number re-derivable from a file anyone can fetch. An "
                 "authenticated third-party mirror fails that rule even though "
                 "IRI is a respected NOAA partner: the back-test would depend on "
                 "credentials the reader cannot check, and on a copy of the file "
                 "rather than the publisher's own."),
    "consequence": ("Historical seasonal issuances older than CPC's own rolling "
                    "window cannot be back-filled anonymously. The back-test is "
                    "therefore run *prospectively*: every issuance is sampled and "
                    "stored while CPC still serves it, and scored when the season "
                    "it covers has been observed."),
}


def log(msg=""):
    print(msg, flush=True)


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

ISSUANCE_RE = re.compile(r"(seasprcp|seastemp)_(\d{6})\.zip", re.I)


def discover_issuances(fetch=fetchlib.get, manifest=None, note=None):
    """Read CPC's own index page and return the issuance months it links.

    Returns a dict with the sorted month list, the per-kind URLs, and the
    evidence (page URL, status, SHA-256, how many links were found).  If the
    page cannot be read the result says so; the caller then falls back to a
    computed trailing window and labels that fallback for what it is.
    """
    res = fetch(CPC_SEASONAL_INDEX, timeout=120)
    if manifest is not None:
        manifest.append(res.provenance(note="CPC seasonal outlook index page "
                                            "(issuance discovery)"))
    out = {
        "index_url": CPC_SEASONAL_INDEX,
        "http_status": res.status,
        "ok": bool(res.ok),
        "sha256": res.sha256,
        "retrieved_utc": res.retrieved_utc,
        "months": [],
        "urls": {},
        "method": "parsed the hrefs on CPC's own Monthly & Seasonal GIS index page",
    }
    if not res.ok or not res.body:
        out["error"] = res.error or f"HTTP {res.status}"
        if note:
            note("warning", "cpc_backtest",
                 "CPC's seasonal outlook index page could not be retrieved; the "
                 "issuance list was computed from the run date instead and is "
                 "labelled as a fallback.",
                 {"url": CPC_SEASONAL_INDEX, "status": res.status})
        return out

    text = fetchlib.decode_text(res.body)[0]
    found = {}
    for kind, ym in ISSUANCE_RE.findall(text):
        kind, ym = kind.lower(), ym
        found.setdefault(kind, set()).add(ym)
    months = sorted({ym for kind in found for ym in found[kind]})
    out["months"] = months
    out["by_kind"] = {k: sorted(v) for k, v in sorted(found.items())}
    for kind in ("seasprcp", "seastemp"):
        for ym in sorted(found.get(kind, ())):
            out["urls"][f"{kind}_{ym}"] = f"{CPC_GIS_BASE}/{kind}_{ym}.zip"
    out["count"] = len(months)
    if months:
        out["window"] = {"earliest": months[0], "latest": months[-1],
                         "months_linked": len(months)}
    return out


def fallback_months(today, n=14):
    """Trailing *n* issuance months ending with the current month.

    Only used when CPC's index page cannot be read.  Deliberately longer than
    the observed retention window so the real 404s are recorded as evidence of
    where the window actually is.
    """
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


# --------------------------------------------------------------------------
# sampling
# --------------------------------------------------------------------------

def sample_issuance(kind, ym, lat, lon, workdir, fetch=fetchlib.get,
                    manifest=None, note=None):
    """Fetch and point-sample one monthly issuance archive.

    ``kind`` is ``seasprcp`` or ``seastemp``.  Returns a dict with one entry per
    lead sampled, carrying the raw DBF row so every number downstream is
    traceable to the publisher's own attribute table.
    """
    url = f"{CPC_GIS_BASE}/{kind}_{ym}.zip"
    res = fetch(url, timeout=240)
    if manifest is not None:
        manifest.append(res.provenance(
            note=f"CPC {kind} issuance {ym} (back-test sample)"))
    if not res.ok:
        return {"kind": kind, "issuance_ym": ym, "url": url, "ok": False,
                "http_status": res.status, "error": res.error or f"HTTP {res.status}",
                "leads": []}
    sampled = cpclib.sample_shapefile_bytes(
        res.body, res.sha256, f"{kind}_{ym}", workdir, lat, lon, note=note)
    leads = []
    for smp in sampled.get("sampled") or []:
        if not smp.get("ok") or not smp.get("hits"):
            continue
        hit = smp["hits"][0]
        attrs = hit.get("attrs") or {}
        months, period_kind = parse_season_key(attrs.get("Valid_Seas"), smp.get("stem"))
        stem = smp.get("stem") or ""
        m_lead = re.match(r"lead(\d+)_", stem, re.I)
        leads.append({
            "stem": stem,
            "lead": int(m_lead.group(1)) if m_lead else None,
            "valid_season": attrs.get("Valid_Seas"),
            "period_kind": period_kind,
            "covers": [f"{y:04d}-{m:02d}" for (y, m) in months] if months else None,
            "category": attrs.get("Cat"),
            "probability_pct": attrs.get("Prob"),
            "fcst_date": attrs.get("Fcst_Date"),
            "polygon_index": hit.get("index"),
            "polygon_bbox_lon_lat": hit.get("bbox"),
            "used_nearest_polygon": bool(smp.get("used_nearest_polygon")),
            "raw_dbf_row": dict(attrs),
            "dbf_fields": smp.get("fields"),
        })
    return {"kind": kind, "issuance_ym": ym, "url": url, "ok": bool(leads),
            "http_status": res.status, "sha256": res.sha256,
            "bytes": res.size, "retrieved_utc": res.retrieved_utc,
            "n_shapefiles": sampled.get("n_shapefiles"),
            "n_leads_sampled": len(leads), "leads": leads}


# --------------------------------------------------------------------------
# observations and terciles
# --------------------------------------------------------------------------

def fetch_ghcn(station_id, fetch=fetchlib.get, manifest=None):
    """Fetch and parse the GHCN-Daily station file the site already publishes."""
    url = f"{GHCN_BASE}/{station_id}.csv"
    res = fetch(url, timeout=600)
    if manifest is not None:
        manifest.append(res.provenance(
            note=f"NCEI GHCN-Daily station file used for back-test observations: "
                 f"{station_id}"))
    if not res.ok or not res.body:
        return None, url, res
    data, fmt = climo.parse_ghcn_daily(res.text())
    return data, url, res


def period_dates(covers):
    """Every calendar date inside a list of ``YYYY-MM`` month keys."""
    days = []
    for ym in covers:
        y, m = int(ym[:4]), int(ym[5:7])
        d = dt.date(y, m, 1)
        while d.month == m:
            days.append(d)
            d += dt.timedelta(days=1)
    return days


def shift_to_base_year(covers, base_year):
    """The same season anchored so its first month falls in *base_year*.

    CPC's ``DJF 2026-2027`` and ``MAM 2026`` both become, for base year 1995,
    ``Dec 1995 - Feb 1996`` and ``Mar-May 1995`` respectively: the shift is
    taken from the first month so a season that crosses New Year keeps its
    shape.
    """
    if not covers:
        return None
    first_year = int(covers[0][:4])
    delta = base_year - first_year
    return [f"{int(ym[:4]) + delta:04d}-{ym[5:7]}" for ym in covers]


def observed_period(ghcn, covers, variable):
    """Observed total precipitation / mean temperature over *covers*.

    Returns ``None`` values with a reason when the period is not fully observed:
    an incomplete season is never scored, because a total computed from 87 of 92
    days is not the season CPC forecast.
    """
    days = period_dates(covers)
    if not days:
        return {"complete": False, "reason": "period has no dates", "n_days": 0}
    missing = [d.isoformat() for d in days
               if d.isoformat() not in ghcn or ghcn[d.isoformat()].get(
                   "PRCP" if variable == "prcp" else "TMAX") is None
               or (variable == "temp" and ghcn[d.isoformat()].get("TMIN") is None)]
    out = {"n_days": len(days), "n_missing": len(missing),
           "missing_dates": missing[:10], "complete": not missing,
           "first_day": days[0].isoformat(), "last_day": days[-1].isoformat()}
    if missing:
        out["reason"] = ("the period is not fully observed in GHCN-Daily yet "
                         f"({len(missing)} of {len(days)} days missing)")
        out["value"] = None
        return out
    if variable == "prcp":
        total = 0.0
        for d in days:
            inches = climo.ghcn_to_inches(ghcn[d.isoformat()]["PRCP"])
            total += inches or 0.0
        out["value"] = round(total, 2)
        out["unit"] = "in"
        out["quantity"] = "total liquid precipitation over the period"
    else:
        vals = []
        for d in days:
            tmax = climo.ghcn_to_f(ghcn[d.isoformat()]["TMAX"])
            tmin = climo.ghcn_to_f(ghcn[d.isoformat()]["TMIN"])
            if tmax is None or tmin is None:
                continue
            vals.append((tmax + tmin) / 2.0)
        out["value"] = round(sum(vals) / len(vals), 2) if vals else None
        out["unit"] = "degF"
        out["quantity"] = ("mean of the daily (TMAX+TMIN)/2 over the period - a "
                           "documented approximation to the seasonal mean "
                           "temperature CPC verifies against")
    return out


def base_distribution(ghcn, covers, variable, period=BASE_PERIOD):
    """This project's 1991-2020 distribution of the same season, same station."""
    values, incomplete = [], []
    for year in range(period[0], period[1] + 1):
        base_covers = shift_to_base_year(covers, year)
        obs = observed_period(ghcn, base_covers, variable)
        if obs.get("complete") and obs.get("value") is not None:
            values.append(obs["value"])
        else:
            incomplete.append(year)
    return {"n": len(values), "values": [round(v, 2) for v in sorted(values)],
            "years_excluded_incomplete": incomplete,
            "period": list(period)}


def tercile_boundaries(values):
    """Lower and upper tercile cuts, nearest-rank on the sorted base values."""
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return None, None
    return (round(climo.percentile(vals, 100.0 / 3.0), 3),
            round(climo.percentile(vals, 200.0 / 3.0), 3))


def assign_tercile(value, lo, hi):
    if value is None or lo is None or hi is None:
        return None
    if value < lo:
        return "below"
    if value > hi:
        return "above"
    return "normal"


TERCILE_LABEL = {"below": "Below (driest third)", "normal": "Normal (middle third)",
                 "above": "Above (wettest third)"}


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

def score_pair(lead, issuance_ym, kind, observed, dist, variable):
    """Score one (issuance, target season) pair.  Pure arithmetic, no I/O."""
    cat_raw = (lead.get("category") or "").strip()
    cat_up = cat_raw.upper()
    prob = lead.get("probability_pct")
    try:
        prob = float(prob)
    except (TypeError, ValueError):
        prob = None
    lo, hi = tercile_boundaries(dist.get("values") or [])
    obs_tercile = assign_tercile(observed.get("value"), lo, hi)

    row = {
        "variable": variable,
        "issuance_ym": issuance_ym,
        "issued": lead.get("fcst_date"),
        "lead": lead.get("lead"),
        "stem": lead.get("stem"),
        "season": lead.get("valid_season"),
        "covers": lead.get("covers"),
        "url": f"{CPC_GIS_BASE}/{kind}_{issuance_ym}.zip",
        "cpc_category_raw": cat_raw or None,
        "cpc_probability_pct": prob,
        "used_nearest_polygon": bool(lead.get("used_nearest_polygon")),
        "observed_value": observed.get("value"),
        "observed_unit": observed.get("unit"),
        "observed_quantity": observed.get("quantity"),
        "observed_complete": bool(observed.get("complete")),
        "observed_n_days": observed.get("n_days"),
        "observed_n_missing": observed.get("n_missing"),
        "observed_tercile": obs_tercile,
        "observed_tercile_label": TERCILE_LABEL.get(obs_tercile),
        "tercile_low": lo,
        "tercile_high": hi,
        "base_n": dist.get("n"),
        "base_years_excluded_incomplete": dist.get("years_excluded_incomplete"),
    }

    # --- status: scored / no-tilt / unscoreable, with the reason always named
    if cat_up in NO_TILT_CATEGORIES:
        row["status"] = "no-tilt"
        row["reason"] = ("CPC published this polygon as 'EC' (equal chances), which "
                         "is no tilt at all: it cannot hit or miss, so it is counted "
                         "separately instead of being scored as a miss.")
        row["hit"] = None
        return row
    forecast_tercile = CATEGORY_TO_TERCILE.get(cat_up)
    if forecast_tercile is None:
        row["status"] = "unrecognised-category"
        row["reason"] = (f"CPC's category {cat_raw!r} is not one this project maps to "
                         "a tercile; reported rather than guessed at.")
        row["hit"] = None
        return row
    row["forecast_tercile"] = forecast_tercile
    if not observed.get("complete") or observed.get("value") is None:
        row["status"] = "not-yet-observable"
        row["reason"] = observed.get("reason") or "the target season is not fully observed"
        row["hit"] = None
        return row
    if obs_tercile is None:
        row["status"] = "no-tercile"
        row["reason"] = ("fewer than three complete base-period seasons were available "
                         "for this season at this station, so no tercile cuts could be "
                         "computed")
        row["hit"] = None
        return row
    row["status"] = "scored"
    row["hit"] = bool(forecast_tercile == obs_tercile)
    row["reason"] = None
    # Probability CPC assigned to the category that actually verified.  Only the
    # named category's probability is published by CPC; the two unnamed ones are
    # taken to share the remainder equally, which is how CPC constructs its
    # probability maps.  That is an assumption, so it is stated in the record and
    # the hit-rate above (which needs no assumption) stays the headline.
    if prob is not None:
        remainder = (100.0 - prob) / 2.0
        row["prob_of_verifying_tercile_pct"] = round(
            prob if row["hit"] else remainder, 1)
        row["prob_convention"] = ("CPC publishes one probability, for the category it "
                                  "names; the other two are taken to share the "
                                  "remainder equally. Stated, not assumed silently.")
    return row


def summarise(rows):
    """Hit-rate summary, broken out the ways a reader would ask for."""
    scored = [r for r in rows if r["status"] == "scored"]
    hits = [r for r in scored if r["hit"]]

    def block(subset):
        s = [r for r in subset if r["status"] == "scored"]
        h = [r for r in s if r["hit"]]
        probs = [r["cpc_probability_pct"] for r in s
                 if isinstance(r.get("cpc_probability_pct"), (int, float))]
        pv = [r.get("prob_of_verifying_tercile_pct") for r in s
                 if isinstance(r.get("prob_of_verifying_tercile_pct"), (int, float))]
        return {
            "n_scored": len(s),
            "n_hits": len(h),
            "hit_rate_pct": round(100.0 * len(h) / len(s), 1) if s else None,
            "baseline_pct": BASELINE_PCT,
            "mean_probability_named_category_pct":
                round(sum(probs) / len(probs), 1) if probs else None,
            "mean_probability_of_verifying_tercile_pct":
                round(sum(pv) / len(pv), 1) if pv else None,
        }

    by_status = defaultdict(int)
    for r in rows:
        by_status[r["status"]] += 1

    out = {
        "n_pairs": len(rows),
        "by_status": dict(sorted(by_status.items())),
        "overall": block(rows),
        "by_variable": {v: block([r for r in rows if r["variable"] == v])
                        for v in ("prcp", "temp")},
        "by_category": {},
        "tilt_only": block([r for r in rows
                            if isinstance(r.get("cpc_probability_pct"), (int, float))
                            and r["cpc_probability_pct"] >= TILT_PROB_MIN]),
        "by_lead_bucket": {},
    }
    for cat in sorted({(r.get("cpc_category_raw") or "?") for r in rows}):
        out["by_category"][cat] = block([r for r in rows
                                         if (r.get("cpc_category_raw") or "?") == cat])
    buckets = ((1, 3, "lead 1-3 (next season to 3 seasons out)"),
               (4, 6, "lead 4-6"),
               (7, 14, "lead 7-14 (up to a year ahead)"))
    for lo, hi, label in buckets:
        out["by_lead_bucket"][label] = block(
            [r for r in rows if isinstance(r.get("lead"), int) and lo <= r["lead"] <= hi])
    return out


RAINY_MONTHS = {10, 11, 12, 1}


def rainy_season_relevance(rows):
    """Which pairs target a season that covers any of Oct-Jan (the landlord's
    question), and why they are or are not scored yet."""
    out = []
    for r in rows:
        months = {int(ym[5:7]) for ym in (r.get("covers") or [])}
        if not (months & RAINY_MONTHS):
            continue
        out.append({"season": r.get("season"), "variable": r.get("variable"),
                    "issuance_ym": r.get("issuance_ym"), "lead": r.get("lead"),
                    "cpc_category_raw": r.get("cpc_category_raw"),
                    "cpc_probability_pct": r.get("cpc_probability_pct"),
                    "status": r.get("status"), "reason": r.get("reason"),
                    "hit": r.get("hit")})
    return out


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def build(datadir=Path("data"), fetch=fetchlib.get, today=None, max_issuances=None):
    """Run the whole back-test.  Pure apart from the injected *fetch*."""
    datadir = Path(datadir)
    today = today or dt.datetime.now(dt.timezone.utc).date()
    manifest, irregularities = [], []

    def note(severity, area, message, evidence=None):
        irregularities.append({"severity": severity, "area": area,
                               "message": message, "evidence": evidence or {}})

    def load(name):
        p = datadir / name
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            return {}

    # ---- the point to sample: the verified centroid, never a typed constant
    run = load("run.json")
    cal = load("calendar.json")
    climo_data = load("climatology.json")
    centroid = ((run.get("target") or {}).get("centroid") or {})
    lat, lon = centroid.get("lat"), centroid.get("lon")
    target = run.get("target") or cal.get("target") or {}
    station_id = ((climo_data.get("meta") or {}).get("precip_station") or {}).get(
        "id") or GHCN_STATION_FALLBACK
    if lat is None or lon is None:
        note("error", "cpc_backtest",
             "No verified centroid is present in data/run.json, so nothing was "
             "sampled. This script never falls back to a hand-typed coordinate: "
             "the point has to be the one the Census file published.",
             {"file": str(datadir / "run.json")})
        return _package(datadir, today, manifest, irregularities, [], None, None,
                        [], [], lat=None, lon=None, station_id=station_id,
                        discovery=None)

    # ---- 1. discovery
    discovery = discover_issuances(fetch=fetch, manifest=manifest, note=note)
    months = list(discovery.get("months") or [])
    if not months:
        months = fallback_months(today)
        discovery["fallback_used"] = True
        discovery["fallback_months"] = months
        discovery["method"] = ("CPC's index page could not be read, so the trailing "
                               f"{len(months)} issuance months were computed from the "
                               "run date; each is then requested and its real HTTP "
                               "status recorded.")

    # ---- 2. observations
    ghcn, ghcn_url, ghcn_res = fetch_ghcn(station_id, fetch=fetch, manifest=manifest)
    if not ghcn:
        note("error", "cpc_backtest",
             f"GHCN-Daily {station_id} could not be retrieved, so no season could be "
             "observed and nothing was scored.",
             {"url": ghcn_url, "status": ghcn_res.status})
    ghcn_last = sorted(ghcn)[-1] if ghcn else None

    # ---- 3. sample every issuance
    previous = load("cpc_backtest.json")
    prev_issuances = {f"{i.get('kind')}_{i.get('issuance_ym')}": i
                      for i in (previous.get("issuances") or [])}
    if max_issuances:
        months = months[-max_issuances:]
    issuances = []
    workdir = Path(tempfile.mkdtemp(prefix="cpcbt_"))
    try:
        for ym in months:
            for kind in ("seasprcp", "seastemp"):
                got = sample_issuance(kind, ym, lat, lon, workdir, fetch=fetch,
                                      manifest=manifest, note=note)
                key = f"{kind}_{ym}"
                if got["ok"]:
                    got["carried_from_previous_run"] = False
                    issuances.append(got)
                    prev_issuances.pop(key, None)
                else:
                    status = got.get("http_status")
                    if status == 404:
                        got["expected_absent"] = "beyond-cpc-retention-window"
                        note("info", "cpc_backtest",
                             f"CPC no longer serves {kind}_{ym}.zip (HTTP 404). The "
                             "monthly/seasonal archive is a rolling window, so this "
                             "issuance is outside it; recorded as an expected absence, "
                             "not a failure.",
                             {"url": got["url"]})
                    else:
                        note("warning", "cpc_backtest",
                             f"{kind}_{ym}.zip could not be fetched "
                             f"(HTTP {status}); its seasons cannot be sampled.",
                             {"url": got["url"], "error": got.get("error")})
                    issuances.append(got)
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)

    # ---- 3b. carry forward issuances CPC has since dropped
    carried = []
    for key, old in sorted(prev_issuances.items()):
        if old.get("ok") and old.get("leads"):
            keep = dict(old)
            keep["carried_from_previous_run"] = True
            keep["still_served_by_cpc"] = False
            carried.append(keep)
    issuances.extend(carried)

    # ---- 4. score
    rows = []
    season_cache = {}
    if ghcn:
        for iss in issuances:
            if not iss.get("ok"):
                continue
            variable = "prcp" if iss["kind"] == "seasprcp" else "temp"
            for lead in iss.get("leads") or []:
                covers = lead.get("covers")
                if not covers:
                    continue
                ck = (variable, tuple(covers))
                if ck not in season_cache:
                    dist = base_distribution(ghcn, covers, variable)
                    obs = observed_period(ghcn, covers, variable)
                    season_cache[ck] = (obs, dist)
                obs, dist = season_cache[ck]
                rows.append(score_pair(lead, iss["issuance_ym"], iss["kind"],
                                       obs, dist, variable))

    # ---- 5. deduplicate: keep the shortest lead for each (season, variable)
    # so one season is not scored 8 times by 8 issuances that all cover it.  The
    # longest-lead views are kept in `all_pairs` for the lead breakdown.
    best = {}
    for r in rows:
        key = (r["variable"], r.get("season"))
        prev = best.get(key)
        if prev is None or (r.get("lead") or 99) < (prev.get("lead") or 99):
            best[key] = r
    deduped = sorted(best.values(), key=lambda r: (r["variable"], str(r.get("season")),
                                                   str(r.get("issuance_ym"))))

    summary = summarise(deduped) if deduped else None
    all_summary = summarise(rows) if rows else None

    return _package(datadir, today, manifest, irregularities, issuances, summary,
                    all_summary, rows, deduped, lat, lon, station_id, ghcn_url,
                    ghcn_res, ghcn_last, discovery)


def _package(datadir, today, manifest, irregularities, issuances, summary,
             all_summary, all_rows, deduped, lat=None, lon=None, station_id=None,
             ghcn_url=None, ghcn_res=None, ghcn_last=None, discovery=None):
    """Assemble the published dataset.  No number here is computed."""
    fetched = [i for i in issuances if i.get("ok")]
    absent = [i for i in issuances if i.get("expected_absent")]
    failed = [i for i in issuances
              if not i.get("ok") and not i.get("expected_absent")]
    months_ok = sorted({i["issuance_ym"] for i in fetched})
    out = {
        "generated_utc": fetchlib.iso_utc(),
        "target": {"zip": "94122", "lat": lat, "lon": lon,
                   "point_source": "the verified Census ZCTA centroid read from "
                                   "data/run.json - never typed into this script"},
        "station_id": station_id,
        "base_period": list(BASE_PERIOD),
        "baseline_pct": BASELINE_PCT,
        "tilt_probability_min_pct": TILT_PROB_MIN,
        "method": {
            "sampling": ("point-in-polygon sample of every lead inside each official "
                         "CPC seasprcp_YYYYMM.zip / seastemp_YYYYMM.zip, using "
                         "pipeline/lib_cpc.py - the same code path that samples the "
                         "live outlook published on the front page"),
            "observed": (f"GHCN-Daily {station_id}: total liquid precipitation (or mean "
                         "of daily (TMAX+TMIN)/2 for temperature) over the exact months "
                         "the CPC season covers; a season with any missing day is not "
                         "scored"),
            "terciles": ("this project's own terciles - nearest-rank 33.3rd and 66.7th "
                         f"percentiles of the {BASE_PERIOD[0]}-{BASE_PERIOD[1]} values of "
                         "the same 3-month season at the same station. They are NOT "
                         "CPC's internal climatological divisions, and the cuts actually "
                         "used are published in every row so the difference is visible"),
            "hit": ("the category CPC named for the polygon containing the point equals "
                    "the tercile the observed season total falls in"),
            "ec": ("a polygon CPC published as 'EC' (equal chances) is no tilt; it is "
                   "counted separately and never scored as a miss"),
            "dedup": ("where several issuances cover the same season, the shortest lead "
                      "is the headline pair; every lead is kept in all_pairs and scored "
                      "in the lead breakdown"),
        },
        "discovery": discovery or {},
        "counts": {
            "issuances_requested": len(issuances),
            "issuances_sampled": len(fetched),
            "issuances_beyond_retention_window": len(absent),
            "issuances_failed": len(failed),
            "issuance_months_sampled": months_ok,
            "leads_sampled": sum(len(i.get("leads") or []) for i in fetched),
            "carried_from_previous_runs":
                sum(1 for i in issuances if i.get("carried_from_previous_run")),
            "pairs": len(all_rows or []),
            "pairs_deduped": len(deduped or []),
            "pairs_scored": (summary or {}).get("overall", {}).get("n_scored", 0),
        },
        "ghcn": {"url": ghcn_url, "http_status": (ghcn_res.status if ghcn_res else None),
                 "sha256": (ghcn_res.sha256 if ghcn_res else None),
                 "last_observed_date": ghcn_last},
        "issuances": issuances,
        "scored": deduped or [],
        "all_pairs": all_rows or [],
        "summary": summary,
        "summary_all_leads": all_summary,
        "rainy_season_pairs": rainy_season_relevance(deduped or []),
        "irregularities": irregularities,
        "limitations": [
            f"CPC's own index page linked {len((discovery or {}).get('months') or [])} "
            "monthly issuance(s) on this run; the monthly/seasonal shapefile archive is "
            "a rolling window, not a permanent one, so issuances older than that window "
            "return HTTP 404 and cannot be back-filled from the publisher.",
            "The IRI Data Library holds a longer archive but requires sign-in "
            f"(verified: {IRI_FINDING['result']}); it is therefore not used. "
            "See docs/DATA_SOURCES.md for the full reasoning.",
            "Every sample is retained in this file, so the hit-rate grows each month "
            "and the Oct-Jan seasons are scored prospectively rather than never.",
            "Small samples: a hit-rate over fewer than about 30 pairs cannot "
            "distinguish skill from luck, and the count is published with it.",
            "Terciles are this project's, computed from GHCN-Daily at the published "
            "station; CPC's own verification uses its internal climatological "
            "divisions, so a boundary case can land in a different third here.",
        ],
        "iri_archive": IRI_FINDING,
        "provenance_note": ("Every URL this script touched is recorded in "
                            "data/cpc_backtest_provenance.json with its HTTP status, "
                            "byte count and SHA-256; pipeline/verify_sources.py checks "
                            "that manifest too."),
    }
    return out, manifest


def write_outputs(out, manifest, datadir):
    datadir = Path(datadir)
    datadir.mkdir(parents=True, exist_ok=True)
    (datadir / "cpc_backtest.json").write_text(
        json.dumps(out, indent=2, sort_keys=False) + "\n")
    provlib.write_manifest(
        datadir, "cpc_backtest", manifest, out["generated_utc"],
        "Fetches made by pipeline/cpc_backtest.py for the CPC seasonal back-test.")
    provlib.merge_irregularities(datadir, "cpc_backtest", out["irregularities"])
    return datadir / "cpc_backtest.json"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datadir", default="data",
                    help="directory holding run.json / climatology.json (default: data)")
    ap.add_argument("--outdir", default=None,
                    help="where to write cpc_backtest.json (default: --datadir)")
    ap.add_argument("--max-issuances", type=int, default=None,
                    help="cap the number of issuance months requested")
    ap.add_argument("--selftest", action="store_true",
                    help="run the whole scoring path offline against a synthetic "
                         "archive (no network, writes nothing)")
    args = ap.parse_args()

    if args.selftest:
        import selftest_cpc_backtest
        return selftest_cpc_backtest.run()

    datadir = Path(args.datadir)
    outdir = Path(args.outdir or args.datadir)
    log(f"CPC back-test - {dt.datetime.now(dt.timezone.utc).date().isoformat()}")
    out, manifest = build(datadir=datadir, max_issuances=args.max_issuances)
    path = write_outputs(out, manifest, outdir)
    c = out["counts"]
    log(f"  issuances: {c['issuances_sampled']} sampled / "
        f"{c['issuances_beyond_retention_window']} beyond CPC's window / "
        f"{c['issuances_failed']} failed")
    log(f"  leads sampled: {c['leads_sampled']}   pairs: {c['pairs']} "
        f"(deduped {c['pairs_deduped']}, scored {c['pairs_scored']})")
    if out.get("summary"):
        o = out["summary"]["overall"]
        log(f"  hit-rate: {o['n_hits']}/{o['n_scored']} = {o['hit_rate_pct']}% "
            f"(baseline {o['baseline_pct']}%)")
    else:
        log("  hit-rate: no pair could be scored on this run - see "
            "data/cpc_backtest.json -> irregularities")
    log(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
